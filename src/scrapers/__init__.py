"""Scrapers for different data sources."""

from .discovery import AutoDiscoveryScraper, DiscoveryResult
from .tbi_portal import TBIPortalConfig, TBIPortalScraper

__all__ = ["AutoDiscoveryScraper", "DiscoveryResult", "TBIPortalConfig", "TBIPortalScraper"]
