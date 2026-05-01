"""Run scraper with Wikipedia support."""

import asyncio
import io
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
        pass

rich.console.Console.print = safe_print

# Import our modules
from scrapers.wikipedia import WikipediaScraper
from pipeline import DataPipeline


async def main():
    """Run the scraper with Wikipedia support."""

    url = "https://en.wikipedia.org/wiki/List_of_tea_gardens_in_Assam"

    print(f"Scraping: {url}")

    scraper = WikipediaScraper()

    try:
        result = await scraper.scrape(url)

        if result.gardens:
            print(f"\nFound {len(result.gardens)} gardens:\n")

            for i, garden in enumerate(result.gardens[:20], 1):
                print(f"{i:2d}. {garden.estate_name}")

            if len(result.gardens) > 20:
                print(f"\n... and {len(result.gardens) - 20} more")

            # Note: Wikipedia doesn't have workforce data, so we can't filter
            # Export all found gardens
            Path("output").mkdir(exist_ok=True)

            # Export as raw list
            with open("output/wikipedia_gardens.txt", "w") as f:
                for garden in result.gardens:
                    f.write(f"{garden.estate_name}\n")

            print(f"\nExported {len(result.gardens)} garden names to output/wikipedia_gardens.txt")
            print("\nNote: Wikipedia lists don't include workforce data.")
            print("You'll need to enrich this data with workforce information from other sources.")
        else:
            print("No gardens found")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
