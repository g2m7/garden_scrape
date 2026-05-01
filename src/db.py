"""
SQLite database layer for tea garden data.

Tables:
  gardens        — every tea garden found, with phone status
  scrape_progress — which pincodes have been scraped
  scrape_log     — timestamped log of scraping activity
"""

import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from pathlib import Path

# Always place DB at project root (parent of src/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = str(_PROJECT_ROOT / "tea_gardens.db")


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Create tables if they don't exist. Returns a connection."""
    conn = get_connection(db_path)

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS gardens (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            phone           TEXT,
            has_phone       INTEGER DEFAULT 0,
            phone_status    TEXT DEFAULT 'not_found'
                             CHECK(phone_status IN ('found','not_found','not_listed')),
            address         TEXT,
            pincode         TEXT,
            district        TEXT,
            town            TEXT,
            latitude        REAL,
            longitude       REAL,
            area_hectares   REAL,
            area_source     TEXT DEFAULT 'not_available'
                             CHECK(area_source IN ('google_maps','extracted_text','estimated','not_available')),
            rating          TEXT,
            reviews_count   INTEGER DEFAULT 0,
            category        TEXT,
            google_url      TEXT,
            place_cid       TEXT,
            search_query    TEXT,
            scraped_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

            UNIQUE(name, pincode)
        );

        CREATE INDEX IF NOT EXISTS idx_gardens_pincode   ON gardens(pincode);
        CREATE INDEX IF NOT EXISTS idx_gardens_has_phone ON gardens(has_phone);
        CREATE INDEX IF NOT EXISTS idx_gardens_district  ON gardens(district);
        CREATE INDEX IF NOT EXISTS idx_gardens_place_cid ON gardens(place_cid);

        CREATE TABLE IF NOT EXISTS scrape_progress (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            pincode         TEXT UNIQUE NOT NULL,
            district        TEXT,
            town            TEXT,
            status          TEXT DEFAULT 'pending'
                             CHECK(status IN ('pending','in_progress','completed','empty','failed','blocked')),
            gardens_found   INTEGER DEFAULT 0,
            queries_run     INTEGER DEFAULT 0,
            scraped_at      TEXT,
            duration_secs   REAL DEFAULT 0,
            error           TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_progress_status ON scrape_progress(status);

        CREATE TABLE IF NOT EXISTS scrape_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ts         TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            level      TEXT DEFAULT 'INFO',
            pincode    TEXT,
            message    TEXT
        );
    """)

    conn.commit()
    return conn


# ── Garden CRUD ──────────────────────────────────────────────────

PHONE_RE = re.compile(
    r"(?:\+91[-.\s]?|0)?"          # country / std prefix
    r"(?:"
    r"37[0-9][-.\s]?\d{6,7}"       # Assam landline  037x-xxxxxx
    r"|[6-9]\d{4}[-.\s]?\d{5}"     # mobile
    r"|\d{3,4}[-.\s]\d{3,4}[-.\s]\d{3,4}"  # generic split
    r")"
)


def _classify_phone(raw: str | None) -> tuple[str | None, str]:
    """Return (cleaned_phone, status)."""
    if not raw:
        return None, "not_found"
    # try to find a phone-like substring
    m = PHONE_RE.search(raw)
    if m:
        phone = m.group(0).strip()
        return phone, "found"
    return None, "not_listed"


def upsert_garden(conn: sqlite3.Connection, data: dict[str, Any]) -> int | None:
    """
    Insert or update a garden.  Deduplicates on (name, pincode).
    Returns the row id or None if skipped.
    """
    name = data.get("name", "").strip()
    if not name:
        return None

    phone_raw = data.get("phone")
    phone, phone_status = _classify_phone(phone_raw)

    place_cid = data.get("place_cid") or _extract_cid(data.get("google_url", ""))

    # Try UPDATE first (on conflict of name+pincode)
    try:
        row = conn.execute(
            "SELECT id, phone FROM gardens WHERE name = ? AND pincode = ?",
            (name, data.get("pincode")),
        ).fetchone()

        if row:
            # Only update if we have new info (e.g. now we have a phone)
            updates = {}
            if phone and not row["phone"]:
                updates["phone"] = phone
                updates["has_phone"] = 1
                updates["phone_status"] = "found"
            if data.get("address"):
                updates["address"] = data["address"]
            if data.get("latitude"):
                updates["latitude"] = data["latitude"]
            if data.get("longitude"):
                updates["longitude"] = data["longitude"]
            if data.get("rating"):
                updates["rating"] = data["rating"]
            if data.get("category"):
                updates["category"] = data["category"]
            if data.get("google_url"):
                updates["google_url"] = data["google_url"]
            if place_cid:
                updates["place_cid"] = place_cid
            if data.get("district"):
                updates["district"] = data["district"]
            if data.get("area_hectares") is not None:
                updates["area_hectares"] = data["area_hectares"]
                updates["area_source"] = data.get("area_source", "extracted_text")

            if updates:
                updates["updated_at"] = datetime.utcnow().isoformat()
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE gardens SET {set_clause} WHERE id = ?",
                    (*updates.values(), row["id"]),
                )
                conn.commit()
            return row["id"]

        # INSERT
        cur = conn.execute(
            """INSERT INTO gardens
               (name, phone, has_phone, phone_status, address, pincode, district, town,
                latitude, longitude, area_hectares, area_source,
                rating, reviews_count, category,
                google_url, place_cid, search_query)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                name,
                phone,
                1 if phone else 0,
                phone_status,
                data.get("address"),
                data.get("pincode"),
                data.get("district"),
                data.get("town"),
                data.get("latitude"),
                data.get("longitude"),
                data.get("area_hectares"),
                data.get("area_source", "not_available"),
                data.get("rating"),
                data.get("reviews_count", 0),
                data.get("category"),
                data.get("google_url"),
                place_cid,
                data.get("search_query"),
            ),
        )
        conn.commit()
        return cur.lastrowid

    except sqlite3.IntegrityError:
        # race duplicate — safe to ignore
        return None


def _extract_cid(url: str) -> str | None:
    """Extract Google Maps CID from a URL for dedup."""
    if not url:
        return None
    # data=!...1s0x1234:0x5678...  →  the hex after 0x before :
    m = re.search(r"1s0x([0-9a-fA-F]+):0x([0-9a-fA-F]+)", url)
    if m:
        return f"0x{m.group(1)}:0x{m.group(2)}"
    return None


def garden_exists_by_cid(conn: sqlite3.Connection, cid: str) -> bool:
    """Check if a garden with this CID already exists."""
    if not cid:
        return False
    row = conn.execute(
        "SELECT 1 FROM gardens WHERE place_cid = ? LIMIT 1", (cid,)
    ).fetchone()
    return row is not None


# ── Progress tracking ────────────────────────────────────────────

def mark_pincode(
    conn: sqlite3.Connection,
    pincode: str,
    district: str,
    town: str,
    status: str,
    gardens_found: int = 0,
    queries_run: int = 0,
    duration_secs: float = 0,
    error: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO scrape_progress
           (pincode, district, town, status, gardens_found, queries_run,
            scraped_at, duration_secs, error)
           VALUES (?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'),?,?)
           ON CONFLICT(pincode) DO UPDATE SET
             status=excluded.status,
             gardens_found=excluded.gardens_found,
             queries_run=excluded.queries_run,
             scraped_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
             duration_secs=excluded.duration_secs,
             error=excluded.error
        """,
        (pincode, district, town, status, gardens_found, queries_run, duration_secs, error),
    )
    conn.commit()


def get_pending_pincodes(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """Return (pincode, district, town) for pincodes not yet completed."""
    rows = conn.execute(
        "SELECT pincode, district, town FROM scrape_progress "
        "WHERE status IN ('pending','failed')"
    ).fetchall()
    return [(r["pincode"], r["district"], r["town"]) for r in rows]


def init_progress(conn: sqlite3.Connection, pincodes: list[tuple[str, str, str]]) -> int:
    """Seed progress table. Returns count of newly inserted pincodes."""
    count = 0
    for pin, district, town in pincodes:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO scrape_progress (pincode, district, town) VALUES (?,?,?)",
                (pin, district, town),
            )
            count += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return count


# ── Logging ──────────────────────────────────────────────────────

def log(conn: sqlite3.Connection, level: str, message: str, pincode: str | None = None) -> None:
    try:
        conn.execute(
            "INSERT INTO scrape_log (level, pincode, message) VALUES (?,?,?)",
            (level, pincode, message),
        )
        conn.commit()
    except Exception:
        pass  # never let logging crash the scraper


# ── Query helpers ────────────────────────────────────────────────

def get_stats(conn: sqlite3.Connection) -> dict:
    """Return summary statistics."""
    total = conn.execute("SELECT COUNT(*) c FROM gardens").fetchone()["c"]
    with_phone = conn.execute("SELECT COUNT(*) c FROM gardens WHERE has_phone = 1").fetchone()["c"]
    by_district = conn.execute(
        "SELECT district, COUNT(*) c FROM gardens GROUP BY district ORDER BY c DESC"
    ).fetchall()
    by_status = conn.execute(
        "SELECT phone_status, COUNT(*) c FROM gardens GROUP BY phone_status"
    ).fetchall()
    progress = conn.execute(
        "SELECT status, COUNT(*) c FROM scrape_progress GROUP BY status"
    ).fetchall()
    return {
        "total_gardens": total,
        "with_phone": with_phone,
        "without_phone": total - with_phone,
        "by_district": {r["district"]: r["c"] for r in by_district},
        "by_phone_status": {r["phone_status"]: r["c"] for r in by_status},
        "progress": {r["status"]: r["c"] for r in progress},
    }


def export_to_csv(conn: sqlite3.Connection, filepath: str) -> int:
    """Export all gardens to CSV. Returns row count."""
    import csv
    rows = conn.execute(
        """SELECT name, phone, has_phone, phone_status, address, pincode,
                  district, town, latitude, longitude, area_hectares, area_source,
                  rating, reviews_count, category, google_url, scraped_at
           FROM gardens ORDER BY district, pincode, name"""
    ).fetchall()

    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    columns = [
        "name", "phone", "has_phone", "phone_status", "address", "pincode",
        "district", "town", "latitude", "longitude", "area_hectares", "area_source",
        "rating", "reviews_count", "category", "google_url", "scraped_at",
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))

    return len(rows)


def export_phones_csv(conn: sqlite3.Connection, filepath: str) -> int:
    """Export only gardens WITH phone numbers. Returns row count."""
    import csv
    rows = conn.execute(
        """SELECT name, phone, address, pincode, district, town,
                  latitude, longitude, area_hectares, area_source, google_url
           FROM gardens WHERE has_phone = 1
           ORDER BY district, pincode, name"""
    ).fetchall()

    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    columns = [
        "name", "phone", "address", "pincode", "district", "town",
        "latitude", "longitude", "area_hectares", "area_source", "google_url",
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))

    return len(rows)
