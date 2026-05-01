"""Data ingestion module supporting local files and web sources."""

import io
import logging
import os
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Literal

import pandas as pd

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Set environment before importing crawl4ai
os.environ["CRAWL4AI_DISABLE_LOGGING"] = "1"

from crawl4ai import AsyncWebCrawler, BrowserConfig

from parsers import parse_pdf_tables

logger = logging.getLogger(__name__)

# Status codes for scraping results
ScrapeStatus = Literal["SUCCESS", "AUTH_REQUIRED", "EMPTY_RESPONSE", "ERROR"]


def load_local_source(file_path: str) -> pd.DataFrame:
    """
    Accepts PDF, CSV, or Excel files directly from local disk.

    Returns:
        DataFrame with columns mapped to standard schema
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = path.suffix.lower()

    logger.info(f"Loading local file: {file_path} (type: {suffix})")

    if suffix == ".pdf":
        df = parse_pdf_tables(file_path)
    elif suffix == ".csv":
        df = pd.read_csv(file_path)
    elif suffix in [".xlsx", ".xls"]:
        df = pd.read_excel(file_path)
    else:
        raise ValueError(f"Unsupported file format: {suffix}")

    logger.info(f"Loaded {len(df)} records from {file_path}")
    return df


def verify_scrape_status(result) -> tuple[ScrapeStatus, str]:
    """
    Check the status of a web scrape attempt.

    Returns:
        Tuple of (status_code, message)
    """
    # Check for authentication required
    if hasattr(result, "status_code") and result.status_code == 403:
        return "AUTH_REQUIRED", "403 Forbidden - Authentication required"

    # Check for login indicators in content
    if hasattr(result, "html"):
        html_lower = result.html.lower() if result.html else ""
        login_indicators = ["login", "sign in", "authenticate", "log in", "password"]
        if any(indicator in html_lower for indicator in login_indicators):
            if len(html_lower) < 5000:  # Login page is usually small
                return "AUTH_REQUIRED", "Login page detected"

    # Check for empty response
    if hasattr(result, "success") and not result.success:
        return "ERROR", "Scrape failed"

    if hasattr(result, "html") and len(result.html or "") < 1000:
        return "EMPTY_RESPONSE", f"Response too short: {len(result.html or '')} chars"

    return "SUCCESS", "Scrape successful"


async def scrape_with_fallback(
    url: str,
    local_fallback: str | None = None,
) -> tuple[pd.DataFrame, ScrapeStatus]:
    """
    Scrape a URL with automatic fallback to local file if auth detected.

    Args:
        url: URL to scrape
        local_fallback: Optional local file path to use if scrape fails

    Returns:
        Tuple of (DataFrame, status_code)
    """
    config = BrowserConfig(headless=True, verbose=False)

    try:
        async with AsyncWebCrawler(config=config) as crawler:
            null_out = io.StringIO()
            null_err = io.StringIO()

            with redirect_stdout(null_out), redirect_stderr(null_err):
                result = await crawler.arun(url=url)

            status, message = verify_scrape_status(result)

            if status == "SUCCESS":
                # Convert to DataFrame - would need extraction logic here
                # For now, return empty DF with success status
                logger.info(f"Successful scrape: {message}")
                return pd.DataFrame(), status
            elif status == "AUTH_REQUIRED":
                logger.warning(f"Authentication required: {message}")
                if local_fallback:
                    logger.info(f"Falling back to local file: {local_fallback}")
                    df = load_local_source(local_fallback)
                    return df, "FALLBACK_SUCCESS"
                else:
                    return pd.DataFrame(), status
            else:
                logger.warning(f"Scrape failed: {message}")
                return pd.DataFrame(), status

    except Exception as e:
        logger.error(f"Scrape error: {e}")
        if local_fallback:
            logger.info(f"Falling back to local file: {local_fallback}")
            try:
                df = load_local_source(local_fallback)
                return df, "FALLBACK_SUCCESS"
            except Exception as fallback_error:
                logger.error(f"Fallback also failed: {fallback_error}")
        return pd.DataFrame(), "ERROR"


def batch_ingest(
    sources: list[str],
    mode: Literal["web", "local", "auto"] = "auto",
) -> list[pd.DataFrame]:
    """
    Ingest data from multiple sources.

    Args:
        sources: List of URLs or file paths
        mode: 'web' for web only, 'local' for files only, 'auto' to detect

    Returns:
        List of DataFrames from each source
    """
    results = []

    for source in sources:
        try:
            if mode == "local" or (mode == "auto" and Path(source).exists()):
                df = load_local_source(source)
                results.append(df)
            elif mode == "web" or (mode == "auto" and source.startswith("http")):
                df, status = asyncio.run(scrape_with_fallback(source))
                if not df.empty:
                    results.append(df)
            else:
                logger.warning(f"Skipping unknown source: {source}")
        except Exception as e:
            logger.error(f"Failed to ingest {source}: {e}")

    return results
