"""Geospatial extraction module for tea garden data using Google Maps API."""

import asyncio
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from config import (
    ASSAM_DISTRICTS,
    DistrictConfig,
    GeospatialConfig,
    get_geospatial_config,
    get_scraper_config,
)

logger = logging.getLogger(__name__)


@dataclass
class EstateGeometry:
    """Geometry data for a tea estate."""

    estate_name: str
    place_id: str
    latitude: float
    longitude: float
    phone: str | None = None
    area_km2: float | None = None
    viewport: dict[str, Any] | None = None
    bounds: dict[str, Any] | None = None
    polygon_coords: list[tuple[float, float]] | None = None
    address: str | None = None
    estimated_workforce: int | None = None


@dataclass
class SearchResults:
    """Results from a geospatial search operation."""

    estates_found: int = 0
    estates_with_geometry: int = 0
    estates_meeting_criteria: int = 0
    estates_skipped_no_phone: int = 0  # Estates filtered out due to missing phone
    total_area_km2: float = 0.0
    errors: list[str] = field(default_factory=list)
    processing_time_seconds: float = 0.0


class GeospatialExtractor:
    """
    Extracts tea garden data from Google Maps Platform.

    Features:
    - Search for tea gardens by district/region
    - Fetch geometry data (viewport, bounds, polygons)
    - Calculate physical footprint in square kilometers
    - Estimate workforce based on area
    - Cache results to avoid redundant API calls
    """

    def __init__(self, config: GeospatialConfig | None = None):
        """
        Initialize the geospatial extractor.

        Args:
            config: GeospatialConfig instance. If None, uses default config.
        """
        self.config = config or get_geospatial_config()

        # Lazy-load googlemaps client to avoid import errors if API key missing
        self._gm = None
        self._cache_enabled = self.config.use_cached_geometry
        self._cache_dir = Path(self.config.cache_dir)

        # API call tracking for cost control
        self._api_calls_made = 0
        self._estates_processed = 0
        self._limit_reached = False

    def _check_limits(self) -> bool:
        """Check if we've hit any safety limits."""
        if self._limit_reached:
            return False

        if self._api_calls_made >= self.config.max_api_calls:
            logger.warning(
                f"API call limit reached: {self._api_calls_made}/{self.config.max_api_calls}"
            )
            self._limit_reached = True
            return False

        if self._estates_processed >= self.config.max_estates_to_process:
            logger.warning(
                f"Estate processing limit reached: {self._estates_processed}/{self.config.max_estates_to_process}"
            )
            self._limit_reached = True
            return False

        return True

    def _record_api_call(self) -> None:
        """Record an API call and check limits."""
        self._api_calls_made += 1
        logger.debug(f"API calls: {self._api_calls_made}/{self.config.max_api_calls}")
        if not self._check_limits() and self.config.hard_stop_on_limit:
            raise StopIteration("API call limit reached")

    def _record_estate_processed(self) -> None:
        """Record an estate detail fetch."""
        self._estates_processed += 1
        logger.debug(f"Estates processed: {self._estates_processed}/{self.config.max_estates_to_process}")

    def get_api_stats(self) -> dict[str, int]:
        """Get current API usage statistics."""
        return {
            "api_calls_made": self._api_calls_made,
            "api_calls_limit": self.config.max_api_calls,
            "estates_processed": self._estates_processed,
            "estates_limit": self.config.max_estates_to_process,
            "limit_reached": self._limit_reached,
        }

    @property
    def gm(self):
        """Lazy-load the Google Maps client."""
        if self._gm is None:
            try:
                import googlemaps

                self._gm = googlemaps.Client(key=self.config.google_maps_api_key)
                logger.info("Google Maps client initialized")
            except ImportError:
                raise ImportError(
                    "googlemaps package not installed. "
                    "Install with: pip install googlemaps"
                )
        return self._gm

    def search_estates(
        self,
        district: DistrictConfig | None = None,
        location_query: str | None = None,
        radius_km: float | None = None,
    ) -> pd.DataFrame:
        """
        Search for tea gardens in a specific district or location.

        Args:
            district: DistrictConfig with center coordinates and radius
            location_query: Custom location search query (overrides district)
            radius_km: Search radius in kilometers

        Returns:
            DataFrame with columns: name, place_id, location, address
        """
        results = []

        # Determine search parameters
        if location_query:
            # Use custom query with geocoding
            center = self._geocode_location(location_query)
            if center is None:
                logger.error(f"Could not geocode location: {location_query}")
                return pd.DataFrame()
            search_radius = radius_km or self.config.default_search_radius_km
        elif district:
            center = (district.center_lat, district.center_lng)
            search_radius = radius_km or district.radius_km
        else:
            raise ValueError("Must provide either district or location_query")

        logger.info(f"Searching {search_radius}km radius around {center}")

        # Phase 1: Radius-based search (nearby search)
        for query in self.config.search_queries:
            full_query = f"{query} {location_query or district.name if district else ''}".strip()

            try:
                response = self._search_places_with_pagination(
                    query=full_query,
                    location=center,
                    radius=search_radius * 1000,  # Convert to meters
                )

                for place in response:
                    # Avoid duplicates
                    if not any(p["place_id"] == place["place_id"] for p in results):
                        results.append({
                            "name": place.get("name"),
                            "place_id": place.get("place_id"),
                            "location": place.get("geometry", {}).get("location"),
                            "address": place.get("formatted_address"),
                            "types": place.get("types", []),
                        })

            except Exception as e:
                logger.warning(f"Search failed for query '{full_query}': {e}")
                continue

        logger.info(f"Phase 1 (radius search): found {len(results)} estates")

        # Phase 2: Text search for broader coverage (if results are low and we have API budget)
        if len(results) < 50 and self._check_limits():
            logger.info("Phase 2: Running text search for broader coverage...")

            # Use broader text search queries without the district name
            broad_queries = [
                f"tea garden Assam",
                f"tea estate Assam",
            ]

            for query in broad_queries:
                if not self._check_limits():
                    break

                try:
                    response = self._search_places_text(
                        query=query,
                        location=center,
                    )

                    for place in response:
                        # Avoid duplicates
                        if not any(p["place_id"] == place["place_id"] for p in results):
                            # Filter by distance to ensure they're in the target district
                            place_loc = place.get("geometry", {}).get("location", {})
                            if place_loc:
                                place_lat = place_loc.get("lat")
                                place_lng = place_loc.get("lng")
                                if self._is_within_distance(
                                    place_lat, place_lng, center[0], center[1], search_radius
                                ):
                                    results.append({
                                        "name": place.get("name"),
                                        "place_id": place.get("place_id"),
                                        "location": place.get("geometry", {}).get("location"),
                                        "address": place.get("formatted_address"),
                                        "types": place.get("types", []),
                                    })

                except Exception as e:
                    logger.warning(f"Text search failed for '{query}': {e}")
                    continue

            logger.info(f"Phase 2 (text search): total now {len(results)} estates")

        df = pd.DataFrame(results)
        logger.info(f"Final count: {len(df)} estates in {location_query or district.name if district else 'search'}")
        return df

    def _is_within_distance(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
        max_distance_km: float,
    ) -> bool:
        """Check if two coordinates are within max_distance_km of each other."""
        import math

        # Haversine formula
        R = 6371  # Earth's radius in km
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.asin(math.sqrt(a))
        distance = R * c

        return distance <= max_distance_km

    def get_estate_geometry(self, place_id: str, estate_name: str | None = None) -> EstateGeometry | None:
        """
        Fetch geometry data for a specific estate and calculate area.

        IMPORTANT: Skips estates without phone numbers to avoid wasting API calls.

        Args:
            place_id: Google Maps place_id
            estate_name: Optional name for logging

        Returns:
            EstateGeometry with calculated area or None if unavailable or no phone
        """
        # Check limits before processing
        if not self._check_limits():
            logger.warning(f"Skipping {estate_name or place_id}: limits reached")
            return None

        # Check cache first (cache hits don't count toward API limit)
        if self._cache_enabled:
            cached = self._load_from_cache(place_id)
            if cached:
                # Even cached results must have a phone number
                if not cached.phone:
                    logger.debug(f"Skipping cached {estate_name or place_id}: no phone")
                    return None
                logger.debug(f"Cache hit for {place_id}")
                self._record_estate_processed()
                return cached

        try:
            # Fetch place details with geometry AND phone number
            self._record_api_call()
            details = self.gm.place(
                place_id=place_id,
                fields=["name", "geometry", "formatted_address", "place_id", "formatted_phone_number", "international_phone_number"],
            )

            if "result" not in details:
                logger.warning(f"No details found for place_id: {place_id}")
                return None

            result = details["result"]

            # CRITICAL: Skip if no phone number available
            phone = result.get("formatted_phone_number") or result.get("international_phone_number")
            if not phone:
                logger.debug(f"Skipping {estate_name or place_id}: no phone number")
                return None

            geometry = result.get("geometry")
            if not geometry:
                logger.warning(f"No geometry for {estate_name or place_id}")
                return None

            # Extract coordinates
            location = geometry.get("location", {})
            lat = location.get("lat")
            lng = location.get("lng")

            if not lat or not lng:
                return None

            # Calculate area from available geometry
            area_km2 = self._calculate_area_from_geometry(geometry)

            # Estimate workforce
            estimated_workforce = None
            if area_km2:
                estimated_workforce = int(area_km2 * self.config.workforce_multiplier)

            estate_geom = EstateGeometry(
                estate_name=estate_name or result.get("name", ""),
                place_id=place_id,
                latitude=lat,
                longitude=lng,
                phone=phone,
                area_km2=area_km2,
                viewport=geometry.get("viewport"),
                bounds=geometry.get("bounds"),
                address=result.get("formatted_address"),
                estimated_workforce=estimated_workforce,
            )

            # Cache the result
            if self._cache_enabled:
                self._save_to_cache(place_id, estate_geom)

            self._record_estate_processed()
            return estate_geom

        except Exception as e:
            logger.error(f"Error fetching geometry for {estate_name or place_id}: {e}")
            return None

    def process_district(
        self,
        district: DistrictConfig,
        min_workforce: int = 26,
        max_workforce: int = 49,
    ) -> tuple[pd.DataFrame, SearchResults]:
        """
        Complete processing pipeline for a single district.

        Args:
            district: DistrictConfig to process
            min_workforce: Minimum workforce threshold
            max_workforce: Maximum workforce threshold

        Returns:
            Tuple of (DataFrame with processed estates, SearchResults summary)
        """
        start_time = datetime.now()
        results = SearchResults()

        logger.info(f"Processing district: {district.name}")

        # Step 1: Search for estates
        estates_df = self.search_estates(district=district)
        results.estates_found = len(estates_df)

        if estates_df.empty:
            logger.warning(f"No estates found in {district.name}")
            return estates_df, results

        # Step 2: Fetch geometry for each estate
        geometries = []
        for _, row in estates_df.iterrows():
            geom = self.get_estate_geometry(
                place_id=row["place_id"],
                estate_name=row["name"],
            )
            if geom:
                geometries.append(geom)
                if geom.area_km2:
                    results.estates_with_geometry += 1
            else:
                # Track separately: skipped due to no phone vs other errors
                # The get_estate_geometry method returns None for no phone
                results.estates_skipped_no_phone += 1

        # Step 3: Convert to DataFrame and filter
        processed_df = pd.DataFrame([
            {
                "estate_name": g.estate_name,
                "place_id": g.place_id,
                "latitude": g.latitude,
                "longitude": g.longitude,
                "phone": g.phone,
                "area_km2": g.area_km2,
                "estimated_workforce": g.estimated_workforce,
                "address": g.address,
                "source_origin": get_scraper_config().source_maps,
            }
            for g in geometries
        ])

        # Step 4: Filter by workforce criteria
        if not processed_df.empty:
            processed_df = processed_df[
                (processed_df["estimated_workforce"] >= min_workforce) &
                (processed_df["estimated_workforce"] <= max_workforce)
            ]
            results.estates_meeting_criteria = len(processed_df)
            results.total_area_km2 = processed_df["area_km2"].sum()

        results.processing_time_seconds = (datetime.now() - start_time).total_seconds()

        logger.info(
            f"District {district.name}: "
            f"{results.estates_found} found, "
            f"{results.estates_skipped_no_phone} skipped (no phone), "
            f"{results.estates_with_geometry} with geometry, "
            f"{results.estates_meeting_criteria} meeting criteria"
        )

        return processed_df, results

    def process_multiple_districts(
        self,
        districts: list[DistrictConfig] | None = None,
        min_workforce: int = 26,
        max_workforce: int = 49,
    ) -> tuple[pd.DataFrame, SearchResults]:
        """
        Process multiple districts and combine results.

        Args:
            districts: List of DistrictConfig objects. If None, uses config target_districts
            min_workforce: Minimum workforce threshold
            max_workforce: Maximum workforce threshold

        Returns:
            Tuple of (combined DataFrame, aggregated SearchResults)
        """
        if districts is None:
            districts = self.config.get_districts()

        all_dfs = []
        all_results = SearchResults()

        for district in districts:
            try:
                df, results = self.process_district(district, min_workforce, max_workforce)
                all_dfs.append(df)
                all_results.estates_found += results.estates_found
                all_results.estates_skipped_no_phone += results.estates_skipped_no_phone
                all_results.estates_with_geometry += results.estates_with_geometry
                all_results.estates_meeting_criteria += results.estates_meeting_criteria
                all_results.total_area_km2 += results.total_area_km2
                all_results.errors.extend(results.errors)
                all_results.processing_time_seconds += results.processing_time_seconds

                # Rate limiting between districts
                if district != districts[-1]:
                    asyncio.sleep(self.config.rate_limit_delay)

            except Exception as e:
                logger.error(f"Failed to process district {district.name}: {e}")
                all_results.errors.append(f"District {district.name}: {e}")

        # Combine all DataFrames
        combined_df = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()

        return combined_df, all_results

    def _search_places_with_pagination(
        self,
        query: str,
        location: tuple[float, float],
        radius: int,
    ) -> list[dict]:
        """
        Search for places with pagination support (up to max_results_per_search).

        Args:
            query: Search query string
            location: (lat, lng) center point
            radius: Search radius in meters

        Returns:
            List of place results
        """
        results = []
        next_page_token = None

        while len(results) < self.config.max_results_per_search:
            # Check limits before making API call
            if not self._check_limits():
                logger.warning(f"Search stopped for '{query}': API limit reached")
                break

            try:
                self._record_api_call()
                response = self.gm.places(
                    query=query,
                    location=location,
                    radius=radius,
                    page_token=next_page_token,
                )

                if "results" in response:
                    results.extend(response["results"])
                    logger.debug(f"Query '{query}': found {len(response['results'])} results (total: {len(results)})")

                # Check for more pages
                next_page_token = response.get("next_page_token")
                if not next_page_token:
                    break

                # Google Maps requires a delay before using next_page_token
                import time
                time.sleep(2)

            except StopIteration:
                logger.warning(f"Search stopped for '{query}': hard limit reached")
                break
            except Exception as e:
                logger.warning(f"Search error for '{query}': {e}")
                break

        return results[:self.config.max_results_per_search]

    def _search_places_text(self, query: str, location: tuple[float, float] | None = None) -> list[dict]:
        """
        Search for places using text search (no radius limit).

        Text search can find results across a broader area than nearby search.
        Results are ranked by relevance, with optional location bias.

        Args:
            query: Search query string
            location: Optional (lat, lng) to bias results toward

        Returns:
            List of place results
        """
        results = []
        next_page_token = None

        while len(results) < self.config.max_results_per_search:
            # Check limits before making API call
            if not self._check_limits():
                logger.warning(f"Text search stopped for '{query}': API limit reached")
                break

            try:
                self._record_api_call()

                # Build search parameters
                params = {"query": query}
                if location:
                    # Use location bias to prioritize results near this point
                    # This doesn't restrict results to a radius, just ranks them
                    params["location"] = location
                    # Small radius just for ranking, not hard limit
                    params["radius"] = 100000  # 100km for ranking purposes

                response = self.gm.places(**params, page_token=next_page_token)

                if "results" in response:
                    results.extend(response["results"])
                    logger.debug(f"Text search '{query}': found {len(response['results'])} results (total: {len(results)})")

                # Check for more pages
                next_page_token = response.get("next_page_token")
                if not next_page_token:
                    break

                # Google Maps requires a delay before using next_page_token
                import time
                time.sleep(2)

            except StopIteration:
                logger.warning(f"Text search stopped for '{query}': hard limit reached")
                break
            except Exception as e:
                logger.warning(f"Text search error for '{query}': {e}")
                break

        return results[:self.config.max_results_per_search]

    def _calculate_area_from_geometry(self, geometry: dict) -> float | None:
        """
        Calculate area in square kilometers from geometry data.

        Uses viewport or bounds to estimate area. For more accurate results,
        polygon geometry would be needed but isn't typically available via Places API.

        Args:
            geometry: Google Maps geometry dict

        Returns:
            Area in km² or None if calculable
        """
        # Try viewport first (usually available)
        viewport = geometry.get("viewport")
        bounds = geometry.get("bounds")

        region = viewport or bounds
        if not region:
            return None

        northeast = region.get("northeast", {})
        southwest = region.get("southwest", {})

        lat_span = abs(northeast.get("lat", 0) - southwest.get("lat", 0))
        lng_span = abs(northeast.get("lng", 0) - southwest.get("lng", 0))

        if lat_span == 0 or lng_span == 0:
            return None

        # Approximate area calculation using Haversine-based estimation
        # 1 degree of latitude ≈ 111 km
        # 1 degree of longitude ≈ 111 km * cos(latitude in radians)
        center_lat = (northeast.get("lat", 0) + southwest.get("lat", 0)) / 2
        lng_km = lng_span * 111 * abs(math.cos(math.radians(center_lat))) if center_lat else lng_span * 111

        # Simplified: treat as rectangle
        area_km2 = lat_span * 111 * lng_km

        # Apply adjustment factor - viewport tends to overestimate
        # Tea gardens are roughly rectangular, so apply 0.4 adjustment
        return max(0.1, min(area_km2 * 0.4, 10.0))  # Clamp between 0.1 and 10 km²

    def _geocode_location(self, query: str) -> tuple[float, float] | None:
        """Convert a location query to coordinates."""
        try:
            geocode_result = self.gm.geocode(query)
            if geocode_result:
                location = geocode_result[0]["geometry"]["location"]
                return (location["lat"], location["lng"])
        except Exception as e:
            logger.error(f"Geocoding failed for '{query}': {e}")
        return None

    def _get_cache_path(self, place_id: str) -> Path:
        """Get cache file path for a place_id."""
        return self._cache_dir / f"{place_id}.json"

    def _load_from_cache(self, place_id: str) -> EstateGeometry | None:
        """Load geometry from cache if available."""
        cache_path = self._get_cache_path(place_id)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path) as f:
                data = json.load(f)
            return EstateGeometry(**data)
        except Exception:
            return None

    def _save_to_cache(self, place_id: str, geometry: EstateGeometry) -> None:
        """Save geometry to cache."""
        cache_path = self._get_cache_path(place_id)
        try:
            with open(cache_path, "w") as f:
                json.dump(geometry.__dict__, f, default=str)
        except Exception as e:
            logger.warning(f"Failed to cache {place_id}: {e}")

    def clear_cache(self) -> int:
        """Clear all cached geometry files. Returns count of files deleted."""
        count = 0
        for file in self._cache_dir.glob("*.json"):
            file.unlink()
            count += 1
        logger.info(f"Cleared {count} cached geometry files")
        return count


def create_extractor_from_config(
    api_key: str | None = None,
    min_area: float = 0.5,
    max_area: float = 3.0,
    workforce_multiplier: float = 25.0,
) -> GeospatialExtractor:
    """
    Factory function to create a GeospatialExtractor with custom parameters.

    Args:
        api_key: Google Maps API key (overrides env var)
        min_area: Minimum area threshold in km²
        max_area: Maximum area threshold in km²
        workforce_multiplier: Workers per km² for estimation

    Returns:
        Configured GeospatialExtractor instance
    """
    from config import GeospatialConfig

    config_kwargs = {}
    if api_key:
        config_kwargs["google_maps_api_key"] = api_key
    if min_area:
        config_kwargs["min_area_km2"] = min_area
    if max_area:
        config_kwargs["max_area_km2"] = max_area
    if workforce_multiplier:
        config_kwargs["workforce_multiplier"] = workforce_multiplier

    config = GeospatialConfig(**config_kwargs)
    return GeospatialExtractor(config=config)
