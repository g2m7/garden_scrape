"""
Google Maps scraper — browser-based, zero API cost.

Uses Selenium to search Google Maps pincode-by-pincode, scroll through results,
visit each place detail page, and extract name/phone/address/coords.

Anti-detection measures:
  - Removes navigator.webdriver flag
  - Random human-like delays between every action
  - Varies search phrasing
  - Scrolls in small random increments
  - Long breaks between pincodes and between batches
  - Detects CAPTCHA / "unusual traffic" and pauses
  - Resume-safe: every garden saved immediately to DB
"""

import logging
import random
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Sequence

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)

try:
    from db import garden_exists_by_cid, upsert_garden, mark_pincode, log as db_log, _extract_cid
except ImportError:
    from src.db import garden_exists_by_cid, upsert_garden, mark_pincode, log as db_log, _extract_cid

logger = logging.getLogger(__name__)


# ── Config ───────────────────────────────────────────────────────

@dataclass
class ScraperConfig:
    headless: bool = True
    # Timing (seconds) — generous to avoid detection
    delay_after_page: tuple[float, float] = (3.0, 6.0)
    delay_between_details: tuple[float, float] = (3.0, 6.0)
    delay_between_searches: tuple[float, float] = (8.0, 15.0)
    delay_between_pincodes: tuple[float, float] = (20.0, 40.0)
    delay_batch_break: tuple[float, float] = (60.0, 120.0)
    results_per_batch: int = 5        # detail visits before a long break
    max_results_per_search: int = 40  # don't chase infinite scroll forever
    max_scroll_attempts: int = 30
    # Search queries to rotate per pincode
    search_queries: tuple[str, ...] = (
        "tea garden {pincode} Assam",
        "tea estate {pincode} Assam",
    )
    # If a search returns 0 results for N consecutive pincodes, we might be blocked
    block_detection_threshold: int = 10


# ── Scraper ──────────────────────────────────────────────────────

class GoogleMapsScraper:
    """Pincode-wise Google Maps tea garden scraper."""

    def __init__(self, config: ScraperConfig | None = None):
        self.cfg = config or ScraperConfig()
        self.driver: webdriver.Chrome | None = None
        self._gardens_this_session = 0
        self._zero_streak = 0  # consecutive 0-result searches

    # ── Browser lifecycle ────────────────────────────────────────

    def start(self) -> None:
        opts = ChromeOptions()
        if self.cfg.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--lang=en-US")
        opts.add_argument("--disable-notifications")
        opts.add_argument("--start-maximized")
        opts.add_argument("--disable-infobars")
        opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        opts.add_experimental_option("useAutomationExtension", False)

        service = ChromeService()
        self.driver = webdriver.Chrome(service=service, options=opts)

        # Hide webdriver flag
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": STEALTH_JS},
        )
        logger.info("Browser started (headless=%s)", self.cfg.headless)

    def stop(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            logger.info("Browser closed")

    # ── Main scraping loop ───────────────────────────────────────

    def scrape_pincode(
        self,
        pincode: str,
        district: str,
        town: str,
        conn,
    ) -> int:
        """
        Scrape one pincode.  Returns count of NEW gardens saved.
        """
        assert self.driver, "Call start() first"
        total_new = 0
        t0 = time.time()

        db_log(conn, "INFO", f"Starting pincode {pincode} ({town}, {district})", pincode)

        for query_template in self.cfg.search_queries:
            query = query_template.format(pincode=pincode)
            url = f"https://www.google.com/maps/search/{urllib.parse.quote(query)}"

            logger.info("  Searching: %s", query)
            try:
                self.driver.get(url)
            except WebDriverException as e:
                logger.error("  Navigation failed: %s", e)
                db_log(conn, "ERROR", f"Navigation failed: {e}", pincode)
                continue

            self._random_delay(*self.cfg.delay_after_page)

            # Dismiss popups / consent
            self._dismiss_popups()

            # Check for block / CAPTCHA
            if self._is_blocked():
                logger.warning("  ⚠ BLOCKED by Google! Pausing for 5 minutes…")
                db_log(conn, "WARN", "Blocked by Google – long pause", pincode)
                time.sleep(300)  # 5 min cooldown
                self.driver.get(url)
                self._random_delay(5, 8)
                if self._is_blocked():
                    logger.error("  Still blocked after cooldown. Stopping.")
                    mark_pincode(conn, pincode, district, town, "blocked",
                                 error="Google block/CAPTCHA")
                    return total_new

            # Check for no results
            if self._is_no_results():
                logger.info("  No results for '%s'", query)
                self._zero_streak += 1
                self._random_delay(*self.cfg.delay_between_searches)
                continue

            self._zero_streak = 0

            # Scroll to load all results
            self._scroll_results()

            # Collect result URLs
            urls = self._collect_place_urls()
            logger.info("  Found %d result URLs for '%s'", len(urls), query)

            if not urls:
                self._random_delay(*self.cfg.delay_between_searches)
                continue

            # Visit each result detail page
            for i, place_url in enumerate(urls):
                # Check if already scraped (by CID)
                cid = _extract_cid(place_url)
                if cid and garden_exists_by_cid(conn, cid):
                    logger.debug("  Skipping (already in DB): %s", cid)
                    continue

                try:
                    garden = self._extract_place_details(place_url, query)
                except Exception as e:
                    logger.warning("  Detail extraction failed: %s", e)
                    db_log(conn, "WARN", f"Detail extraction failed: {e}", pincode)
                    continue

                if not garden or not garden.get("name"):
                    continue

                # Enrich with meta
                garden["pincode"] = pincode
                garden["district"] = district
                garden["town"] = town
                garden["search_query"] = query

                row_id = upsert_garden(conn, garden)
                if row_id:
                    total_new += 1
                    self._gardens_this_session += 1

                    phone_icon = "📞" if garden.get("phone") else "❌"
                    logger.info(
                        "    %s %s %s",
                        phone_icon,
                        garden["name"][:50],
                        f"({garden.get('phone', 'no phone')})" if garden.get("phone") else "",
                    )

                # Batch break
                if self._gardens_this_session % self.cfg.results_per_batch == 0:
                    logger.info("  Batch break (%d gardens this session)…", self._gardens_this_session)
                    self._random_delay(*self.cfg.delay_batch_break)

                self._random_delay(*self.cfg.delay_between_details)

            self._random_delay(*self.cfg.delay_between_searches)

        # Done with this pincode
        duration = time.time() - t0
        status = "completed" if total_new > 0 else "empty"
        mark_pincode(conn, pincode, district, town, status,
                     gardens_found=total_new, duration_secs=duration)
        db_log(conn, "INFO",
               f"Pincode {pincode} done: {total_new} gardens, {duration:.0f}s",
               pincode)

        self._random_delay(*self.cfg.delay_between_pincodes)
        return total_new

    # ── Google Maps interaction helpers ──────────────────────────

    def _scroll_results(self) -> None:
        """Scroll the results panel to load all results."""
        assert self.driver
        for attempt in range(self.cfg.max_scroll_attempts):
            try:
                # Use JS to find and scroll the feed
                scrolled = self.driver.execute_script(SCROLL_JS)
                if not scrolled:
                    break
                # Human-like: random small scroll jitter
                self._random_delay(1.0, 2.5)
            except Exception:
                break

    def _collect_place_urls(self) -> list[str]:
        """Extract all unique place URLs from the current search results page."""
        assert self.driver
        try:
            urls = self.driver.execute_script(COLLECT_URLS_JS)
            if urls:
                # Deduplicate preserving order
                seen = set()
                unique = []
                for u in urls:
                    if u not in seen:
                        seen.add(u)
                        unique.append(u)
                return unique
        except Exception as e:
            logger.warning("Failed to collect URLs via JS: %s", e)

        # Fallback: Selenium selectors
        return self._collect_urls_fallback()

    def _collect_urls_fallback(self) -> list[str]:
        """Fallback URL collection using Selenium selectors."""
        assert self.driver
        urls = []
        try:
            links = self.driver.find_elements(
                By.CSS_SELECTOR, 'a[href*="/maps/place/"]'
            )
            for link in links:
                try:
                    href = link.get_attribute("href")
                    if href and "/maps/place/" in href and href not in urls:
                        urls.append(href)
                except StaleElementReferenceException:
                    continue
        except Exception as e:
            logger.warning("Fallback URL collection failed: %s", e)
        return urls

    def _extract_place_details(self, url: str, search_query: str) -> dict | None:
        """
        Navigate to a place detail URL and extract all info.
        Returns dict with garden data or None.
        """
        assert self.driver

        try:
            self.driver.get(url)
        except WebDriverException:
            return None

        self._random_delay(2.0, 4.0)

        # Try JS extraction first (most reliable)
        try:
            data = self.driver.execute_script(EXTRACT_DETAILS_JS)
            if data and data.get("name"):
                # Extract coords from URL
                lat, lng = self._coords_from_url(self.driver.current_url)
                data["latitude"] = lat
                data["longitude"] = lng
                data["google_url"] = self.driver.current_url
                return data
        except Exception as e:
            logger.debug("JS extraction failed: %s", e)

        # Fallback: Selenium-based extraction
        return self._extract_details_fallback(url)

    def _extract_details_fallback(self, url: str) -> dict | None:
        """Fallback detail extraction using Selenium selectors."""
        assert self.driver

        data: dict = {"google_url": url}

        # Name — try h1 first, then large text
        try:
            h1 = self.driver.find_element(By.TAG_NAME, "h1")
            data["name"] = h1.text.strip()
        except NoSuchElementException:
            pass

        if not data.get("name"):
            return None

        # Phone — search page text for Indian phone patterns
        try:
            body_text = self.driver.find_element(By.TAG_NAME, "body").text
            phone_match = re.search(
                r"(\+91[-.\s]?\d{2,4}[-.\s]?\d{3,4}[-.\s]?\d{3,4}|"
                r"\d{3,4}[-.\s]\d{6,7})",
                body_text,
            )
            if phone_match:
                data["phone"] = phone_match.group(0).strip()
        except Exception:
            pass

        # Coords from URL
        lat, lng = self._coords_from_url(self.driver.current_url)
        data["latitude"] = lat
        data["longitude"] = lng

        # Rating
        try:
            rating_el = self.driver.find_element(By.CSS_SELECTOR, "span[role='img']")
            aria = rating_el.get_attribute("aria-label") or ""
            m = re.search(r"(\d+\.?\d*)", aria)
            if m:
                data["rating"] = m.group(1)
        except NoSuchElementException:
            pass

        # Category
        try:
            # The category is usually the button text after the rating
            buttons = self.driver.find_elements(By.CSS_SELECTOR, "button[jsaction]")
            for btn in buttons:
                txt = btn.text.strip()
                if any(k in txt.lower() for k in ["tea", "garden", "estate", "plantation", "farm"]):
                    data["category"] = txt
                    break
        except Exception:
            pass

        # Area — extract from page text
        try:
            body_text = self.driver.find_element(By.TAG_NAME, "body").text
            area_ha = self._parse_area_from_text(body_text)
            if area_ha is not None:
                data["area_hectares"] = area_ha
                data["area_source"] = "extracted_text"
        except Exception:
            pass

        return data

    # ── Page state checks ────────────────────────────────────────

    def _is_blocked(self) -> bool:
        """Check if Google is showing a CAPTCHA or unusual traffic message."""
        assert self.driver
        try:
            body = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            blocked_phrases = [
                "unusual traffic",
                "captcha",
                "verify you are human",
                "our systems have detected",
                "sorry, we couldn't",
                "try again later",
            ]
            return any(p in body for p in blocked_phrases)
        except Exception:
            return False

    def _is_no_results(self) -> bool:
        """Check if the search returned no results."""
        assert self.driver
        try:
            body = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            no_result_phrases = [
                "no results found",
                "cannot find",
                "try a different search",
                "did not match any",
            ]
            return any(p in body for p in no_result_phrases)
        except Exception:
            return False

    def _dismiss_popups(self) -> None:
        """Dismiss common Google Maps popups (consent, sign-in, etc.)."""
        assert self.driver
        for selector in [
            "button[aria-label*='Accept']",
            "button[aria-label*='accept']",
            "button[aria-label*='Agree']",
            "button[aria-label*='Got it']",
            "button[aria-label*='Dismiss']",
            "form:nth-of-type(1) button",
        ]:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                if btn.is_displayed():
                    btn.click()
                    self._random_delay(0.5, 1.0)
                    return
            except (NoSuchElementException, StaleElementReferenceException):
                continue
            except Exception:
                continue

    # ── Utilities ────────────────────────────────────────────────

    def _random_delay(self, lo: float, hi: float) -> None:
        time.sleep(random.uniform(lo, hi))

    @staticmethod
    def _coords_from_url(url: str) -> tuple[float | None, float | None]:
        """Extract lat,lng from a Google Maps URL."""
        # Try @lat,lng pattern
        m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
        if m:
            return float(m.group(1)), float(m.group(2))
        # Try !3dLAT!4dLNG pattern
        m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url)
        if m:
            return float(m.group(1)), float(m.group(2))
        return None, None

    @staticmethod
    def _parse_area_from_text(text: str) -> float | None:
        """Parse area in hectares from page text. Returns hectares or None."""
        # Hectares
        m = re.search(r"([\d,.]+)\\s*hectare", text, re.IGNORECASE)
        if m:
            return round(float(m.group(1).replace(",", "")), 2)
        # Acres → hectares (1 acre = 0.404686 ha)
        m = re.search(r"([\d,.]+)\\s*acre", text, re.IGNORECASE)
        if m:
            return round(float(m.group(1).replace(",", "")) * 0.404686, 2)
        # km² → hectares (1 km² = 100 ha)
        m = re.search(r"([\d,.]+)\\s*(?:km²|sq\\s*km|square\\s*km)", text, re.IGNORECASE)
        if m:
            return round(float(m.group(1).replace(",", "")) * 100, 2)
        # Bigha (Assam) → hectares (1 bigha ≈ 0.1338 ha)
        m = re.search(r"([\d,.]+)\\s*bigha", text, re.IGNORECASE)
        if m:
            return round(float(m.group(1).replace(",", "")) * 0.1338, 2)
        return None


# ── Injected JavaScript snippets ─────────────────────────────────

STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    window.navigator.chrome = { runtime: {} };
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5]
    });
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en']
    });
"""

SCROLL_JS = """
    // Find the scrollable results feed
    const feed = document.querySelector('div[role="feed"]')
              || document.querySelector('#pane div[style*="overflow"]')
              || document.querySelector('div.m6QErb.XiKgde');
    if (!feed) return false;

    const prevHeight = feed.scrollHeight;
    feed.scrollTop = feed.scrollHeight;
    return feed.scrollHeight > prevHeight;
"""

COLLECT_URLS_JS = """
    // Try to scope to the results panel first
    let container = document.querySelector('div[role="feed"]');
    if (!container) container = document.getElementById('pane');
    if (!container) container = document.body;

    const links = container.querySelectorAll('a[href*="/maps/place/"]');
    const seen = new Set();
    const urls = [];

    for (const a of links) {
        const href = a.href;
        if (!href || seen.has(href)) continue;
        // Skip navigation / header links
        if (href.includes('/maps/dir/') || href.includes('/maps/contrib/')) continue;
        seen.add(href);
        urls.push(href);
    }
    return urls;
"""

EXTRACT_DETAILS_JS = """
    const data = {};

    // ── Name ──
    const h1 = document.querySelector('h1');
    if (h1) data.name = h1.textContent.trim();

    // ── Phone ──
    // Strategy 1: look for tel: links
    const telLink = document.querySelector('a[href^="tel:"]');
    if (telLink) {
        data.phone = telLink.getAttribute('href').replace('tel:', '').trim();
    }

    // Strategy 2: search visible text for Indian phone patterns
    if (!data.phone) {
        const body = document.body.innerText;
        const phoneRe = /(\\+91[-.\\s]?|0)?(37[0-9][-.\\s]?\\d{6,7}|[6-9]\\d{4}[-.\\s]?\\d{5}|\\d{3,4}[-.\\s]\\d{3,4}[-.\\s]\\d{3,4})/g;
        const match = phoneRe.exec(body);
        if (match) data.phone = match[0].trim();
    }

    // Strategy 3: buttons with phone aria-labels
    if (!data.phone) {
        const buttons = document.querySelectorAll('button[aria-label*="Phone"], button[aria-label*="phone"]');
        for (const btn of buttons) {
            const label = btn.getAttribute('aria-label');
            const m = label.match(/\\+?[\\d\\s\\-.]{8,}/);
            if (m) { data.phone = m[0].trim(); break; }
        }
    }

    // ── Address ──
    const addrButton = document.querySelector('button[aria-label*="Address"], button[aria-label*="address"]');
    if (addrButton) {
        data.address = addrButton.getAttribute('aria-label').replace(/^Address:?\\s*/i, '').trim();
    }
    if (!data.address) {
        const allButtons = document.querySelectorAll('button');
        for (const btn of allButtons) {
            const label = btn.getAttribute('aria-label') || '';
            if (label.includes('Copy') && label.includes('address')) {
                const m = label.match(/Copy (.+)/);
                if (m) { data.address = m[1].trim(); break; }
            }
        }
    }

    // ── Area in hectares ──
    // Google Maps sometimes shows area in the details panel.
    // Look for patterns like "250 hectares", "800 acres", "5.2 km²", etc.
    const pageText = document.body.innerText;

    // Try hectares first (most direct)
    const haMatch = pageText.match(/([\\d,.]+)\\s*hectare/i);
    if (haMatch) {
        data.area_hectares = parseFloat(haMatch[1].replace(/,/g, ''));
        data.area_source = 'google_maps';
    }

    // Try acres (1 acre = 0.404686 hectares)
    if (!data.area_hectares) {
        const acreMatch = pageText.match(/([\\d,.]+)\\s*acre/i);
        if (acreMatch) {
            data.area_hectares = Math.round(parseFloat(acreMatch[1].replace(/,/g, '')) * 0.404686 * 100) / 100;
            data.area_source = 'google_maps';
        }
    }

    // Try km² (1 km² = 100 hectares)
    if (!data.area_hectares) {
        const kmMatch = pageText.match(/([\\d,.]+)\\s*(?:km²|sq\\s*km|square\\s*km)/i);
        if (kmMatch) {
            data.area_hectares = Math.round(parseFloat(kmMatch[1].replace(/,/g, '')) * 100 * 100) / 100;
            data.area_source = 'google_maps';
        }
    }

    // Try bigha (1 bigha in Assam ≈ 0.1338 hectares / 14,400 sq ft)
    if (!data.area_hectares) {
        const bighaMatch = pageText.match(/([\\d,.]+)\\s*bigha/i);
        if (bighaMatch) {
            data.area_hectares = Math.round(parseFloat(bighaMatch[1].replace(/,/g, '')) * 0.1338 * 100) / 100;
            data.area_source = 'extracted_text';
        }
    }

    // ── Rating ──
    const ratingEl = document.querySelector('span[role="img"][aria-label*="star"]');
    if (ratingEl) {
        const m = ratingEl.getAttribute('aria-label').match(/(\\d+\\.?\\d*)/);
        if (m) data.rating = m[1];
        const reviewM = ratingEl.getAttribute('aria-label').match(/(\\d[\\d,]*)\\s*review/i);
        if (reviewM) data.reviews_count = parseInt(reviewM[1].replace(/,/g, ''));
    }

    // ── Category ──
    const catBtn = document.querySelector('button[jsaction*="category"]');
    if (catBtn) {
        data.category = catBtn.textContent.trim();
    }
    if (!data.category) {
        const spans = document.querySelectorAll('span');
        for (const s of spans) {
            const t = s.textContent.toLowerCase();
            if (['tea garden','tea estate','tea plantation','tea company',
                 'tea factory','agriculture','farm'].includes(t)) {
                data.category = s.textContent.trim();
                break;
            }
        }
    }

    return data;
"""
