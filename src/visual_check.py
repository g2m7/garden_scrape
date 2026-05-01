"""Visual verification module for tea garden satellite imagery."""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException

from config import get_geospatial_config

logger = logging.getLogger(__name__)


class VerificationStatus(Enum):
    """Status of visual verification attempt."""

    SUCCESS = "screenshot_captured"
    NO_GEOMETRY = "no_geometry_available"
    TIMEOUT = "screenshot_timeout"
    DRIVER_ERROR = "driver_initialization_failed"
    NOT_VISIBLE = "boundary_not_visible"
    CACHED = "used_cached_screenshot"


@dataclass
class VerificationResult:
    """Result of a visual verification attempt."""

    estate_name: str
    status: VerificationStatus
    screenshot_path: str | None = None
    maps_url: str | None = None
    error_message: str | None = None
    timestamp: str | None = None


class VisualVerifier:
    """
    Captures satellite imagery of tea estates for manual verification.

    Uses Selenium to:
    1. Open Google Maps at specific coordinates
    2. Switch to satellite view
    3. Capture screenshot of the estate area
    4. Save image for manual review
    """

    def __init__(self, config=None, headless: bool = True):
        """
        Initialize the visual verifier.

        Args:
            config: GeospatialConfig instance
            headless: Whether to run browser in headless mode
        """
        self.config = config or get_geospatial_config()
        self.headless = headless
        self._driver = None

    @property
    def driver(self):
        """Lazy-load the Selenium WebDriver."""
        if self._driver is None:
            self._driver = self._init_driver()
        return self._driver

    def capture_estate_image(
        self,
        latitude: float,
        longitude: float,
        estate_name: str,
        zoom_level: int = 16,
    ) -> VerificationResult:
        """
        Capture satellite image of an estate.

        Args:
            latitude: Estate latitude
            longitude: Estate longitude
            estate_name: Name for file naming
            zoom_level: Google Maps zoom level (1-20, higher = closer)

        Returns:
            VerificationResult with screenshot path or error details
        """
        if not self.config.enable_screenshots:
            return VerificationResult(
                estate_name=estate_name,
                status=VerificationStatus.NO_GEOMETRY,
                error_message="Screenshots disabled in config",
            )

        # Check for existing screenshot
        screenshot_path = self._get_screenshot_path(estate_name)
        if screenshot_path.exists():
            logger.debug(f"Using cached screenshot for {estate_name}")
            return VerificationResult(
                estate_name=estate_name,
                status=VerificationStatus.CACHED,
                screenshot_path=str(screenshot_path),
                maps_url=self._build_maps_url(latitude, longitude, zoom_level),
            )

        try:
            # Build Google Maps URL
            maps_url = self._build_maps_url(latitude, longitude, zoom_level)

            # Navigate and capture
            self.driver.get(maps_url)
            time.sleep(self.config.screenshot_delay_seconds)

            # Try to dismiss any popups
            self._dismiss_popups()

            # Capture screenshot
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            self.driver.save_screenshot(str(screenshot_path))

            logger.info(f"Captured screenshot for {estate_name}: {screenshot_path}")

            return VerificationResult(
                estate_name=estate_name,
                status=VerificationStatus.SUCCESS,
                screenshot_path=str(screenshot_path),
                maps_url=maps_url,
            )

        except TimeoutException:
            logger.error(f"Timeout capturing screenshot for {estate_name}")
            return VerificationResult(
                estate_name=estate_name,
                status=VerificationStatus.TIMEOUT,
                error_message="Page load timeout",
                maps_url=self._build_maps_url(latitude, longitude, zoom_level),
            )

        except WebDriverException as e:
            logger.error(f"WebDriver error for {estate_name}: {e}")
            return VerificationResult(
                estate_name=estate_name,
                status=VerificationStatus.DRIVER_ERROR,
                error_message=str(e),
            )

        except Exception as e:
            logger.error(f"Unexpected error for {estate_name}: {e}")
            return VerificationResult(
                estate_name=estate_name,
                status=VerificationStatus.NOT_VISIBLE,
                error_message=str(e),
            )

    def batch_capture(
        self,
        estates: list[dict],
        zoom_level: int = 16,
        delay_seconds: float = 0.5,
    ) -> list[VerificationResult]:
        """
        Capture screenshots for multiple estates.

        Args:
            estates: List of dicts with keys: estate_name, latitude, longitude
            zoom_level: Google Maps zoom level
            delay_seconds: Delay between captures

        Returns:
            List of VerificationResult objects
        """
        results = []

        try:
            for i, estate in enumerate(estates):
                logger.info(f"Capturing {i+1}/{len(estates)}: {estate.get('estate_name')}")

                result = self.capture_estate_image(
                    latitude=estate["latitude"],
                    longitude=estate["longitude"],
                    estate_name=estate["estate_name"],
                    zoom_level=zoom_level,
                )
                results.append(result)

                # Add delay between captures
                if i < len(estates) - 1:
                    time.sleep(delay_seconds)

        except Exception as e:
            logger.error(f"Batch capture error: {e}")

        return results

    def close(self) -> None:
        """Close the WebDriver and cleanup resources."""
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def _init_driver(self):
        """Initialize Selenium WebDriver."""
        try:
            # Try Firefox first (often more stable for screenshots)
            options = FirefoxOptions()

            if self.headless:
                options.add_argument("--headless")

            # Additional options for stability
            options.set_preference("dom.webnotifications.enabled", False)
            options.set_preference("geo.enabled", True)
            options.set_preference("geo.provider.use_corelocation", False)
            options.set_preference("geo.prompt.testing", True)
            options.set_preference("geo.prompt.testing.allow", True)

            # Window size for consistent screenshots
            options.add_argument("--width=1280")
            options.add_argument("--height=720")

            driver = webdriver.Firefox(options=options)
            logger.info("Firefox WebDriver initialized")

            return driver

        except Exception as e:
            logger.warning(f"Firefox WebDriver failed: {e}")

            # Fallback to Chrome
            try:
                from selenium import webdriver as chrome_driver
                from selenium.webdriver.chrome.options import Options as ChromeOptions

                options = ChromeOptions()

                if self.headless:
                    options.add_argument("--headless=new")

                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                options.add_argument("--window-size=1280,720")
                options.add_argument("--disable-gpu")
                options.add_argument("--disable-notifications")

                driver = chrome_driver.Chrome(options=options)
                logger.info("Chrome WebDriver initialized (fallback)")

                return driver

            except Exception as chrome_error:
                logger.error(f"Chrome WebDriver also failed: {chrome_error}")
                raise RuntimeError(
                    "Could not initialize any WebDriver. "
                    "Install geckodriver (Firefox) or chromedriver (Chrome)."
                )

    def _build_maps_url(self, lat: float, lng: float, zoom: int) -> str:
        """Build Google Maps URL for satellite view."""
        return f"https://www.google.com/maps/@{lat},{lng},{zoom}z/data=!3m1!1e3"

    def _dismiss_popups(self) -> None:
        """Attempt to dismiss common Google Maps popups."""
        try:
            wait = WebDriverWait(self.driver, 2)

            # Try to dismiss cookie consent
            consent_button = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label*='Accept']"))
            )
            consent_button.click()
            time.sleep(0.5)

        except TimeoutException:
            # No popup, that's fine
            pass
        except Exception:
            # Popup dismissal failed, continue anyway
            pass

    def _get_screenshot_path(self, estate_name: str) -> Path:
        """Generate screenshot file path for an estate."""
        # Sanitize name for filesystem
        safe_name = "".join(
            c for c in estate_name
            if c.isalnum() or c in (" ", "-", "_")
        ).strip() or "unknown"

        safe_name = safe_name.replace(" ", "_")[:50]  # Limit length

        return Path(self.config.screenshot_dir) / f"{safe_name}.png"


def create_verifier(
    headless: bool = True,
    enable_screenshots: bool = True,
) -> VisualVerifier:
    """
    Factory function to create a VisualVerifier.

    Args:
        headless: Run browser in headless mode
        enable_screenshots: Enable screenshot capture

    Returns:
        Configured VisualVerifier instance
    """
    from config import GeospatialConfig

    config = GeospatialConfig(enable_screenshots=enable_screenshots)
    return VisualVerifier(config=config, headless=headless)


def add_visual_proof_column(
    df: "pd.DataFrame",
    results: list[VerificationResult],
) -> "pd.DataFrame":
    """
    Add screenshot paths to DataFrame based on verification results.

    Args:
        df: DataFrame with estate_name column
        results: List of VerificationResult objects

    Returns:
        DataFrame with added visual_proof column
    """
    import pandas as pd

    # Create mapping of estate names to screenshot paths
    proof_map = {
        result.estate_name: result.screenshot_path
        for result in results
        if result.screenshot_path
    }

    # Add column
    df = df.copy()
    df["visual_proof"] = df["estate_name"].map(proof_map)
    df["verification_status"] = df["estate_name"].map({
        result.estate_name: result.status.value
        for result in results
    })

    return df
