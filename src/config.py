"""Configuration for tea garden scraper with geospatial support."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

@dataclass
class DistrictConfig:
    """Configuration for a target district in Assam."""

    name: str
    center_lat: float
    center_lng: float
    radius_km: float = 50.0


# Major tea-growing districts in Assam with approximate centers
# Increased radius for major tea-growing districts to capture more estates
ASSAM_DISTRICTS: dict[str, DistrictConfig] = {
    "Dibrugarh": DistrictConfig(name="Dibrugarh", center_lat=27.4844, center_lng=94.9112, radius_km=80),
    "Jorhat": DistrictConfig(name="Jorhat", center_lat=26.7396, center_lng=94.2038, radius_km=70),
    "Tinsukia": DistrictConfig(name="Tinsukia", center_lat=27.4934, center_lng=95.3560, radius_km=75),
    "Sivasagar": DistrictConfig(name="Sivasagar", center_lat=26.9833, center_lng=94.6333, radius_km=60),
    "Golaghat": DistrictConfig(name="Golaghat", center_lat=26.5167, center_lng=93.9667, radius_km=65),
    "Kamrup": DistrictConfig(name="Kamrup", center_lat=26.1167, center_lng=91.5833, radius_km=60),
    "Sonitpur": DistrictConfig(name="Sonitpur", center_lat=26.6167, center_lng=92.9167, radius_km=70),
    "Cachar": DistrictConfig(name="Cachar", center_lat=24.8833, center_lng=92.7833, radius_km=65),
    "Nagaon": DistrictConfig(name="Nagaon", center_lat=26.3500, center_lng=92.6833, radius_km=60),
    "Lakhimpur": DistrictConfig(name="Lakhimpur", center_lat=27.2333, center_lng=94.1000, radius_km=65),
}


@dataclass
class GeospatialConfig:
    """Configuration for geospatial extraction."""

    # API Configuration
    google_maps_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_MAPS_API_KEY", ""))

    # Size thresholds for filtering (in square kilometers)
    min_area_km2: float = 0.5
    max_area_km2: float = 3.0

    # Workforce estimation: workers per square kilometer
    workforce_multiplier: float = 25.0

    # Search parameters
    default_search_radius_km: float = 50.0
    max_results_per_search: int = 60  # Increased to catch more results
    search_queries: list[str] = field(default_factory=lambda: [
        "tea garden",
        "tea estate",
        "tea plantation",
        "plantation",
        "tea factory",
        "tea co",
        "T.G.",
        "T G",
        "tea industries",
        "tea limited",
        "bagan",  # Local term for garden
    ])

    # Visual verification settings
    enable_screenshots: bool = False  # Disabled by default to save resources
    screenshot_dir: str = "output/screenshots"
    screenshot_delay_seconds: float = 2.0

    # Processing settings
    batch_size: int = 10
    rate_limit_delay: float = 0.1
    use_cached_geometry: bool = True
    cache_dir: str = ".cache/geospatial"

    # Target districts (comma-separated names or 'all')
    target_districts: list[str] = field(default_factory=lambda: ["Dibrugarh", "Jorhat", "Tinsukia"])

    # SAFETY LIMITS - Prevent unexpected API costs (local model has no real limits)
    # Maximum total API calls allowed (places + details queries)
    max_api_calls: int = 500
    # Maximum estates to fetch geometry details for
    max_estates_to_process: int = 200
    # Stop processing if this limit is reached
    hard_stop_on_limit: bool = False

    def __post_init__(self):
        """Validate configuration and create necessary directories."""
        if not self.google_maps_api_key:
            raise ValueError(
                "GOOGLE_MAPS_API_KEY not found. "
                "Set it in environment variables or .env file."
            )

        # Create directories
        Path(self.screenshot_dir).mkdir(parents=True, exist_ok=True)
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

    def get_districts(self) -> list[DistrictConfig]:
        """Get DistrictConfig objects for target districts."""
        if "all" in [d.lower() for d in self.target_districts]:
            return list(ASSAM_DISTRICTS.values())

        districts = []
        for name in self.target_districts:
            if name in ASSAM_DISTRICTS:
                districts.append(ASSAM_DISTRICTS[name])
            else:
                raise ValueError(f"Unknown district: {name}. Available: {list(ASSAM_DISTRICTS.keys())}")
        return districts


@dataclass
class ScraperConfig:
    """Configuration for web scraping operations."""

    tbi_base_url: str = "https://www.teaboard.gov.in/"
    min_workforce: int = 26
    max_workforce: int = 49
    concurrent_requests: int = 5
    headless: bool = True
    output_path: str = "output/gardens.csv"
    timeout_seconds: int = 30
    retry_attempts: int = 3

    # Source type identifiers
    source_local: str = "LOCAL_FILE"
    source_web: str = "WEB_SCRAPER"
    source_maps: str = "GOOGLE_MAPS_GEOMETRY"
    source_wikipedia: str = "WIKIPEDIA"


# Global config instances
_scraper_config: ScraperConfig | None = None
_geospatial_config: GeospatialConfig | None = None


def get_scraper_config(**kwargs) -> ScraperConfig:
    """Get or create scraper configuration with optional overrides."""
    global _scraper_config
    if _scraper_config is None:
        _scraper_config = ScraperConfig(**{k: v for k, v in kwargs.items() if v is not None})
    return _scraper_config


def get_geospatial_config(**kwargs) -> GeospatialConfig:
    """Get or create geospatial configuration with optional overrides."""
    global _geospatial_config
    if _geospatial_config is None:
        _geospatial_config = GeospatialConfig(**{k: v for k, v in kwargs.items() if v is not None})
    return _geospatial_config


def reset_configs():
    """Reset global config instances (useful for testing)."""
    global _scraper_config, _geospatial_config
    _scraper_config = None
    _geospatial_config = None
