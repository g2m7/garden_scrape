"""Data models for tea garden scraping."""

from pydantic import BaseModel, Field, field_validator
from typing import Literal


class TeaGarden(BaseModel):
    """Raw tea garden data from any source."""

    estate_name: str
    workforce_count: int | None = None
    primary_phone: str | None = None
    contact_person: str | None = None
    source_origin: str

    # Geospatial fields
    latitude: float | None = None
    longitude: float | None = None
    area_km2: float | None = None
    place_id: str | None = None
    address: str | None = None
    visual_proof: str | None = None

    @field_validator("workforce_count")
    @classmethod
    def validate_workforce(cls, v: int | None) -> int | None:
        """Ensure workforce is positive if provided."""
        if v is not None and v < 0:
            raise ValueError("Workforce count cannot be negative")
        return v

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: float | None) -> float | None:
        """Ensure latitude is valid."""
        if v is not None and not (-90 <= v <= 90):
            raise ValueError(f"Latitude must be between -90 and 90, got {v}")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: float | None) -> float | None:
        """Ensure longitude is valid."""
        if v is not None and not (-180 <= v <= 180):
            raise ValueError(f"Longitude must be between -180 and 180, got {v}")
        return v


class StandardizedGarden(BaseModel):
    """Final standardized tea garden record."""

    estate_id: str
    estate_name: str
    workforce_count: int
    primary_phone: str
    contact_person: str
    source_origin: str
    is_inferred: bool = False

    # Geospatial fields (optional)
    latitude: float | None = None
    longitude: float | None = None
    area_km2: float | None = None
    place_id: str | None = None
    address: str | None = None
    visual_proof: str | None = None
    verification_status: Literal["verified", "inferred", "pending"] = "pending"

    @field_validator("workforce_count")
    @classmethod
    def check_workforce_range(cls, v: int) -> int:
        """Ensure workforce is within target range (exclusive bounds)."""
        if not (25 < v < 50):
            raise ValueError(f"Workforce {v} not in range (25, 50)")
        return v

    @field_validator("primary_phone")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        """Normalize phone to +91-XX-XXXXXXX format."""
        # Basic normalization - can be enhanced
        cleaned = "".join(c for c in v if c.isdigit())
        if cleaned.startswith("91") and len(cleaned) == 12:
            return f"+91-{cleaned[2:4]}-{cleaned[4:]}"
        if len(cleaned) == 10:
            return f"+91-{cleaned[0:2]}-{cleaned[2:]}"
        return v


class ScrapingConfig(BaseModel):
    """Configuration for scraping operations."""

    tbi_base_url: str
    min_workforce: int = 26
    max_workforce: int = 49
    concurrent_requests: int = 5
    headless: bool = True
    output_path: str = "output/gardens.csv"
