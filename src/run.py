"""Simple runner that handles encoding issues."""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Suppress crawl4ai output
logging.getLogger("crawl4ai").setLevel(logging.ERROR)

# Fix encoding for Windows
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "scrapers"))

from scrapers.discovery import AutoDiscoveryScraper
from pipeline import DataPipeline


async def main():
    """Run scraper with minimal output."""
    # Use Wikipedia as a test - it has structured data
    test_url = "https://en.wikipedia.org/wiki/List_of_tea_gardens_in_Assam"

    scraper = AutoDiscoveryScraper(headless=True, verbose=False)
    pipeline = DataPipeline(min_workforce=26, max_workforce=49)

    print(f"Scraping: {test_url}")

    try:
        result = await scraper.scrape_url(test_url)

        if result.gardens:
            print(f"Found {len(result.gardens)} gardens")

            # Process and export
            standardized, errors = pipeline.process(result.gardens)

            Path("output").mkdir(exist_ok=True)
            pipeline.export_to_csv(standardized, "output/tea_gardens.csv")

            print(f"Exported {len(standardized)} gardens to output/tea_gardens.csv")

            # Show sample
            for garden in standardized[:3]:
                print(f"  - {garden.estate_name}: {garden.workforce_count} workers")
        else:
            print("No gardens found")
            print(f"Discovery info: {json.dumps(result.discovery_info, indent=2)}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
