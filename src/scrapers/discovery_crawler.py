"""Aggressive web crawler that discovers tea garden data from multiple sources."""

import asyncio
import io
import json
import logging
import os
import re
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ["CRAWL4AI_DISABLE_LOGGING"] = "1"

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

from models import TeaGarden

logger = logging.getLogger(__name__)


# Potential tea garden data sources
POTENTIAL_SOURCES = [
    # Tea Board
    "https://www.teaboard.gov.in/",
    "https://www.teaboard.gov.in/Garden",
    "https://www.teaboard.gov.in/Statistics",
    # Tea associations
    "https://www.indiatea.org/",
    "https://www.indiatea.org/tea-gardens",
    "https://www.assamtea.org/",
    # Tourism sites
    "https://www.assamtourism.org/",
    "https://www.assamtourism.org/tea-gardens",
    "https://www.incredibleindia.org/",
    # Wikipedia (may have lists)
    "https://en.wikipedia.org/wiki/Tea_gardens_of_Assam",
    "https://en.wikipedia.org/wiki/Tea_industry_in_Assam",
    # Commercial directories
    "https://www.indiamart.com/",
    # Trade portals
    "https://www.teaauction.gov.in/",
]


class TeaGardenDiscoveryCrawler:
    """Crawler that aggressively searches for tea garden data."""

    def __init__(
        self,
        min_workforce: int = 26,
        max_workforce: int = 49,
        max_sources: int = 20,
    ) -> None:
        self.min_workforce = min_workforce
        self.max_workforce = max_workforce
        self.max_sources = max_sources
        self.browser_config = BrowserConfig(
            headless=True,
            verbose=False,
            java_script_enabled=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )

    async def discover_all(self) -> list[TeaGarden]:
        """Crawl all potential sources and extract tea garden data."""
        all_gardens: list[TeaGarden] = []
        results_log = []

        async with AsyncWebCrawler(config=self.browser_config) as crawler:
            for url in POTENTIAL_SOURCES[:self.max_sources]:
                logger.info(f"Trying: {url}")

                try:
                    gardens, info = await self._scrape_source(crawler, url)

                    if gardens:
                        logger.info(f"  ✓ Found {len(gardens)} gardens")
                        all_gardens.extend(gardens)
                        results_log.append({"url": url, "found": len(gardens), "status": "success"})
                    else:
                        logger.info(f"  ✗ No gardens found")
                        results_log.append({"url": url, "found": 0, "status": "no_data"})

                except Exception as e:
                    logger.warning(f"  ✗ Error: {e}")
                    results_log.append({"url": url, "found": 0, "status": str(e)})

        # Save discovery log
        Path("output").mkdir(exist_ok=True)
        with open("output/discovery_log.json", "w") as f:
            json.dump(results_log, f, indent=2)

        return all_gardens

    async def _scrape_source(
        self,
        crawler: AsyncWebCrawler,
        url: str,
    ) -> tuple[list[TeaGarden], dict[str, Any]]:
        """Scrape a single source for tea garden data."""

        null_out = io.StringIO()
        null_err = io.StringIO()

        with redirect_stdout(null_out), redirect_stderr(null_err):
            result = await crawler.arun(url=url)

        info = {
            "url": url,
            "success": result.success if hasattr(result, "success") else False,
            "html_length": len(result.html) if hasattr(result, "html") else 0,
            "has_markdown": bool(result.markdown) if hasattr(result, "markdown") else False,
        }

        if not result.success:
            return [], info

        gardens: list[TeaGarden] = []

        # Try multiple extraction strategies

        # 1. Look for tables in markdown
        if result.markdown:
            gardens.extend(self._extract_from_markdown(result.markdown.raw_markdown, url))

        # 2. Look for structured data patterns
        if result.html:
            gardens.extend(self._extract_from_html(result.html, url))

        # 3. Look for JSON-LD or structured data
        if hasattr(result, "extracted_content") and result.extracted_content:
            gardens.extend(self._extract_from_json(result.extracted_content, url))

        return gardens, info

    def _extract_from_markdown(self, text: str, source: str) -> list[TeaGarden]:
        """Extract tea gardens from markdown text."""
        gardens: list[TeaGarden] = []

        # Pattern: Look for garden names with associated data
        # Common patterns in markdown lists and tables

        lines = text.split('\n')
        current_garden = None

        for line in lines:
            line = line.strip()

            # Skip empty lines and navigation
            if not line or line.startswith('#') or line.startswith('*') or line.startswith('['):
                continue

            # Look for tea garden name patterns
            if self._looks_like_garden_name(line):
                name = self._extract_garden_name(line)
                if name:
                    current_garden = {"name": name, "source": source}

            # Look for phone numbers
            phone_match = re.search(r'(?:Phone|Tel|Contact)?[:\s]*(?:\+91[-\s]?)?(\d{10}|\d{3}[-\s]\d{3}[-\s]\d{4})', line, re.IGNORECASE)
            if phone_match and current_garden:
                current_garden["phone"] = phone_match.group(1)

            # Look for workforce/staff numbers
            workforce_match = re.search(r'(?:Staff|Workers|Employees|Workforce)?[:\s]*(\d{2,3})', line, re.IGNORECASE)
            if workforce_match and current_garden:
                workforce = int(workforce_match.group(1))
                if self.min_workforce <= workforce <= self.max_workforce:
                    current_garden["workforce"] = workforce

            # If we have a complete garden, save it
            if current_garden and "name" in current_garden:
                garden = TeaGarden(
                    estate_name=current_garden["name"],
                    workforce_count=current_garden.get("workforce"),
                    primary_phone=current_garden.get("phone"),
                    contact_person=None,
                    source_origin=source,
                )
                gardens.append(garden)
                current_garden = None

        return gardens

    def _extract_from_html(self, html: str, source: str) -> list[TeaGarden]:
        """Extract tea gardens from HTML content."""
        gardens: list[TeaGarden] = []

        # Look for common patterns in HTML

        # 1. Table rows with garden names
        table_pattern = r'<tr[^>]*>.*?<td[^>]*>(.*?)</td>.*?</tr>'
        for match in re.finditer(table_pattern, html, re.IGNORECASE | re.DOTALL):
            cells = re.findall(r'<td[^>]*>(.*?)</td>', match.group(0), re.IGNORECASE | re.DOTALL)
            if cells and len(cells) >= 2:
                # Check if first cell looks like a garden name
                first_cell = re.sub(r'<[^>]+>', '', cells[0]).strip()
                if self._looks_like_garden_name(first_cell):
                    garden = TeaGarden(
                        estate_name=first_cell,
                        workforce_count=None,
                        primary_phone=None,
                        contact_person=None,
                        source_origin=source,
                    )
                    gardens.append(garden)

        # 2. List items with garden names
        list_pattern = r'<li[^>]*>(.*?)</li>'
        for match in re.finditer(list_pattern, html, re.IGNORECASE | re.DOTALL):
            text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
            if self._looks_like_garden_name(text):
                name = self._extract_garden_name(text)
                if name:
                    garden = TeaGarden(
                        estate_name=name,
                        workforce_count=None,
                        primary_phone=None,
                        contact_person=None,
                        source_origin=source,
                    )
                    gardens.append(garden)

        return gardens

    def _extract_from_json(self, json_str: str, source: str) -> list[TeaGarden]:
        """Extract tea gardens from JSON data."""
        gardens: list[TeaGarden] = []

        try:
            data = json.loads(json_str)
            # Handle list of objects
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        # Look for garden-like fields
                        name = None
                        for key in item:
                            if any(
                                kw in key.lower()
                                for kw in ["name", "garden", "estate", "title"]
                            ):
                                name = str(item[key])
                                break

                        if name and self._looks_like_garden_name(name):
                            garden = TeaGarden(
                                estate_name=name,
                                workforce_count=item.get("staff") or item.get("workers") or item.get("workforce"),
                                primary_phone=item.get("phone") or item.get("contact") or item.get("mobile"),
                                contact_person=item.get("manager") or item.get("owner"),
                                source_origin=source,
                            )
                            gardens.append(garden)
        except (json.JSONDecodeError, TypeError):
            pass

        return gardens

    @staticmethod
    def _looks_like_garden_name(text: str) -> bool:
        """Check if text looks like a tea garden name."""

        if not text or len(text) < 5 or len(text) > 100:
            return False

        text_lower = text.lower()

        # Must contain tea-related keywords
        tea_keywords = ["tea", "garden", "estate", "t.g.", "plantation"]
        if not any(kw in text_lower for kw in tea_keywords):
            return False

        # Skip common non-garden phrases
        skip_phrases = [
            "welcome to", "click here", "read more", "more info",
            "privacy policy", "terms of service", "contact us",
            "home page", "main menu", "search", "login", "register"
        ]
        if any(phrase in text_lower for phrase in skip_phrases):
            return False

        return True

    @staticmethod
    def _extract_garden_name(text: str) -> str | None:
        """Clean and extract garden name from text."""

        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)

        # Remove extra whitespace
        text = ' '.join(text.split())

        # Remove trailing punctuation
        text = text.rstrip('.,;:')

        if len(text) < 5 or len(text) > 100:
            return None

        return text


async def main():
    """Run the discovery crawler."""

    import argparse

    parser = argparse.ArgumentParser(description="Discover tea garden data from web sources")
    parser.add_argument("--max-sources", type=int, default=20, help="Maximum sources to try")
    parser.add_argument("--min-workforce", type=int, default=26, help="Minimum workforce")
    parser.add_argument("--max-workforce", type=int, default=49, help="Maximum workforce")
    parser.add_argument("--output", type=str, default="output/discovered_gardens.csv", help="Output file")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    crawler = TeaGardenDiscoveryCrawler(
        min_workforce=args.min_workforce,
        max_workforce=args.max_workforce,
        max_sources=args.max_sources,
    )

    logger.info("Starting tea garden discovery crawler...")
    logger.info(f"Will try up to {args.max_sources} sources")

    gardens = await crawler.discover_all()

    logger.info(f"\nDiscovery complete! Found {len(gardens)} gardens")

    if gardens:
        # Export results
        from pathlib import Path
        import pandas as pd

        Path(args.output).parent.mkdir(parents=True, exist_ok=True)

        df = pd.DataFrame([g.model_dump() for g in gardens])
        df.to_csv(args.output, index=False)

        logger.info(f"Exported to {args.output}")

        # Show sample
        print("\n" + "=" * 80)
        print("SAMPLE GARDENS FOUND:")
        print("=" * 80)
        for garden in gardens[:10]:
            print(f"  • {garden.estate_name}")
            if garden.workforce_count:
                print(f"    Staff: {garden.workforce_count}")
            if garden.primary_phone:
                print(f"    Phone: {garden.primary_phone}")

        if len(gardens) > 10:
            print(f"\n  ... and {len(gardens) - 10} more")
        print("=" * 80)
    else:
        logger.warning("No gardens found. Check discovery_log.json for details.")


if __name__ == "__main__":
    asyncio.run(main())
