"""Data processing pipeline for tea garden data."""

import logging
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from models import StandardizedGarden, TeaGarden
from parsers import extract_phone, extract_workforce, map_columns

logger = logging.getLogger(__name__)


class DataPipeline:
    """Processing pipeline for tea garden data."""

    def __init__(
        self,
        min_workforce: int = 26,
        max_workforce: int = 49,
    ) -> None:
        self.min_workforce = min_workforce
        self.max_workforce = max_workforce

    def process_dataframe(
        self,
        df: pd.DataFrame,
    ) -> tuple[list[StandardizedGarden], list[str]]:
        """Process a pandas DataFrame through the pipeline.

        Args:
            df: Input DataFrame with raw data

        Returns:
            Tuple of (validated gardens, error log messages)
        """
        errors: list[str] = []

        # Step 1: Map columns to standard schema
        df = map_columns(df)

        # Step 2: Convert DataFrame to TeaGarden models
        raw_gardens = self._dataframe_to_gardens(df, errors)

        # Step 3: Run standard pipeline processing
        return self.process(raw_gardens, errors)

    def process(
        self,
        raw_data: list[TeaGarden],
        errors: list[str] | None = None,
    ) -> tuple[list[StandardizedGarden], list[str]]:
        """Process raw data through the pipeline.

        Returns:
            Tuple of (validated gardens, error log messages)
        """
        if errors is None:
            errors = []

        # Module 2: Processing & Cleaning Layer
        deduplicated = self._deduplicate(raw_data, errors)
        filtered = self._filter_by_workforce(deduplicated, errors)

        # Module 3: Standardization Layer
        standardized = self._standardize(filtered, errors)

        # Module 4: Output Layer
        return standardized, errors

    def _dataframe_to_gardens(
        self,
        df: pd.DataFrame,
        errors: list[str],
    ) -> list[TeaGarden]:
        """Convert DataFrame rows to TeaGarden models."""
        gardens: list[TeaGarden] = []

        for idx, row in df.iterrows():
            try:
                # Extract estate name
                name = row.get("estate_name")
                if pd.isna(name) or not str(name).strip():
                    continue

                estate_name = str(name).strip()

                # Extract workforce - check for estimated_workforce first (from geospatial)
                workforce_raw = row.get("estimated_workforce") or row.get("workforce_count")
                workforce = extract_workforce(workforce_raw)

                # Extract phone
                phone_raw = row.get("primary_phone")
                phone = extract_phone(phone_raw)

                # Extract contact person
                contact_raw = row.get("contact_person")
                contact = (
                    str(contact_raw).strip()
                    if not pd.isna(contact_raw) and str(contact_raw).strip()
                    else None
                )

                # Get source origin
                source = row.get("source_origin", "Unknown_Source")
                if pd.isna(source):
                    source = "Unknown_Source"
                source = str(source)

                # Geospatial fields
                latitude = row.get("latitude")
                longitude = row.get("longitude")
                area_km2 = row.get("area_km2")
                place_id = row.get("place_id")
                address = row.get("address")
                visual_proof = row.get("visual_proof")

                garden = TeaGarden(
                    estate_name=estate_name,
                    workforce_count=workforce,
                    primary_phone=phone,
                    contact_person=contact,
                    source_origin=source,
                    latitude=float(latitude) if pd.notna(latitude) else None,
                    longitude=float(longitude) if pd.notna(longitude) else None,
                    area_km2=float(area_km2) if pd.notna(area_km2) else None,
                    place_id=str(place_id) if pd.notna(place_id) else None,
                    address=str(address).strip() if pd.notna(address) and str(address).strip() else None,
                    visual_proof=str(visual_proof) if pd.notna(visual_proof) else None,
                )
                gardens.append(garden)

            except Exception as e:
                errors.append(f"Row {idx}: {e}")
                continue

        return gardens

    def _deduplicate(
        self,
        data: list[TeaGarden],
        errors: list[str],
    ) -> list[TeaGarden]:
        """Remove duplicates based on estate name and phone."""
        seen: dict[str, TeaGarden] = {}
        duplicate_count = 0

        for garden in data:
            key = self._generate_key(garden)
            if key in seen:
                duplicate_count += 1
                # Keep the one with more complete data
                existing = seen[key]
                if self._completeness_score(garden) > self._completeness_score(existing):
                    seen[key] = garden
            else:
                seen[key] = garden

        if duplicate_count:
            logger.info(f"Removed {duplicate_count} duplicate entries")

        return list(seen.values())

    def _filter_by_workforce(
        self,
        data: list[TeaGarden],
        errors: list[str],
    ) -> list[TeaGarden]:
        """Filter gardens by workforce range."""
        filtered = [
            g
            for g in data
            if g.workforce_count is not None
            and self.min_workforce <= g.workforce_count <= self.max_workforce
        ]

        rejected = len(data) - len(filtered)
        if rejected:
            errors.append(f"Filtered out {rejected} gardens outside workforce range")

        return filtered

    def _standardize(
        self,
        data: list[TeaGarden],
        errors: list[str],
    ) -> list[StandardizedGarden]:
        """Standardize garden data and enrich missing fields."""
        standardized: list[StandardizedGarden] = []
        name_groups = self._group_by_similar_names(data)

        for garden in data:
            try:
                # Use canonical name from group
                canonical_name = self._get_canonical_name(garden.estate_name, name_groups)

                # Determine verification status based on source
                verification_status = "pending"
                is_inferred = garden.workforce_count is None

                if garden.source_origin == "GOOGLE_MAPS_GEOMETRY":
                    verification_status = "verified" if garden.visual_proof else "inferred"
                elif garden.source_origin in ("LOCAL_FILE", "WEB_SCRAPER"):
                    verification_status = "inferred" if is_inferred else "verified"

                std = StandardizedGarden(
                    estate_id=str(uuid.uuid4())[:8],
                    estate_name=canonical_name,
                    workforce_count=garden.workforce_count or 0,
                    primary_phone=garden.primary_phone or "Unknown",
                    contact_person=garden.contact_person or "Estate Management",
                    source_origin=garden.source_origin,
                    is_inferred=is_inferred,
                    latitude=garden.latitude,
                    longitude=garden.longitude,
                    area_km2=garden.area_km2,
                    place_id=garden.place_id,
                    address=garden.address,
                    visual_proof=garden.visual_proof,
                    verification_status=verification_status,
                )
                standardized.append(std)
            except Exception as e:
                errors.append(f"Failed to standardize {garden.estate_name}: {e}")

        return standardized

    def export_to_csv(self, data: list[StandardizedGarden], filepath: str) -> None:
        """Export standardized data to CSV."""
        df = pd.DataFrame([g.model_dump() for g in data])
        df.to_csv(filepath, index=False)
        logger.info(f"Exported {len(data)} records to {filepath}")

    def export_to_excel(self, data: list[StandardizedGarden], filepath: str) -> None:
        """Export standardized data to Excel with multiple sheets."""
        df = pd.DataFrame([g.model_dump() for g in data])

        # Create Excel writer with multiple sheets
        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Validated_Gardens", index=False)

            # Create a summary sheet
            summary = pd.DataFrame(
                {
                    "Metric": ["Total Records", "Unique Gardens", "With Phone", "Inferred Data"],
                    "Count": [
                        len(data),
                        len(set(g.estate_name for g in data)),
                        sum(1 for g in data if g.primary_phone != "Unknown"),
                        sum(1 for g in data if g.is_inferred),
                    ],
                }
            )
            summary.to_excel(writer, sheet_name="Summary", index=False)

        logger.info(f"Exported {len(data)} records to {filepath}")

    @staticmethod
    def _generate_key(garden: TeaGarden) -> str:
        """Generate deduplication key."""
        return f"{garden.estate_name.lower()}|{garden.primary_phone or ''}"

    @staticmethod
    def _completeness_score(garden: TeaGarden) -> int:
        """Score data completeness (0-4)."""
        score = 0
        if garden.estate_name:
            score += 1
        if garden.workforce_count:
            score += 1
        if garden.primary_phone:
            score += 1
        if garden.contact_person:
            score += 1
        return score

    @staticmethod
    def _group_by_similar_names(data: list[TeaGarden]) -> dict[str, list[str]]:
        """Group gardens by similar names for normalization."""
        groups: dict[str, list[str]] = defaultdict(list)

        for garden in data:
            # Simple normalization: lowercase, remove common suffixes
            normalized = (
                garden.estate_name.lower()
                .replace(" tea garden", "")
                .replace(" t.g.", "")
                .replace(" estate", "")
                .strip()
            )
            groups[normalized].append(garden.estate_name)

        return groups

    @staticmethod
    def _get_canonical_name(name: str, groups: dict[str, list[str]]) -> str:
        """Get canonical name from group (pick longest)."""
        normalized = name.lower().replace(" tea garden", "").replace(" t.g.", "").strip()
        if normalized in groups and groups[normalized]:
            # Return the longest name as canonical
            return max(groups[normalized], key=len)
        return name
