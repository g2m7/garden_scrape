"""Scraper with Windows encoding workaround."""

import asyncio
import io
import json
import logging
import os
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# Set environment before importing crawl4ai
os.environ["CRAWL4AI_DISABLE_LOGGING"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

# Patch rich to avoid encoding issues
import rich.console
original_print = rich.console.Console.print

def safe_print(self, *args, **kwargs):
    """Safe print that handles encoding errors."""
    try:
        return original_print(self, *args, **kwargs)
    except UnicodeEncodeError:
        # Silently skip unicode errors
        pass

rich.console.Console.print = safe_print

# Now we can import our modules
from scrapers.discovery import AutoDiscoveryScraper
from pipeline import DataPipeline


async def main():
    """Run the scraper."""
    # URLs to try
    urls = [
        "https://en.wikipedia.org/wiki/List_of_tea_gardens_in_Assam",
        "https://www.teaboard.gov.in/",
        "https://www.indiatea.org/",
    ]

    scraper = AutoDiscoveryScraper(headless=True)
    pipeline = DataPipeline(min_workforce=26, max_workforce=49)

    all_gardens = []

    for url in urls:
        print(f"\nTrying: {url}")

        try:
            # Redirect all output to suppress crawl4ai
            null_out = io.StringIO()
            null_err = io.StringIO()

            with redirect_stdout(null_out), redirect_stderr(null_err):
                result = await scraper.scrape_url(url)

            if result.gardens:
                print(f"  Found {len(result.gardens)} gardens")
                all_gardens.extend(result.gardens)

                # Show sample
                for g in result.gardens[:3]:
                    print(f"    - {g.estate_name}: {g.workforce_count} workers")
            else:
                print(f"  No gardens found")

        except Exception as e:
            print(f"  Error: {e}")

    if all_gardens:
        print(f"\nTotal gardens: {len(all_gardens)}")

        # Process
        standardized, errors = pipeline.process(all_gardens)

        Path("output").mkdir(exist_ok=True)
        pipeline.export_to_csv(standardized, "output/tea_gardens.csv")

        print(f"Exported {len(standardized)} gardens to output/tea_gardens.csv")
    else:
        print("\nNo gardens found from any source")


if __name__ == "__main__":
    asyncio.run(main())
