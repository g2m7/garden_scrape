"""Main CLI entry point for tea garden scraper."""

import argparse
import asyncio
import io
import json
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

# Patch rich to avoid encoding issues
import rich.console

original_print = rich.console.Console.print


def safe_print(self, *args, **kwargs):
    """Safe print that handles encoding errors."""
    try:
        return original_print(self, *args, **kwargs)
    except UnicodeEncodeError:
        pass


rich.console.Console.print = safe_print

# Import our modules
from config import ASSAM_DISTRICTS, DistrictConfig, GeospatialConfig, get_geospatial_config
from ingestion import batch_ingest, load_local_source, scrape_with_fallback
from parsers import map_columns
from pipeline import DataPipeline

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Default URLs to try for web scraping
DEFAULT_URLS = [
    "https://www.teaboard.gov.in/",
    "https://www.indiatea.org/",
]


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Tea Garden Data Acquisition System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Local file mode
  python main.py --mode=local --source-file=data/gardens.csv --output=master_list.csv

  # Local PDF mode
  python main.py --mode=local --source-file=data/report.pdf --output=master_list.xlsx

  # Web scraping mode
  python main.py --mode=web --urls=https://example.com/gardens --output=results.csv

  # Auto mode (detects source type)
  python main.py --source-file=data/gardens.pdf --output=results.csv
        """,
    )

    parser.add_argument(
        "--mode",
        type=str,
        choices=["local", "web", "auto", "maps"],
        default="auto",
        help="Operation mode: local (file), web (scrape), auto (detect), or maps (Google Maps geospatial)",
    )

    parser.add_argument(
        "--source-file",
        type=str,
        help="Path to local data file (PDF, CSV, Excel)",
    )

    parser.add_argument(
        "--urls",
        type=str,
        nargs="+",
        help="URLs to scrape (for web mode)",
    )

    parser.add_argument(
        "--fallback-file",
        type=str,
        help="Local file to use if web scraping fails",
    )

    parser.add_argument(
        "--output",
        type=str,
        default="output/tea_gardens.csv",
        help="Output file path (CSV or Excel)",
    )

    parser.add_argument(
        "--min-workforce",
        type=int,
        default=26,
        help="Minimum workforce count (default: 26)",
    )

    parser.add_argument(
        "--max-workforce",
        type=int,
        default=49,
        help="Maximum workforce count (default: 49)",
    )

    parser.add_argument(
        "--format",
        type=str,
        choices=["csv", "excel", "both"],
        default="csv",
        help="Output format",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    # Maps mode arguments
    parser.add_argument(
        "--districts",
        type=str,
        help="Comma-separated district names for maps mode (e.g., 'Dibrugarh,Jorhat,Tinsukia' or 'all')",
    )

    parser.add_argument(
        "--api-key",
        type=str,
        help="Google Maps API key (overrides env var GOOGLE_MAPS_API_KEY)",
    )

    parser.add_argument(
        "--min-area",
        type=float,
        default=0.5,
        help="Minimum estate area in km² (default: 0.5)",
    )

    parser.add_argument(
        "--max-area",
        type=float,
        default=3.0,
        help="Maximum estate area in km² (default: 3.0)",
    )

    parser.add_argument(
        "--workforce-multiplier",
        type=float,
        default=25.0,
        help="Workers per km² for workforce estimation (default: 25.0)",
    )

    parser.add_argument(
        "--no-screenshots",
        action="store_true",
        help="Disable visual verification screenshots",
    )

    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear cached geometry data before processing",
    )

    # API Safety limit arguments
    parser.add_argument(
        "--max-api-calls",
        type=int,
        default=100,
        help="Maximum API calls allowed (default: 100 - for cost control)",
    )

    parser.add_argument(
        "--max-estates",
        type=int,
        default=50,
        help="Maximum estates to fetch details for (default: 50)",
    )

    return parser.parse_args()


async def run_local_mode(
    source_file: str,
    output_path: str,
    min_workforce: int,
    max_workforce: int,
    output_format: str,
) -> int:
    """Run in local file mode."""
    logger.info(f"Running in LOCAL mode")
    logger.info(f"Source: {source_file}")

    try:
        # Load local file
        df = load_local_source(source_file)

        # Map columns to standard schema
        df = map_columns(df)

        # Process through pipeline
        pipeline = DataPipeline(min_workforce=min_workforce, max_workforce=max_workforce)
        standardized, errors = pipeline.process_dataframe(df)

        # Export results
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if output_format in ["csv", "both"]:
            csv_path = output_path if output_path.endswith(".csv") else output_path.replace(".xlsx", ".csv")
            pipeline.export_to_csv(standardized, csv_path)

        if output_format in ["excel", "both"]:
            excel_path = (
                output_path if output_path.endswith(".xlsx") else output_path.replace(".csv", ".xlsx")
            )
            pipeline.export_to_excel(standardized, excel_path)

        # Log errors
        for error in errors:
            logger.warning(error)

        logger.info(f"✓ Processing complete: {len(standardized)} gardens exported")
        return 0

    except Exception as e:
        logger.error(f"✗ Local mode failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


async def run_web_mode(
    urls: list[str],
    output_path: str,
    fallback_file: str | None,
    min_workforce: int,
    max_workforce: int,
    output_format: str,
) -> int:
    """Run in web scraping mode."""
    logger.info(f"Running in WEB mode")
    logger.info(f"URLs: {urls}")

    all_data = []
    all_errors = []

    for url in urls:
        logger.info(f"Scraping: {url}")

        try:
            df, status = await scrape_with_fallback(url, fallback_file)

            if status == "SUCCESS" and not df.empty:
                logger.info(f"✓ Successfully scraped: {len(df)} records")
                all_data.append(df)
            elif status == "FALLBACK_SUCCESS":
                logger.info(f"✓ Used fallback file: {len(df)} records")
                all_data.append(df)
            else:
                logger.warning(f"✗ Failed: {status}")
                all_errors.append(f"{url}: {status}")

        except Exception as e:
            logger.error(f"✗ Error scraping {url}: {e}")
            all_errors.append(f"{url}: {e}")

    if not all_data:
        logger.error("No data extracted from any source")
        return 1

    # Combine all data
    combined_df = pd.concat(all_data, ignore_index=True)

    # Map columns and process
    combined_df = map_columns(combined_df)

    pipeline = DataPipeline(min_workforce=min_workforce, max_workforce=max_workforce)
    standardized, errors = pipeline.process_dataframe(combined_df)

    # Export results
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if output_format in ["csv", "both"]:
        csv_path = output_path if output_path.endswith(".csv") else output_path.replace(".xlsx", ".csv")
        pipeline.export_to_csv(standardized, csv_path)

    if output_format in ["excel", "both"]:
        excel_path = (
            output_path if output_path.endswith(".xlsx") else output_path.replace(".csv", ".xlsx")
        )
        pipeline.export_to_excel(standardized, excel_path)

    logger.info(f"✓ Processing complete: {len(standardized)} gardens exported")
    return 0


async def run_maps_mode(
    districts: str | None,
    output_path: str,
    min_workforce: int,
    max_workforce: int,
    output_format: str,
    api_key: str | None,
    min_area: float,
    max_area: float,
    workforce_multiplier: float,
    enable_screenshots: bool,
    clear_cache: bool,
    max_api_calls: int = 100,
    max_estates: int = 50,
) -> int:
    """Run in Google Maps geospatial mode."""
    logger.info("Running in MAPS (geospatial) mode")

    try:
        # Import geospatial modules
        from geospatial_extractor import GeospatialExtractor
        from visual_check import VisualVerifier, add_visual_proof_column

        # Configure geospatial settings
        config_kwargs = {
            "min_area_km2": min_area,
            "max_area_km2": max_area,
            "workforce_multiplier": workforce_multiplier,
            "enable_screenshots": enable_screenshots,
            "max_api_calls": max_api_calls,
            "max_estates_to_process": max_estates,
        }

        if api_key:
            config_kwargs["google_maps_api_key"] = api_key

        # Parse districts
        if districts:
            district_names = [d.strip() for d in districts.split(",")]
            config_kwargs["target_districts"] = district_names

        geo_config = GeospatialConfig(**config_kwargs)
        extractor = GeospatialExtractor(config=geo_config)

        # Display API safety limits prominently
        print("\n" + "=" * 60)
        print("API SAFETY LIMITS ENABLED")
        print("=" * 60)
        print(f"  Max API calls: {geo_config.max_api_calls}")
        print(f"  Max estates to process: {geo_config.max_estates_to_process}")
        print(f"  Hard stop on limit: {geo_config.hard_stop_on_limit}")
        print(f"  Results per search: {geo_config.max_results_per_search}")
        print("=" * 60 + "\n")

        # Clear cache if requested
        if clear_cache:
            logger.info("Clearing geometry cache...")
            extractor.clear_cache()

        # Get target districts
        target_districts = geo_config.get_districts()
        logger.info(f"Target districts: {[d.name for d in target_districts]}")

        # Process districts
        combined_df, results = extractor.process_multiple_districts(
            districts=target_districts,
            min_workforce=min_workforce,
            max_workforce=max_workforce,
        )

        if combined_df.empty:
            logger.warning("No estates found matching criteria")
            return 0

        logger.info(
            f"Geospatial extraction complete: "
            f"{results.estates_found} found, "
            f"{results.estates_skipped_no_phone} skipped (no phone), "
            f"{results.estates_with_geometry} with geometry, "
            f"{results.estates_meeting_criteria} meeting workforce criteria"
        )

        # Add required columns for pipeline compatibility
        combined_df["workforce_count"] = combined_df["estimated_workforce"]
        # Use phone from API if available, otherwise "Unknown" (but results with no phone are filtered earlier)
        combined_df["primary_phone"] = combined_df.get("phone", "Unknown")
        combined_df["contact_person"] = None

        # Optional: Capture screenshots for visual verification
        if enable_screenshots and not combined_df.empty:
            logger.info("Capturing visual verification screenshots...")
            verifier = VisualVerifier(config=geo_config, headless=True)

            try:
                estates_to_verify = combined_df[
                    ["estate_name", "latitude", "longitude"]
                ].to_dict("records")

                verification_results = verifier.batch_capture(
                    estates=estates_to_verify,
                    zoom_level=16,
                    delay_seconds=0.5,
                )

                # Add screenshot paths to DataFrame
                combined_df = add_visual_proof_column(combined_df, verification_results)

                logger.info(
                    f"Screenshots captured: "
                    f"{sum(1 for r in verification_results if r.screenshot_path)}/{len(verification_results)}"
                )

            finally:
                verifier.close()

        # Map columns and process through pipeline
        combined_df = map_columns(combined_df)
        pipeline = DataPipeline(min_workforce=min_workforce, max_workforce=max_workforce)
        standardized, errors = pipeline.process_dataframe(combined_df)

        # Export results
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if output_format in ["csv", "both"]:
            csv_path = output_path if output_path.endswith(".csv") else output_path.replace(".xlsx", ".csv")
            pipeline.export_to_csv(standardized, csv_path)

        if output_format in ["excel", "both"]:
            excel_path = (
                output_path if output_path.endswith(".xlsx") else output_path.replace(".csv", ".xlsx")
            )
            pipeline.export_to_excel(standardized, excel_path)

        # Log summary
        api_stats = extractor.get_api_stats()
        logger.info(f"✓ Maps mode complete: {len(standardized)} gardens exported")
        logger.info(f"  Total area covered: {results.total_area_km2:.2f} km²")

        # Display API usage
        print("\n" + "=" * 60)
        print("API USAGE SUMMARY")
        print("=" * 60)
        print(f"  API calls made: {api_stats['api_calls_made']}/{api_stats['api_calls_limit']}")
        print(f"  Estates processed: {api_stats['estates_processed']}/{api_stats['estates_limit']}")
        print(f"  Limit reached: {api_stats['limit_reached']}")
        print("=" * 60 + "\n")

        for error in errors:
            logger.warning(error)

        return 0

    except ImportError as e:
        logger.error(f"Missing dependencies for maps mode: {e}")
        logger.error("Install with: pip install googlemaps selenium shapely")
        return 1
    except Exception as e:
        logger.error(f"✗ Maps mode failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


async def run_auto_mode(
    source: str | None,
    output_path: str,
    min_workforce: int,
    max_workforce: int,
    output_format: str,
) -> int:
    """Run in auto mode - detect source type."""
    if source and Path(source).exists():
        # It's a file
        return await run_local_mode(source, output_path, min_workforce, max_workforce, output_format)
    elif source and source.startswith("http"):
        # It's a URL
        return await run_web_mode([source], output_path, None, min_workforce, max_workforce, output_format)
    else:
        logger.error("Cannot detect source type. Please specify --mode explicitly.")
        return 1


async def main():
    """Main entry point."""
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Determine mode
    mode: Literal["local", "web", "auto", "maps"] = args.mode

    if mode == "maps":
        exit_code = await run_maps_mode(
            districts=args.districts,
            output_path=args.output,
            min_workforce=args.min_workforce,
            max_workforce=args.max_workforce,
            output_format=args.format,
            api_key=args.api_key,
            min_area=args.min_area,
            max_area=args.max_area,
            workforce_multiplier=args.workforce_multiplier,
            enable_screenshots=not args.no_screenshots,
            clear_cache=args.clear_cache,
            max_api_calls=args.max_api_calls,
            max_estates=args.max_estates,
        )
    elif mode == "auto":
        exit_code = await run_auto_mode(
            args.source_file,
            args.output,
            args.min_workforce,
            args.max_workforce,
            args.format,
        )
    elif mode == "local":
        if not args.source_file:
            logger.error("--source-file is required for local mode")
            return 1
        exit_code = await run_local_mode(
            args.source_file,
            args.output,
            args.min_workforce,
            args.max_workforce,
            args.format,
        )
    elif mode == "web":
        urls = args.urls or DEFAULT_URLS
        exit_code = await run_web_mode(
            urls,
            args.output,
            args.fallback_file,
            args.min_workforce,
            args.max_workforce,
            args.format,
        )
    else:
        exit_code = 1

    return exit_code


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
