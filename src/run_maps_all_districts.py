"""Runner for geospatial extraction across ALL Assam districts with district-wise outputs."""

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
    """Run geospatial extraction for ALL Assam tea gardens with district-wise outputs."""
    # Import after path setup
    from config import ASSAM_DISTRICTS, GeospatialConfig
    from geospatial_extractor import GeospatialExtractor
    from visual_check import VisualVerifier, add_visual_proof_column
    from pipeline import DataPipeline
    from parsers import map_columns

    # Configuration - Process ALL districts (no workforce filter initially)
    all_districts = list(ASSAM_DISTRICTS.keys())
    min_workforce = None  # No minimum filter
    max_workforce = None  # No maximum filter
    enable_screenshots = False  # Disable to save API calls
    output_dir = Path("output/district_wise")
    enable_screenshots = True

    print("=" * 70)
    print("Tea Garden Geospatial Extraction - ALL ASSAM DISTRICTS")
    print("=" * 70)
    print(f"Target Districts: {', '.join(all_districts)} ({len(all_districts)} total)")
    print(f"Workforce Range: {min_workforce} - {max_workforce}")
    print(f"Output Directory: {output_dir}")
    print(f"Screenshots: {'Enabled' if enable_screenshots else 'Disabled'}")
    print("=" * 70)

    try:
        # Initialize configuration
        config = GeospatialConfig(
            target_districts=all_districts,
            enable_screenshots=enable_screenshots,
        )

        # Initialize extractor
        extractor = GeospatialExtractor(config=config)

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)

        # Process each district separately and collect all results
        print("\nProcessing districts...")
        all_results = []
        district_dfs = {}

        for district_name in all_districts:
            print(f"\n  Processing: {district_name}")
            
            # Get district config
            district_config = ASSAM_DISTRICTS[district_name]
            
            # Process this district
            combined_df, results = extractor.process_district(
                district=district_config,
                min_workforce=min_workforce,
                max_workforce=max_workforce,
            )

            if not combined_df.empty:
                # Add required columns for pipeline compatibility
                combined_df["workforce_count"] = combined_df["estimated_workforce"]
                combined_df["primary_phone"] = "Unknown"
                combined_df["contact_person"] = None
                
                # Process through standardization pipeline
                combined_df = map_columns(combined_df)
                pipeline = DataPipeline(min_workforce=min_workforce, max_workforce=max_workforce)
                standardized, errors = pipeline.process_dataframe(combined_df)

                if standardized:
                    district_dfs[district_name] = standardized
                    
                    # Optional: Capture screenshots for visual verification
                    if enable_screenshots and len(standardized) > 0:
                        print(f"    Capturing {len(standardized)} screenshots...")
                        verifier = VisualVerifier(config=config, headless=True)

                        try:
                            estates_to_verify = standardized[
                                ["estate_name", "latitude", "longitude"]
                            ].to_dict("records")

                            verification_results = verifier.batch_capture(
                                estates=estates_to_verify,
                                zoom_level=16,
                                delay_seconds=0.5,
                            )

                            # Add screenshot paths to DataFrame
                            standardized = add_visual_proof_column(standardized, verification_results)

                            captured = sum(1 for r in verification_results if r.screenshot_path)
                            print(f"    Screenshots captured: {captured}/{len(verification_results)}")

                        finally:
                            verifier.close()

                    # Export district-wise CSV
                    output_file = output_dir / f"{district_name}_gardens.csv"
                    standardized.to_csv(output_file, index=False)
                    print(f"    ✓ Saved: {output_file} ({len(standardized)} estates)")

            all_results.append(results)

        # Summary statistics
        total_estates = sum(len(df) for df in district_dfs.values())
        
        print("\n" + "=" * 70)
        print("EXTRACTION COMPLETE - SUMMARY")
        print("=" * 70)
        print(f"\nDistricts Processed: {len(all_districts)}")
        print(f"Total Estates Found: {total_estates}")
        
        # Show per-district breakdown
        print("\nPer-District Breakdown:")
        for district_name, df in sorted(district_dfs.items(), key=lambda x: len(x[1]), reverse=True):
            if len(df) > 0:
                print(f"  {district_name}: {len(df)} estates")

        # Export combined master file
        combined_output = output_dir / "all_districts_master.csv"
        if district_dfs:
            import pandas as pd
            master_df = pd.concat(district_dfs.values(), ignore_index=True)
            master_df.to_csv(combined_output, index=False)
            print(f"\n✓ Combined Master File: {combined_output} ({len(master_df)} total estates)")

        # Show sample results from largest district
        if district_dfs:
            largest_district = max(district_dfs.items(), key=lambda x: len(x[1]))
            print(f"\nSample Results from {largest_district[0]}:")
            for garden in largest_district[1][:3]:
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
