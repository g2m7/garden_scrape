import sqlite3
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = str(_PROJECT_ROOT / "tea_gardens.db")


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS gardens (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,

    phone             TEXT,
    email             TEXT,
    email_confidence  REAL DEFAULT 0,
    website           TEXT,

    address           TEXT,
    pincode           TEXT,
    district          TEXT,
    state             TEXT DEFAULT 'Assam',
    town              TEXT,
    latitude          REAL,
    longitude         REAL,

    area_hectares     REAL,
    area_bigha        REAL,
    workforce         INTEGER,

    category          TEXT,
    google_url        TEXT,
    place_cid         TEXT,
    rating            TEXT,
    reviews_count     INTEGER DEFAULT 0,

    confidence_score  REAL DEFAULT 0.5,
    data_source       TEXT NOT NULL DEFAULT 'unknown',
    data_freshness    TEXT,
    search_query      TEXT,

    created_at        TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at        TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    UNIQUE(name, pincode, district)
);

CREATE INDEX IF NOT EXISTS idx_gardens_pincode ON gardens(pincode);
CREATE INDEX IF NOT EXISTS idx_gardens_district ON gardens(district);
CREATE INDEX IF NOT EXISTS idx_gardens_state ON gardens(state);
CREATE INDEX IF NOT EXISTS idx_gardens_phone ON gardens(phone) WHERE phone IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_gardens_email ON gardens(email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_gardens_source ON gardens(data_source);
CREATE INDEX IF NOT EXISTS idx_gardens_confidence ON gardens(confidence_score);
CREATE INDEX IF NOT EXISTS idx_gardens_has_email ON gardens(email) WHERE email IS NOT NULL;

CREATE TABLE IF NOT EXISTS data_provenance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    garden_id   INTEGER NOT NULL REFERENCES gardens(id),
    field_name  TEXT NOT NULL,
    field_value TEXT,
    source_file TEXT,
    source_type TEXT,
    confidence  REAL DEFAULT 0.5,
    collected_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS idx_prov_garden ON data_provenance(garden_id);

CREATE TABLE IF NOT EXISTS email_crawl_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    garden_id   INTEGER REFERENCES gardens(id),
    garden_name TEXT,
    url_crawled TEXT,
    emails_found TEXT,
    status      TEXT DEFAULT 'pending',
    crawled_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    error       TEXT
);

CREATE TABLE IF NOT EXISTS garden_emails (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    garden_id   INTEGER NOT NULL REFERENCES gardens(id),
    email       TEXT NOT NULL,
    confidence  REAL DEFAULT 0.5,
    source_url  TEXT,
    source_type TEXT DEFAULT 'crawl',
    found_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(garden_id, email)
);

CREATE INDEX IF NOT EXISTS idx_gemails_garden ON garden_emails(garden_id);
CREATE INDEX IF NOT EXISTS idx_gemails_email ON garden_emails(email);

CREATE TABLE IF NOT EXISTS source_files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    filename     TEXT NOT NULL UNIQUE,
    file_type    TEXT,
    record_count INTEGER,
    status       TEXT DEFAULT 'Not Processed',
    processed_at TEXT,
    notes        TEXT
);
"""


def init_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r'\D', '', str(raw))
    if len(digits) == 12 and digits.startswith('91'):
        digits = digits[2:]
    if len(digits) >= 10:
        return digits[-10:]
    return None


def _compute_confidence(data: dict) -> float:
    score = 0.1
    if data.get("phone"):
        score += 0.15
    if data.get("email"):
        score += 0.15
    if data.get("address"):
        score += 0.1
    if data.get("district"):
        score += 0.1
    if data.get("pincode"):
        score += 0.1
    if data.get("latitude") and data.get("longitude"):
        score += 0.1
    if data.get("area_hectares"):
        score += 0.1
    if data.get("google_url"):
        score += 0.1
    return min(score, 1.0)


def upsert_garden(conn: sqlite3.Connection, data: dict[str, Any]) -> int | None:
    name = (data.get("name") or "").strip()
    if not name:
        return None

    phone = _normalize_phone(data.get("phone"))
    email = data.get("email")
    if email:
        email = email.strip().lower()
    website = data.get("website")
    if website:
        website = website.strip()

    district = (data.get("district") or "").strip() or None
    state = (data.get("state") or "Assam").strip()
    pincode = (data.get("pincode") or "").strip() or None

    data_source = data.get("data_source", "unknown")
    confidence = data.get("confidence_score") or _compute_confidence(data)
    data_freshness = data.get("data_freshness") or datetime.utcnow().isoformat()

    existing = conn.execute(
        "SELECT id, phone, email, website, confidence_score FROM gardens WHERE name = ? AND (pincode = ? OR district = ?)",
        (name, pincode, district),
    ).fetchone()

    if existing:
        updates = {}
        if phone and not existing["phone"]:
            updates["phone"] = phone
        if email and not existing["email"]:
            updates["email"] = email
            updates["email_confidence"] = data.get("email_confidence", 0.7)
        if website and not existing["website"]:
            updates["website"] = website
        for field in ("address", "district", "state", "town", "pincode",
                       "latitude", "longitude", "area_hectares", "area_bigha",
                       "workforce", "category", "google_url", "place_cid",
                       "rating", "reviews_count"):
            if data.get(field) is not None:
                updates[field] = data[field]
        new_conf = max(confidence, existing["confidence_score"])
        updates["confidence_score"] = new_conf
        updates["updated_at"] = datetime.utcnow().isoformat()
        if data_source:
            existing_sources = conn.execute(
                "SELECT data_source FROM gardens WHERE id = ?", (existing["id"],)
            ).fetchone()["data_source"]
            if data_source not in existing_sources:
                updates["data_source"] = f"{existing_sources},{data_source}"

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE gardens SET {set_clause} WHERE id = ?",
            (*updates.values(), existing["id"]),
        )
        conn.commit()

        if data.get("_source_file"):
            _add_provenance(conn, existing["id"], data, data.get("_source_file"))

        return existing["id"]

    cur = conn.execute(
        """INSERT INTO gardens
           (name, phone, email, email_confidence, website,
            address, pincode, district, state, town,
            latitude, longitude, area_hectares, area_bigha, workforce,
            category, google_url, place_cid, rating, reviews_count,
            confidence_score, data_source, data_freshness, search_query)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            name, phone, email, data.get("email_confidence", 0),
            website,
            data.get("address"), pincode, district, state, data.get("town"),
            data.get("latitude"), data.get("longitude"),
            data.get("area_hectares"), data.get("area_bigha"), data.get("workforce"),
            data.get("category"), data.get("google_url"), data.get("place_cid"),
            data.get("rating"), data.get("reviews_count", 0),
            confidence, data_source, data_freshness, data.get("search_query"),
        ),
    )
    conn.commit()
    garden_id = cur.lastrowid

    if data.get("_source_file"):
        _add_provenance(conn, garden_id, data, data["_source_file"])

    if email:
        add_garden_email(conn, garden_id, email, confidence=data.get("email_confidence", 0.7),
                         source_type="source_file")

    return garden_id


def _add_provenance(conn: sqlite3.Connection, garden_id: int, data: dict, source_file: str):
    source_type = Path(source_file).suffix.lstrip(".") if source_file else "unknown"
    for field, value in data.items():
        if value is not None and not field.startswith("_") and field not in ("name",):
            try:
                conn.execute(
                    "INSERT INTO data_provenance (garden_id, field_name, field_value, source_file, source_type) VALUES (?,?,?,?,?)",
                    (garden_id, field, str(value), source_file, source_type),
                )
            except Exception:
                pass
    conn.commit()


def upsert_source_file(conn: sqlite3.Connection, filename: str, file_type: str = None,
                       record_count: int = 0, status: str = "Not Processed", notes: str = None):
    conn.execute(
        """INSERT INTO source_files (filename, file_type, record_count, status, processed_at, notes)
           VALUES (?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'),?)
           ON CONFLICT(filename) DO UPDATE SET
             record_count=excluded.record_count,
             status=excluded.status,
             processed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
             notes=COALESCE(excluded.notes, source_files.notes)
        """,
        (filename, file_type, record_count, status, notes),
    )
    conn.commit()


def get_stats(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) c FROM gardens").fetchone()["c"]
    with_phone = conn.execute("SELECT COUNT(*) c FROM gardens WHERE phone IS NOT NULL").fetchone()["c"]
    with_email = conn.execute("SELECT COUNT(*) c FROM gardens WHERE email IS NOT NULL").fetchone()["c"]
    with_website = conn.execute("SELECT COUNT(*) c FROM gardens WHERE website IS NOT NULL").fetchone()["c"]

    by_district = conn.execute(
        "SELECT district, COUNT(*) c FROM gardens WHERE district IS NOT NULL GROUP BY district ORDER BY c DESC"
    ).fetchall()

    by_source = conn.execute(
        "SELECT data_source, COUNT(*) c FROM gardens GROUP BY data_source ORDER BY c DESC"
    ).fetchall()

    avg_confidence = conn.execute("SELECT AVG(confidence_score) a FROM gardens").fetchone()["a"] or 0

    by_state = conn.execute(
        "SELECT state, COUNT(*) c FROM gardens GROUP BY state ORDER BY c DESC"
    ).fetchall()

    return {
        "total": total,
        "with_phone": with_phone,
        "without_phone": total - with_phone,
        "with_email": with_email,
        "without_email": total - with_email,
        "with_website": with_website,
        "by_district": {r["district"]: r["c"] for r in by_district},
        "by_source": {r["data_source"]: r["c"] for r in by_source},
        "by_state": {r["state"]: r["c"] for r in by_state},
        "avg_confidence": round(avg_confidence, 3),
    }


VALID_DISTRICTS = {
    "Dibrugarh", "Jorhat", "Tinsukia", "Sivasagar", "Golaghat",
    "Kamrup", "Sonitpur", "Cachar", "Nagaon", "Lakhimpur",
    "Dooars", "Darjeeling", "Jalpaiguri", "Cooch Behar",
    "North Tripura", "South Tripura", "West Tripura",
    "Kamrup Metro", "Dhemaji", "Biswanath", "Hojai",
    "Charaideo", "Majuli", "West Karbi Anglong", "Karbi Anglong",
    "Dima Hasao", "Karimganj", "Hailakandi", "Barpeta",
    "Goalpara", "Kokrajhar", "Baksa", "Chirang", "Udalguri",
    "Tamulpur", "Bajali", "South Salmara", "Dhubri",
    "Morigaon", "Golaghat",
}

def cleanup_bad_data(conn: sqlite3.Connection) -> dict:
    cleaned = {}

    bad_districts = conn.execute(
        "SELECT id, district FROM gardens WHERE district IS NOT NULL AND length(district) > 30"
    ).fetchall()
    for row in bad_districts:
        conn.execute("UPDATE gardens SET district = NULL WHERE id = ?", (row["id"],))
    cleaned["long_districts_nulled"] = len(bad_districts)

    bad_names = conn.execute(
        "SELECT id, name FROM gardens WHERE length(name) > 80 OR name GLOB '*[0-9][0-9][0-9][0-9]*'"
    ).fetchall()
    for row in bad_names:
        conn.execute("DELETE FROM data_provenance WHERE garden_id = ?", (row["id"],))
        conn.execute("DELETE FROM email_crawl_log WHERE garden_id = ?", (row["id"],))
        conn.execute("DELETE FROM gardens WHERE id = ?", (row["id"],))
    cleaned["bad_names_deleted"] = len(bad_names)

    email_entries = conn.execute(
        "SELECT id, name FROM gardens WHERE name LIKE 'Tea Estate (%'"
    ).fetchall()
    cleaned["email_placeholder_entries"] = len(email_entries)

    conn.commit()
    return cleaned


def query_gardens(conn: sqlite3.Connection,
                  district: str | None = None,
                  state: str | None = None,
                  has_phone: bool | None = None,
                  has_email: bool | None = None,
                  source: str | None = None,
                  min_confidence: float | None = None,
                  max_confidence: float | None = None,
                  search: str | None = None,
                  order_by: str = "district ASC, name ASC",
                  limit: int = 1000,
                  offset: int = 0) -> list[dict]:
    where_clauses = []
    params = []

    if district:
        where_clauses.append("district = ?")
        params.append(district)
    if state:
        where_clauses.append("state = ?")
        params.append(state)
    if has_phone is True:
        where_clauses.append("phone IS NOT NULL")
    elif has_phone is False:
        where_clauses.append("phone IS NULL")
    if has_email is True:
        where_clauses.append("email IS NOT NULL")
    elif has_email is False:
        where_clauses.append("email IS NULL")
    if source:
        where_clauses.append("data_source LIKE ?")
        params.append(f"%{source}%")
    if min_confidence is not None:
        where_clauses.append("confidence_score >= ?")
        params.append(min_confidence)
    if max_confidence is not None:
        where_clauses.append("confidence_score <= ?")
        params.append(max_confidence)
    if search:
        where_clauses.append("(name LIKE ? OR address LIKE ? OR email LIKE ? OR phone LIKE ?)")
        params.extend([f"%{search}%"] * 4)

    where = " AND ".join(where_clauses) if where_clauses else "1=1"

    valid_orders = {"district", "name", "phone", "email", "confidence_score", "data_source",
                    "pincode", "state", "area_hectares", "rating", "created_at", "updated_at"}
    for token in order_by.replace(",", " ").split():
        clean = token.strip().replace(" ASC", "").replace(" DESC", "")
        if clean not in valid_orders:
            order_by = "district ASC, name ASC"
            break

    rows = conn.execute(
        f"""SELECT * FROM gardens WHERE {where} ORDER BY {order_by} LIMIT ? OFFSET ?""",
        (*params, limit, offset),
    ).fetchall()

    return [dict(r) for r in rows]


def count_gardens(conn: sqlite3.Connection,
                  district: str | None = None,
                  state: str | None = None,
                  has_phone: bool | None = None,
                  has_email: bool | None = None,
                  source: str | None = None,
                  min_confidence: float | None = None,
                  max_confidence: float | None = None,
                  search: str | None = None) -> int:
    where_clauses = []
    params = []

    if district:
        where_clauses.append("district = ?")
        params.append(district)
    if state:
        where_clauses.append("state = ?")
        params.append(state)
    if has_phone is True:
        where_clauses.append("phone IS NOT NULL")
    elif has_phone is False:
        where_clauses.append("phone IS NULL")
    if has_email is True:
        where_clauses.append("email IS NOT NULL")
    elif has_email is False:
        where_clauses.append("email IS NULL")
    if source:
        where_clauses.append("data_source LIKE ?")
        params.append(f"%{source}%")
    if min_confidence is not None:
        where_clauses.append("confidence_score >= ?")
        params.append(min_confidence)
    if max_confidence is not None:
        where_clauses.append("confidence_score <= ?")
        params.append(max_confidence)
    if search:
        where_clauses.append("(name LIKE ? OR address LIKE ? OR email LIKE ? OR phone LIKE ?)")
        params.extend([f"%{search}%"] * 4)

    where = " AND ".join(where_clauses) if where_clauses else "1=1"
    return conn.execute(f"SELECT COUNT(*) c FROM gardens WHERE {where}", params).fetchone()["c"]


def get_distinct_values(conn: sqlite3.Connection, column: str) -> list[str]:
    valid = {"district", "state", "data_source", "pincode", "category"}
    if column not in valid:
        return []
    rows = conn.execute(
        f"SELECT DISTINCT {column} FROM gardens WHERE {column} IS NOT NULL ORDER BY {column}"
    ).fetchall()
    return [r[0] for r in rows]


def export_to_xlsx(conn: sqlite3.Connection, filepath: str,
                   district: str | None = None,
                   state: str | None = None,
                   has_phone: bool | None = None,
                   has_email: bool | None = None,
                   source: str | None = None,
                   min_confidence: float | None = None,
                   max_confidence: float | None = None,
                   search: str | None = None) -> int:
    import pandas as pd
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    total = count_gardens(conn, district, state, has_phone, has_email, source,
                          min_confidence, max_confidence, search)
    all_rows = []
    batch = 5000
    for offset in range(0, total, batch):
        rows = query_gardens(conn, district, state, has_phone, has_email, source,
                             min_confidence, max_confidence, search,
                             limit=batch, offset=offset)
        all_rows.extend(rows)

    if not all_rows:
        return 0

    df = pd.DataFrame(all_rows)

    cols_order = [
        "name", "phone", "email", "website", "address", "pincode",
        "district", "state", "town", "latitude", "longitude",
        "area_hectares", "area_bigha", "workforce", "category",
        "confidence_score", "data_source", "data_freshness",
        "google_url", "rating", "reviews_count", "created_at", "updated_at",
    ]
    cols_present = [c for c in cols_order if c in df.columns]
    df = df[cols_present]

    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Gardens", index=False)

        stats = get_stats(conn)
        stats_df = pd.DataFrame([
            {"Metric": "Total Gardens", "Value": stats["total"]},
            {"Metric": "With Phone", "Value": stats["with_phone"]},
            {"Metric": "With Email", "Value": stats["with_email"]},
            {"Metric": "With Website", "Value": stats["with_website"]},
            {"Metric": "Avg Confidence", "Value": stats["avg_confidence"]},
        ])
        stats_df.to_excel(writer, sheet_name="Summary", index=False)

        if stats["by_district"]:
            dist_df = pd.DataFrame(
                [{"District": k, "Count": v} for k, v in stats["by_district"].items()]
            )
            dist_df.to_excel(writer, sheet_name="By District", index=False)

        email_rows = conn.execute(
            """SELECT g.name, g.district, g.state, ge.email, ge.confidence, ge.source_type, ge.source_url, ge.found_at
               FROM garden_emails ge
               JOIN gardens g ON g.id = ge.garden_id
               ORDER BY g.name, ge.confidence DESC"""
        ).fetchall()
        if email_rows:
            email_df = pd.DataFrame([dict(r) for r in email_rows])
            email_df.to_excel(writer, sheet_name="All Emails", index=False)

    return len(df)


def add_garden_email(conn: sqlite3.Connection, garden_id: int, email: str,
                     confidence: float = 0.5, source_url: str = None,
                     source_type: str = "crawl"):
    email = email.strip().lower()
    if not email or "@" not in email:
        return None
    try:
        cur = conn.execute(
            """INSERT INTO garden_emails (garden_id, email, confidence, source_url, source_type)
               VALUES (?,?,?,?,?)
               ON CONFLICT(garden_id, email) DO UPDATE SET
                 confidence = MAX(garden_emails.confidence, excluded.confidence),
                 source_url = COALESCE(excluded.source_url, garden_emails.source_url),
                 found_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
            """,
            (garden_id, email, confidence, source_url, source_type),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        return None


def get_garden_emails(conn: sqlite3.Connection, garden_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM garden_emails WHERE garden_id = ? ORDER BY confidence DESC",
        (garden_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_gardens_without_emails(conn: sqlite3.Connection, limit: int = 0) -> list[dict]:
    q = """
        SELECT g.id, g.name, g.district, g.state, g.google_url
        FROM gardens g
        LEFT JOIN garden_emails ge ON ge.garden_id = g.id
        WHERE ge.id IS NULL
        ORDER BY g.confidence_score DESC
    """
    if limit > 0:
        q += f" LIMIT {limit}"
    rows = conn.execute(q).fetchall()
    return [dict(r) for r in rows]


def get_garden_emails_batch(conn: sqlite3.Connection, garden_ids: list[int]) -> dict[int, list[dict]]:
    if not garden_ids:
        return {}
    placeholders = ",".join("?" * len(garden_ids))
    rows = conn.execute(
        f"SELECT * FROM garden_emails WHERE garden_id IN ({placeholders}) ORDER BY confidence DESC",
        garden_ids,
    ).fetchall()
    result: dict[int, list[dict]] = {}
    for r in rows:
        gid = r["garden_id"]
        result.setdefault(gid, []).append(dict(r))
    return result
