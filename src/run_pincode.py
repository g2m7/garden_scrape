"""
Pincode-wise tea garden scraper for Assam.

Usage:
    python run_pincode.py                          # scrape all pincodes
    python run_pincode.py --district Dibrugarh     # one district
    python run_pincode.py --pincode 786001         # one pincode
    python run_pincode.py --resume                  # continue where we left off
    python run_pincode.py --export                  # export DB to CSV (no scraping)
    python run_pincode.py --stats                   # show DB statistics
    python run_pincode.py --headless false          # show browser window
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Fix Windows encoding
if sys.platform == "win32":
    import os
    os.environ["PYTHONIOENCODING"] = "utf-8"

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args():
    p = argparse.ArgumentParser(description="Pincode-wise tea garden scraper for Assam")

    p.add_argument("--district", type=str, help="Scrape only this district")
    p.add_argument("--pincode", type=str, help="Scrape only this pincode")
    p.add_argument("--pincodes-file", type=str, help="File with one pincode per line")
    p.add_argument("--resume", action="store_true", help="Resume from last run (skip completed)")
    p.add_argument("--headless", type=str, default="true",
                   help="Run headless (true/false, default: true)")
    p.add_argument("--db", type=str, default="tea_gardens.db", help="SQLite database path")
    p.add_argument("--export", action="store_true", help="Export DB to CSV and exit")
    p.add_argument("--stats", action="store_true", help="Show DB statistics and exit")
    p.add_argument("--reset-pincode", type=str, help="Reset a specific pincode to pending")
    p.add_argument("--max-pincodes", type=int, default=0,
                   help="Limit number of pincodes to scrape this run (0=all)")
    return p.parse_args()


def build_pincode_list(args) -> list[tuple[str, str, str]]:
    """Build list of (pincode, district, town) to process."""
    from pincode_data import get_all_pincodes, get_pincodes_for_district

    if args.pincode:
        # Find the pincode in our database
        all_pins = {p[0]: p for p in get_all_pincodes()}
        if args.pincode in all_pins:
            return [all_pins[args.pincode]]
        # Unknown pincode — still allow it
        return [(args.pincode, "Unknown", "Unknown")]

    if args.district:
        return get_pincodes_for_district(args.district)

    if args.pincodes_file:
        pins = []
        all_pins = {p[0]: p for p in get_all_pincodes()}
        with open(args.pincodes_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if line in all_pins:
                        pins.append(all_pins[line])
                    else:
                        pins.append((line, "Unknown", "Unknown"))
        return pins

    return get_all_pincodes()


def run_scraper(args) -> int:
    """Main scraping loop."""
    import sqlite3
    from db import init_db, init_progress, get_pending_pincodes, get_stats, log as db_log
    from maps_scraper import GoogleMapsScraper, ScraperConfig

    # ── Setup ──
    conn = init_db(args.db)
    pincodes = build_pincode_list(args)

    if args.resume:
        # Only scrape pincodes that aren't completed yet
        pending = get_pending_pincodes(conn)
        pending_set = {p[0] for p in pending}
        pincodes = [p for p in pincodes if p[0] in pending_set]
        logger.info("Resuming — %d pincodes remaining", len(pincodes))

    if not pincodes:
        logger.info("No pincodes to process!")
        conn.close()
        return 0

    if args.max_pincodes > 0:
        pincodes = pincodes[:args.max_pincodes]
        logger.info("Limited to %d pincodes this run", len(pincodes))

    # Seed progress table
    init_progress(conn, pincodes)

    # ── Banner ──
    total_pins = len(pincodes)
    districts = sorted(set(p[1] for p in pincodes))
    print()
    print("=" * 60)
    print("  ASSAM TEA GARDEN SCRAPER — PINCODE-WISE")
    print("=" * 60)
    print(f"  Pincodes to scrape : {total_pins}")
    print(f"  Districts          : {', '.join(districts)}")
    print(f"  Database           : {args.db}")
    print(f"  Headless           : {args.headless}")
    print("=" * 60)
    print()

    # ── Run ──
    headless = args.headless.lower() in ("true", "1", "yes")
    cfg = ScraperConfig(headless=headless)
    scraper = GoogleMapsScraper(cfg)

    total_gardens = 0
    total_pins_done = 0

    try:
        scraper.start()

        for i, (pincode, district, town) in enumerate(pincodes, 1):
            logger.info(
                "[%d/%d] Pincode %s — %s, %s",
                i, total_pins, pincode, town, district,
            )

            try:
                new = scraper.scrape_pincode(pincode, district, town, conn)
                total_gardens += new
                total_pins_done += 1
            except KeyboardInterrupt:
                logger.warning("Interrupted by user!")
                db_log(conn, "WARN", "Interrupted by user", pincode)
                break
            except Exception as e:
                logger.error("Pincode %s failed: %s", pincode, e, exc_info=True)
                db_log(conn, "ERROR", f"Pincode failed: {e}", pincode)
                continue

            # Show running stats
            if i % 5 == 0 or i == total_pins:
                stats = get_stats(conn)
                area_count = conn.execute(
                    "SELECT COUNT(*) c FROM gardens WHERE area_hectares IS NOT NULL"
                ).fetchone()["c"]
                logger.info(
                    "  -- Running total: %d gardens (%d with phone, %d with area) --",
                    stats["total_gardens"],
                    stats["with_phone"],
                    area_count,
                )

    except KeyboardInterrupt:
        logger.warning("Stopped by user!")
    finally:
        scraper.stop()
        conn.close()

    # ── Final summary ──
    print()
    print("=" * 60)
    print("  SCRAPING COMPLETE")
    print("=" * 60)
    print(f"  Pincodes processed : {total_pins_done}/{total_pins}")
    print(f"  New gardens found  : {total_gardens}")
    print(f"  Database           : {args.db}")
    print()
    print("  Run with --stats to see full breakdown")
    print("  Run with --export to save CSV files")
    print("=" * 60)

    return 0


def show_stats(args) -> int:
    """Display database statistics."""
    from db import init_db, get_stats
    conn = init_db(args.db)
    stats = get_stats(conn)

    print()
    print("=" * 60)
    print("  DATABASE STATISTICS")
    print("=" * 60)
    print(f"  Total gardens    : {stats['total_gardens']}")
    print(f"  With phone       : {stats['with_phone']}")
    print(f"  Without phone    : {stats['without_phone']}")
    print()
    print("  By District:")
    for dist, count in stats["by_district"].items():
        print(f"    {dist:20s} : {count}")
    print()
    print("  Phone Status:")
    for status, count in stats["by_phone_status"].items():
        print(f"    {status:20s} : {count}")
    print()
    print("  Scraping Progress:")
    for status, count in stats["progress"].items():
        print(f"    {status:20s} : {count}")
    print("=" * 60)
    print()

    conn.close()
    return 0


def export_data(args) -> int:
    """Export database to CSV files."""
    from db import init_db, export_to_csv, export_phones_csv, get_stats
    conn = init_db(args.db)
    stats = get_stats(conn)

    print()
    print("=" * 60)
    print("  EXPORTING TO CSV")
    print("=" * 60)

    # Full export
    all_count = export_to_csv(conn, "output/all_gardens.csv")
    print(f"  all_gardens.csv     : {all_count} gardens")

    # Phone-only export
    phone_count = export_phones_csv(conn, "output/gardens_with_phones.csv")
    print(f"  gardens_with_phones : {phone_count} gardens with phone numbers")

    # Per-district exports
    districts = conn.execute(
        "SELECT DISTINCT district FROM gardens ORDER BY district"
    ).fetchall()
    for row in districts:
        district = row["district"]
        if not district:
            continue
        safe = district.replace(" ", "_").lower()
        path = f"output/district_wise/{safe}_gardens.csv"

        import csv
        rows = conn.execute(
            """SELECT name, phone, has_phone, phone_status, address, pincode,
                      district, town, latitude, longitude, area_hectares, area_source,
                      rating, reviews_count, category, google_url, scraped_at
               FROM gardens WHERE district = ? ORDER BY pincode, name""",
            (district,),
        ).fetchall()
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        columns = [
            "name", "phone", "has_phone", "phone_status", "address", "pincode",
            "district", "town", "latitude", "longitude", "area_hectares", "area_source",
            "rating", "reviews_count", "category", "google_url", "scraped_at",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for r in rows:
                writer.writerow(dict(r))

        print(f"  {path:45s} : {len(rows)} gardens")

    print()
    print(f"  Total in DB: {stats['total_gardens']} ({stats['with_phone']} with phone)")
    print("=" * 60)
    print()

    conn.close()
    return 0


def reset_pincode(args) -> int:
    """Reset a pincode's status to pending."""
    from db import init_db
    conn = init_db(args.db)
    conn.execute(
        "UPDATE scrape_progress SET status = 'pending', error = NULL WHERE pincode = ?",
        (args.reset_pincode,),
    )
    conn.commit()
    affected = conn.total_changes
    print(f"Reset pincode {args.reset_pincode} to pending (affected: {affected})")
    conn.close()
    return 0


def main() -> int:
    args = parse_args()

    if args.stats:
        return show_stats(args)

    if args.export:
        return export_data(args)

    if args.reset_pincode:
        return reset_pincode(args)

    return run_scraper(args)


if __name__ == "__main__":
    sys.exit(main())
