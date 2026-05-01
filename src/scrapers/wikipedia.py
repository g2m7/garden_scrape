"""Wikipedia-specific scraper for tea garden lists."""

import io
import os
import re
import sys
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set environment before importing crawl4ai
os.environ["CRAWL4AI_DISABLE_LOGGING"] = "1"

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

from models import TeaGarden


@dataclass
class WikiResult:
    """Result from Wikipedia scraping."""

    gardens: list[TeaGarden]
    source_url: str


class WikipediaScraper:
    """Scraper for Wikipedia tea garden lists."""

    async def scrape(self, url: str) -> WikiResult:
        """Scrape Wikipedia page for tea garden list."""

        config = BrowserConfig(headless=True, verbose=False)

        async with AsyncWebCrawler(config=config) as crawler:
            # Suppress crawl4ai output
            null_out = io.StringIO()
            null_err = io.StringIO()

            with redirect_stdout(null_out), redirect_stderr(null_err):
                result = await crawler.arun(url=url)

            gardens: list[TeaGarden] = []

            if result.markdown:
                text = result.markdown.raw_markdown
                gardens = self._parse_wikipedia_list(text)

        return WikiResult(gardens=gardens, source_url=url)

    def _parse_wikipedia_list(self, text: str) -> list[TeaGarden]:
        """Parse tea gardens from Wikipedia list format.

        Wikipedia lists look like:
        1. Garden Name
        2. Another Garden
        """
        gardens: list[TeaGarden] = []

        lines = text.split('\n')

        # Look for list items and headings with tea garden names
        for line in lines:
            line = line.strip()

            # Skip empty lines and navigation
            if not line or line.startswith('#') or line.startswith('['):
                continue

            # Look for lines that look like garden names
            # Common patterns:
            # - "Garden Name" (standalone line)
            # - "1. Garden Name"
            # - "* Garden Name"
            # - "### Garden Name"

            # Match lines that start with list markers or are all caps/title case
            if self._looks_like_garden_name(line):
                # Clean up the name
                name = self._clean_garden_name(line)

                if name and len(name) > 3:
                    gardens.append(
                        TeaGarden(
                            estate_name=name,
                            workforce_count=None,  # Wikipedia lists don't have workforce
                            source_origin="Wikipedia",
                        )
                    )

        return gardens

    @staticmethod
    def _looks_like_garden_name(line: str) -> bool:
        """Check if a line looks like a tea garden name."""

        # Remove common markdown/wiki markers
        clean = re.sub(r'^[\d\*\#\-\s]+', '', line).strip()
        clean = re.sub(r'\[.*?\]', '', clean)  # Remove wiki links

        # Must contain garden-related keywords
        garden_keywords = ['tea', 'garden', 'estate', 't.g.', 'tea estate']
        has_keyword = any(kw in clean.lower() for kw in garden_keywords)

        # Should be reasonable length
        if not (10 < len(clean) < 100):
            return False

        # Should start with capital letter (proper noun)
        if not clean[0].isupper():
            return False

        return has_keyword

    @staticmethod
    def _clean_garden_name(line: str) -> str | None:
        """Clean up a garden name line."""

        # Remove list markers
        name = re.sub(r'^[\d\*\#\-\s]+', '', line).strip()

        # Remove wiki links: [[text|label]] or [[text]]
        name = re.sub(r'\[\[(?:[^\|\]]+\|)?([^\]]+)\]\]', r'\1', name)
        name = re.sub(r'\[([^\]]+)\]', r'\1', name)

        # Remove citations: [1], [2], etc.
        name = re.sub(r'\[\d+\]', '', name)

        # Remove trailing notes in parentheses if they're not part of the name
        name = re.sub(r'\s*\([^)]*\)$', '', name).strip()

        return name if name else None
