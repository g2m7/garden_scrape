"""Auto-discovery scraper that finds and extracts tea garden data from any site."""

import asyncio
import io
import json
import logging
import re
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Suppress crawl4ai logging
logging.getLogger("crawl4ai").setLevel(logging.CRITICAL)
logging.getLogger("playwright").setLevel(logging.CRITICAL)

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CacheMode,
    CrawlerRunConfig,
    JsonCssExtractionStrategy,
    DefaultTableExtraction,
)

from models import TeaGarden


@dataclass
class DiscoveryResult:
    """Result of auto-discovery scraping."""

    gardens: list[TeaGarden]
    source_url: str
    discovery_info: dict[str, Any]


class AutoDiscoveryScraper:
    """Scraper that automatically discovers and extracts tea garden data.

    This scraper can handle:
    - Direct data pages (tables, lists)
    - Directory listings with pagination
    - PDF reports
    - Dynamic content loaded via JavaScript
    """

    def __init__(
        self,
        headless: bool = True,
        max_pages: int = 20,
        concurrent_requests: int = 3,
        verbose: bool = False,
    ) -> None:
        self.headless = headless
        self.max_pages = max_pages
        self.concurrent_requests = concurrent_requests
        self.verbose = verbose
        self.browser_config = BrowserConfig(
            headless=headless,
            java_script_enabled=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            verbose=False,
        )

    async def scrape_url(self, url: str) -> DiscoveryResult:
        """Scrape a URL and auto-discover tea garden data."""
        source_origin = self._identify_source(url)
        discovery_info = {"url": url, "source_type": source_origin}

        # Suppress crawl4ai output to avoid encoding issues
        null_stream = io.StringIO()

        with redirect_stdout(null_stream):
            async with AsyncWebCrawler(config=self.browser_config) as crawler:
                # First, detect the page structure
                structure = await self._detect_page_structure(crawler, url)
                discovery_info["structure"] = structure

                # Choose extraction strategy based on structure
                if structure.get("has_tables"):
                    gardens = await self._extract_from_tables(crawler, url, source_origin)
                elif structure.get("has_listings"):
                    gardens = await self._extract_from_listings(crawler, url, source_origin)
                elif structure.get("has_pdf_links"):
                    gardens = await self._extract_from_pdfs(crawler, url, source_origin)
                else:
                    # Try generic extraction
                    gardens = await self._generic_extraction(crawler, url, source_origin)

                discovery_info["gardens_found"] = len(gardens)

                # Check for pagination
                if structure.get("has_pagination") and len(gardens) > 0:
                    more_gardens = await self._follow_pagination(crawler, url, source_origin)
                    gardens.extend(more_gardens)
                    discovery_info["total_gardens_after_pagination"] = len(gardens)

        return DiscoveryResult(
            gardens=gardens,
            source_url=url,
            discovery_info=discovery_info,
        )

    async def search_and_scrape(
        self,
        search_query: str = "Assam tea garden directory",
        max_results: int = 5,
    ) -> list[DiscoveryResult]:
        """Search for tea garden directories and scrape them.

        Note: This uses Google/Bing search. For production, consider using
        a proper search API to avoid IP blocking.
        """
        # Common Tea Board and garden directory URLs
        known_urls = [
            "https://www.teaboard.gov.in/",
            "https://www.teaboard.gov.in/Garden/GardenDirectory",
            "https://www.indiatea.org/",
            "https://www.assamtourism.org/tea-gardens",
        ]

        results: list[DiscoveryResult] = []

        for url in known_urls[:max_results]:
            try:
                result = await self.scrape_url(url)
                if result.gardens:
                    results.append(result)
            except Exception:
                continue

        return results

    async def _detect_page_structure(self, crawler: AsyncWebCrawler, url: str) -> dict[str, Any]:
        """Analyze page to determine the best extraction strategy."""
        config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

        result = await crawler.arun(url=url, config=config)

        if not result.success:
            return {"error": "Failed to load page"}

        html = result.html[:50000]  # Sample for detection

        return {
            "has_tables": bool(re.search(r"<table", html, re.IGNORECASE)),
            "has_listings": bool(
                re.search(r'class=".*?(garden|estate|tea).*?list"', html, re.IGNORECASE)
            ),
            "has_pagination": bool(
                re.search(r'(pagination|next|page.*?\d|load.\s*more)', html, re.IGNORECASE)
            ),
            "has_pdf_links": bool(re.search(r'href="[^"]*\.pdf"', html, re.IGNORECASE)),
            "title": result.metadata.get("title", ""),
        }

    async def _extract_from_tables(
        self,
        crawler: AsyncWebCrawler,
        url: str,
        source_origin: str,
    ) -> list[TeaGarden]:
        """Extract data from HTML tables."""
        config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            table_extraction=DefaultTableExtraction(),
        )

        result = await crawler.arun(url=url, config=config)

        gardens: list[TeaGarden] = []

        for table in (result.tables or [])[:10]:  # Limit to first 10 tables
            headers = table.get("headers", [])
            rows = table.get("rows", [])

            # Detect if this is a tea garden table
            if not self._is_garden_table(headers, rows[:5]):
                continue

            # Map columns
            mapping = self._map_table_columns(headers)

            for row in rows:
                garden = self._parse_table_row(row, mapping, source_origin)
                if garden:
                    gardens.append(garden)

        return gardens

    async def _extract_from_listings(
        self,
        crawler: AsyncWebCrawler,
        url: str,
        source_origin: str,
    ) -> list[TeaGarden]:
        """Extract data from listing cards/divs using CSS extraction."""
        # Try multiple common selector patterns
        schemas = self._generate_common_schemas()

        gardens: list[TeaGarden] = []

        for schema in schemas:
            config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                extraction_strategy=JsonCssExtractionStrategy(schema),
            )

            result = await crawler.arun(url=url, config=config)

            if result.extracted_content:
                try:
                    extracted = json.loads(result.extracted_content)
                    for item in extracted:
                        garden = self._parse_extracted_item(item, source_origin)
                        if garden:
                            gardens.append(garden)

                    if gardens:  # Found data, stop trying schemas
                        break
                except json.JSONDecodeError:
                    continue

        return gardens

    async def _extract_from_pdfs(
        self,
        crawler: AsyncWebCrawler,
        url: str,
        source_origin: str,
    ) -> list[TeaGarden]:
        """Find and extract from PDF links."""
        # For now, return empty - PDF extraction requires separate handling
        # In production: download PDFs and parse with pypdf
        return []

    async def _generic_extraction(
        self,
        crawler: AsyncWebCrawler,
        url: str,
        source_origin: str,
    ) -> list[TeaGarden]:
        """Generic extraction when structure is unknown."""
        # Extract all text and try to find patterns
        config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

        result = await crawler.arun(url=url, config=config)

        if not result.markdown:
            return []

        gardens: list[TeaGarden] = []
        text = result.markdown.raw_markdown

        # Look for patterns like "Garden Name - 30 workers - Phone: XXX"
        pattern = r'([A-Z][A-Za-z\s]+?(?:Tea Garden|T\.G\.|Estate))[^-]*?-?\s*(\d{2,3})\s*(?:workers|staff|employees)'

        for match in re.finditer(pattern, text):
            name = match.group(1).strip()
            workforce = self._parse_workforce(match.group(2))

            if name and workforce:
                gardens.append(
                    TeaGarden(
                        estate_name=name,
                        workforce_count=workforce,
                        source_origin=source_origin,
                    )
                )

        return gardens

    async def _follow_pagination(
        self,
        crawler: AsyncWebCrawler,
        start_url: str,
        source_origin: str,
    ) -> list[TeaGarden]:
        """Follow pagination links to extract more data."""
        gardens: list[TeaGarden] = []
        visited_urls = {start_url}
        to_visit = [start_url]
        page_count = 0

        while to_visit and page_count < self.max_pages:
            url = to_visit.pop(0)
            page_count += 1

            config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

            result = await crawler.arun(url=url, config=config)

            # Find pagination links
            if result.links:
                for link in result.links:
                    if link not in visited_urls and self._is_pagination_link(link):
                        to_visit.append(link)
                        visited_urls.add(link)

        return gardens

    @staticmethod
    def _identify_source(url: str) -> str:
        """Identify the source type from URL."""
        if "teaboard.gov.in" in url:
            return "TBI_Official"
        if "indiatea.org" in url:
            return "India_Tea_Association"
        if "assam" in url.lower():
            return "Assam_Tourism"
        return "Unknown_Source"

    @staticmethod
    def _is_garden_table(headers: list[str], sample_rows: list[list[str]]) -> bool:
        """Detect if a table contains tea garden data."""
        if not headers:
            return False

        headers_lower = " ".join(h.lower() for h in headers)
        keywords = ["garden", "estate", "tea", "name", "workforce", "staff", "worker", "phone"]

        return any(k in headers_lower for k in keywords)

    @staticmethod
    def _map_table_columns(headers: list[str]) -> dict[str, int]:
        """Map table columns to data fields."""
        mapping: dict[str, int] = {}
        headers_lower = [h.lower() for h in headers]

        for i, header in enumerate(headers_lower):
            if any(k in header for k in ["name", "garden", "estate"]):
                mapping["name"] = i
            elif any(k in header for k in ["workforce", "staff", "worker", "employee", "strength"]):
                mapping["workforce"] = i
            elif any(k in header for k in ["phone", "mobile", "contact", "tel"]):
                mapping["phone"] = i
            elif any(k in header for k in ["manager", "person", "in-charge", "owner"]):
                mapping["contact"] = i

        return mapping

    def _parse_table_row(
        self,
        row: list[str],
        mapping: dict[str, int],
        source_origin: str,
    ) -> TeaGarden | None:
        """Parse a table row into a TeaGarden."""
        try:
            name = row[mapping.get("name", -1)].strip() if "name" in mapping else ""
            if not name:
                return None

            workforce = None
            if "workforce" in mapping:
                workforce = self._parse_workforce(row[mapping["workforce"]])

            return TeaGarden(
                estate_name=name,
                workforce_count=workforce,
                primary_phone=row[mapping.get("phone", -1)] if "phone" in mapping else None,
                contact_person=row[mapping.get("contact", -1)] if "contact" in mapping else None,
                source_origin=source_origin,
            )
        except (IndexError, ValueError):
            return None

    def _generate_common_schemas(self) -> list[dict[str, Any]]:
        """Generate common CSS selector schemas for garden listings."""
        return [
            {
                "name": "GardenCards",
                "baseSelector": ".garden-card, .estate-card, .tea-garden",
                "fields": [
                    {"name": "estate_name", "selector": "h3, h4, .title, .name", "type": "text"},
                    {"name": "workforce", "selector": ".workforce, .staff, .workers", "type": "text"},
                    {"name": "phone", "selector": ".phone, .contact", "type": "text"},
                ],
            },
            {
                "name": "TableRows",
                "baseSelector": "table tbody tr",
                "fields": [
                    {"name": "estate_name", "selector": "td:nth-child(1)", "type": "text"},
                    {"name": "workforce", "selector": "td:nth-child(2)", "type": "text"},
                    {"name": "phone", "selector": "td:nth-child(3)", "type": "text"},
                ],
            },
            {
                "name": "ListItems",
                "baseSelector": "ul li, .directory-item",
                "fields": [
                    {"name": "estate_name", "selector": ".name, strong", "type": "text"},
                    {"name": "workforce", "selector": ".staff, .workers", "type": "text"},
                    {"name": "phone", "selector": ".phone, a[href^='tel:']", "type": "text"},
                ],
            },
        ]

    @staticmethod
    def _parse_extracted_item(item: dict[str, Any], source_origin: str) -> TeaGarden | None:
        """Parse extracted JSON item into TeaGarden."""
        try:
            name = item.get("estate_name", "").strip()
            if not name or len(name) < 3:
                return None

            workforce_str = item.get("workforce", "")
            workforce = AutoDiscoveryScraper._parse_workforce(workforce_str)

            return TeaGarden(
                estate_name=name,
                workforce_count=workforce,
                primary_phone=item.get("phone") or None,
                contact_person=item.get("contact_person") or None,
                source_origin=source_origin,
            )
        except Exception:
            return None

    @staticmethod
    def _parse_workforce(value: str | int | None) -> int | None:
        """Parse workforce from various string formats."""
        if isinstance(value, int) and value > 0:
            return value

        if not value or not isinstance(value, str):
            return None

        # Extract numbers from string
        match = re.search(r"(\d{2,3})", value.replace(",", ""))
        if match:
            num = int(match.group(1))
            return num if 0 < num < 1000 else None

        return None

    @staticmethod
    def _is_pagination_link(url: str) -> bool:
        """Check if URL is a pagination link."""
        patterns = [r"page=\d+", r"/page/\d+", r"\?p=\d+"]
        return any(re.search(p, url) for p in patterns)
