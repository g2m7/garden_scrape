import argparse
import asyncio
import logging
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ["CRAWL4AI_DISABLE_LOGGING"] = "1"

import rich.console
_original = rich.console.Console.print
def _safe(self, *a, **k):
    try:
        return _original(self, *a, **k)
    except UnicodeEncodeError:
        pass
rich.console.Console.print = _safe


def cmd_init(args):
    from db_v2 import init_db
    conn = init_db()
    print("Database initialized at tea_gardens.db")
    conn.close()


def cmd_migrate(args):
    from migrate_db import migrate_old_to_v2
    count = migrate_old_to_v2()
    print(f"Migrated {count} gardens from old schema")


def cmd_process(args):
    from process_sources import process_all_sources
    results = process_all_sources()
    print("\n=== Source Processing Results ===")
    for name, count in results.items():
        print(f"  {name}: {count}")


def cmd_crawl_emails(args):
    from email_crawler import crawl_all_emails
    results = asyncio.run(crawl_all_emails(
        batch_size=args.batch_size,
        min_confidence=args.min_confidence,
        retry_failed=args.retry_failed,
    ))
    print(f"\n=== Email Crawl Complete ===")
    print(f"  Crawled: {results['crawled']}")
    print(f"  Total emails found: {results['emails_found']}")
    print(f"  Gardens with email: {results['gardens_with_email']}")
    print(f"  Errors: {results['errors']}")


def cmd_tui(args):
    from tui.app import main as tui_main
    tui_main()


def cmd_stats(args):
    from db_v2 import init_db, get_stats
    conn = init_db()
    stats = get_stats(conn)
    print("\n=== Database Statistics ===")
    print(f"  Total gardens:     {stats['total']}")
    print(f"  With phone:        {stats['with_phone']}")
    print(f"  Without phone:     {stats['without_phone']}")
    print(f"  With email:        {stats['with_email']}")
    print(f"  Without email:     {stats['without_email']}")
    print(f"  With website:      {stats['with_website']}")
    print(f"  Avg confidence:    {stats['avg_confidence']}")
    print(f"\n  By District:")
    for d, c in stats['by_district'].items():
        print(f"    {d}: {c}")
    print(f"\n  By Source:")
    for s, c in stats['by_source'].items():
        print(f"    {s}: {c}")
    conn.close()


def cmd_export(args):
    from db_v2 import init_db, export_to_xlsx
    conn = init_db()
    filters = {}
    if args.district:
        filters["district"] = args.district
    if args.state:
        filters["state"] = args.state
    if args.has_phone:
        filters["has_phone"] = True
    if args.has_email:
        filters["has_email"] = True

    count = export_to_xlsx(conn, args.output, **filters)
    print(f"Exported {count} records to {args.output}")
    conn.close()


def cmd_run_all(args):
    print("Step 1: Initializing database...")
    cmd_init(args)

    print("\nStep 2: Migrating existing data...")
    cmd_migrate(args)

    print("\nStep 3: Processing all source files...")
    cmd_process(args)

    print("\nStep 4: Crawling for emails...")
    cmd_crawl_emails(args)

    print("\nStep 5: Final statistics...")
    cmd_stats(args)

    print("\nAll done! Run 'python run.py tui' to launch the TUI.")


def main():
    parser = argparse.ArgumentParser(
        description="Tea Garden Data Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  init        Initialize the database
  migrate     Migrate data from old schema
  process     Process all unprocessed source files
  crawl       Crawl the web for tea garden emails
  tui         Launch the interactive TUI
  stats       Show database statistics
  export      Export data to XLSX
  run-all     Run all steps (init, migrate, process, crawl)

Examples:
  python run.py init
  python run.py migrate
  python run.py process
  python run.py crawl --batch-size 20
  python run.py tui
  python run.py stats
  python run.py export --output output/gardens.xlsx --district Dibrugarh
  python run.py run-all
        """,
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Initialize database")

    subparsers.add_parser("migrate", help="Migrate old schema data")

    subparsers.add_parser("process", help="Process all source files")

    crawl_parser = subparsers.add_parser("crawl", help="Crawl for emails")
    crawl_parser.add_argument("--batch-size", type=int, default=50)
    crawl_parser.add_argument("--min-confidence", type=float, default=0.3)
    crawl_parser.add_argument("--retry-failed", action="store_true", help="Retry gardens that had no emails from previous crawls")

    subparsers.add_parser("tui", help="Launch TUI")

    subparsers.add_parser("stats", help="Show statistics")

    export_parser = subparsers.add_parser("export", help="Export to XLSX")
    export_parser.add_argument("--output", default="output/tea_gardens_export.xlsx")
    export_parser.add_argument("--district", default=None)
    export_parser.add_argument("--state", default=None)
    export_parser.add_argument("--has-phone", action="store_true")
    export_parser.add_argument("--has-email", action="store_true")

    subparsers.add_parser("run-all", help="Run all steps")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    commands = {
        "init": cmd_init,
        "migrate": cmd_migrate,
        "process": cmd_process,
        "crawl": cmd_crawl_emails,
        "tui": cmd_tui,
        "stats": cmd_stats,
        "export": cmd_export,
        "run-all": cmd_run_all,
    }

    fn = commands.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
