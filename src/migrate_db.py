import sqlite3
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from db_v2 import init_db, upsert_garden, DB_PATH, get_connection

logger = logging.getLogger(__name__)

OLD_DB = str(Path(__file__).resolve().parent.parent / "tea_gardens.db")


def migrate_old_to_v2():
    conn_new = init_db()

    old_path = OLD_DB
    if not Path(old_path).exists():
        logger.info("No existing DB to migrate from")
        return

    conn_old = sqlite3.connect(old_path)
    conn_old.row_factory = sqlite3.Row

    try:
        old_gardens = conn_old.execute(
            "SELECT * FROM gardens"
        ).fetchall()
    except sqlite3.OperationalError:
        logger.info("Old gardens table not found, nothing to migrate")
        conn_old.close()
        return

    migrated = 0
    for row in old_gardens:
        data = {
            "name": row["name"],
            "phone": row["phone"],
            "address": row["address"],
            "pincode": row["pincode"],
            "district": row["district"],
            "state": "Assam",
            "town": row["town"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "area_hectares": row["area_hectares"],
            "category": row["category"],
            "google_url": row["google_url"],
            "place_cid": row["place_cid"],
            "rating": row["rating"],
            "reviews_count": row["reviews_count"],
            "data_source": "google_maps_pincode_sweep",
            "data_freshness": row["scraped_at"],
            "search_query": row["search_query"],
            "_source_file": "tea_gardens.db (old)",
        }
        result = upsert_garden(conn_new, data)
        if result:
            migrated += 1

    conn_new.commit()
    conn_old.close()
    logger.info(f"Migrated {migrated} gardens from old schema")

    try:
        conn_old = sqlite3.connect(old_path)
        conn_old.row_factory = sqlite3.Row
        old_progress = conn_old.execute("SELECT * FROM scrape_progress").fetchall()
        for row in old_progress:
            pass
        conn_old.close()
    except Exception:
        pass

    return migrated


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    count = migrate_old_to_v2()
    print(f"Migration complete: {count} gardens migrated")
