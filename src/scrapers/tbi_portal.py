"""TBI Portal scraper using crawl4ai."""

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CacheMode,
    CrawlerRunConfig,
    JsonCssExtractionStrategy,
)

from models import TeaGarden


@dataclass
class TBIPortalConfig:
    """Configuration for TBI Portal scraping."""

    base_url: str
    estate_selector: str = ".estate-card, .garden-row, tr.garden"
    name_selector: str = ".estate-name, .garden-name, td:nth-child(1)"
    workforce_selector: str = ".workforce, .staff-count, td:nth-child(2)"
    phone_selector: str = ".phone, .contact, td:nth-child(3)"
    pagination_selector: str = ".pagination a.next, .load-more-button"
    headless: bool = True


class TBIPortalScraper:
    """Scraper for TBI Portal using crawl4ai with structured extraction."""

    def __init__(self, config: TBIPortalConfig) -> None:
        self.config = config
        self.browser_config = BrowserConfig(
            headless=config.headless,
            java_script_enabled=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )

    def _build_extraction_schema(self) -> dict[str, Any]:
        """Build CSS extraction schema for tea garden data."""
        return {
            "name": "TeaGardens",
            "baseSelector": self.config.estate_selector,
            "fields": [
                {"name": "estate_name", "selector": self.config.name_selector, "type": "text"},
                {"name": "workforce_count", "selector": self.config.workforce_selector, "type": "text"},
                {"name": "primary_phone", "selector": self.config.phone_selector, "type": "text"},
                {
                    "name": "contact_person",
                    "selector": ".contact-person, .manager, td:nth-child(4)",
                    "type": "text",
                },
            ],
        }

    async def scrape_page(self, url: str) -> list[TeaGarden]:
        """Scrape a single page from TBI Portal."""
        extraction_strategy = JsonCssExtractionStrategy(self._build_extraction_schema())

        crawler_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            extraction_strategy=extraction_strategy,
        )

        async with AsyncWebCrawler(config=self.browser_config) as crawler:
            result = await crawler.arun(url=url, config=crawler_config)

            if not result.success:
                return []

            try:
                extracted = json.loads(result.extracted_content or "[]")
                return self._parse_extracted_data(extracted)
            except json.JSONDecodeError:
                # Fallback: try extracting from tables
                return self._parse_from_tables(result)

    async def scrape_all_pages(self, start_url: str) -> list[TeaGarden]:
        """Scrape all paginated pages from TBI Portal."""
        all_gardens: list[TeaGarden] = []
        current_url = start_url
        page_count = 0

        async with AsyncWebCrawler(config=self.browser_config) as crawler:
            while current_url:
                page_count += 1
                extraction_strategy = JsonCssExtractionStrategy(self._build_extraction_schema())
                crawler_config = CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS,
                    extraction_strategy=extraction_strategy,
                )

                result = await crawler.arun(url=current_url, config=crawler_config)

                if result.success:
                    try:
                        extracted = json.loads(result.extracted_content or "[]")
                        gardens = self._parse_extracted_data(extracted)
                        all_gardens.extend(gardens)
                    except json.JSONDecodeError:
                        gardens = self._parse_from_tables(result)
                        all_gardens.extend(gardens)

                # Find next page link
                current_url = None  # TODO: Implement pagination logic
                if page_count > 10:  # Safety limit
                    break

        return all_gardens

    def _parse_extracted_data(self, extracted: list[dict[str, Any]]) -> list[TeaGarden]:
        """Parse extracted JSON data into TeaGarden models."""
        gardens: list[TeaGarden] = []

        for item in extracted:
            try:
                name = item.get("estate_name", "").strip()
                if not name or name.lower() in ["", "n/a", "-"]:
                    continue

                workforce = self._parse_workforce(item.get("workforce_count", ""))
                if workforce is None:
                    continue

                garden = TeaGarden(
                    estate_name=name,
                    workforce_count=workforce,
                    primary_phone=item.get("primary_phone") or None,
                    contact_person=item.get("contact_person") or None,
                    source_origin="TBI_Portal",
                )
                gardens.append(garden)
            except Exception:
                continue

        return gardens

    def _parse_from_tables(self, result) -> list[TeaGarden]:
        """Parse gardens from HTML tables if JSON extraction fails."""
        gardens: list[TeaGarden] = []

        for table in result.tables or []:
            headers = table.get("headers", [])
            rows = table.get("rows", [])

            # Find column indices
            name_idx = self._find_column_index(headers, ["name", "estate", "garden"])
            workforce_idx = self._find_column_index(headers, ["workforce", "staff", "employees"])
            phone_idx = self._find_column_index(headers, ["phone", "contact", "mobile"])
            contact_idx = self._find_column_index(headers, ["manager", "person", "in-charge"])

            for row in rows:
                try:
                    name = row[name_idx].strip() if name_idx >= 0 and name_idx < len(row) else ""
                    if not name:
                        continue

                    workforce = self._parse_workforce(
                        row[workforce_idx] if workforce_idx >= 0 and workforce_idx < len(row) else ""
                    )
                    if workforce is None:
                        continue

                    garden = TeaGarden(
                        estate_name=name,
                        workforce_count=workforce,
                        primary_phone=row[phone_idx] if phone_idx >= 0 and phone_idx < len(row) else None,
                        contact_person=row[contact_idx] if contact_idx >= 0 and contact_idx < len(row) else None,
                        source_origin="TBI_Portal",
                    )
                    gardens.append(garden)
                except (IndexError, ValueError):
                    continue

        return gardens

    @staticmethod
    def _find_column_index(headers: list[str], keywords: list[str]) -> int:
        """Find column index by keyword matching."""
        headers_lower = [h.lower() for h in headers]
        for i, header in enumerate(headers_lower):
            if any(k in header for k in keywords):
                return i
        return -1

    @staticmethod
    def _parse_workforce(value: str | int | None) -> int | None:
        """Parse workforce from various string formats."""
        if isinstance(value, int):
            return value if value > 0 else None

        if not value or not isinstance(value, str):
            return None

        # Remove common prefixes/suffixes
        cleaned = (
            value.lower()
            .replace("staff", "")
            .replace("workers", "")
            .replace("employees", "")
            .replace("approximately", "")
            .replace("approx", "")
            .replace("~", "")
            .replace("+", "")
            .strip()
        )

        try:
            num = int(cleaned)
            return num if 0 < num < 1000 else None
        except ValueError:
            return None
