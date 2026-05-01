"""Simple runner for geospatial extraction mode."""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Fix encoding for Windows
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    """Run geospatial extraction for Assam tea gardens."""
    # Import after path setup
    from config import ASSAM_DISTRICTS, GeospatialConfig
    from geospatial_extractor import GeospatialExtractor
    from visual_check import VisualVerifier, add_visual_proof_column
    from pipeline import DataPipeline
    from parsers import map_columns

    # Configuration
    districts_to_process = ["Dibrugarh", "Jorhat", "Tinsukia"]  # Add more as needed
    min_workforce = 26
    max_workforce = 49
    output_file = "output/geospatial_master.csv"
    enable_screenshots = True

    print("=" * 60)
    print("Tea Garden Geospatial Extraction")
    print("=" * 60)
    print(f"Target Districts: {', '.join(districts_to_process)}")
    print(f"Workforce Range: {min_workforce} - {max_workforce}")
    print(f"Output: {output_file}")
    print(f"Screenshots: {'Enabled' if enable_screenshots else 'Disabled'}")
    print("=" * 60)

    try:
        # Initialize configuration
        config = GeospatialConfig(
            target_districts=districts_to_process,
            enable_screenshots=enable_screenshots,
        )

        # Initialize extractor
        extractor = GeospatialExtractor(config=config)

        # Get district configs
        target_districts = [ASSAM_DISTRICTS[d] for d in districts_to_process]

        # Process districts
        print("\nProcessing districts...")
        combined_df, results = extractor.process_multiple_districts(
            districts=target_districts,
            min_workforce=min_workforce,
            max_workforce=max_workforce,
        )

        if combined_df.empty:
            print("No estates found matching criteria.")
            return 1

        # Add required columns for pipeline compatibility
        combined_df["workforce_count"] = combined_df["estimated_workforce"]
        combined_df["primary_phone"] = "Unknown"
        combined_df["contact_person"] = None

        # Optional: Capture screenshots for visual verification
        if enable_screenshots:
            print("\nCapturing visual verification screenshots...")
            verifier = VisualVerifier(config=config, headless=True)

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

                captured = sum(1 for r in verification_results if r.screenshot_path)
                print(f"  Screenshots captured: {captured}/{len(verification_results)}")

            finally:
                verifier.close()

        # Process through standard pipeline
        print("\nProcessing through standardization pipeline...")
        combined_df = map_columns(combined_df)
        pipeline = DataPipeline(min_workforce=min_workforce, max_workforce=max_workforce)
        standardized, errors = pipeline.process_dataframe(combined_df)

        # Export results
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        pipeline.export_to_csv(standardized, output_file)

        # Summary
        print("\n" + "=" * 60)
        print("EXTRACTION COMPLETE")
        print("=" * 60)
        print(f"Estates found: {results.estates_found}")
        print(f"Estates with geometry: {results.estates_with_geometry}")
        print(f"Estates meeting criteria: {results.estates_meeting_criteria}")
        print(f"Total area covered: {results.total_area_km2:.2f} km²")
        print(f"Processing time: {results.processing_time_seconds:.1f} seconds")
        print(f"\nExported to: {output_file}")

        # Show sample results
        if standardized:
            print("\nSample Results:")
            for garden in standardized[:5]:
                loc_str = f" ({garden.latitude:.4f}, {garden.longitude:.4f})" if garden.latitude else ""
                print(f"  - {garden.estate_name}: {garden.workforce_count} workers{loc_str}")

        return 0

    except Exception as e:
        logger.error(f"Geospatial extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
