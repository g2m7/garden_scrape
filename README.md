# Tea Garden Scraper - Automated Data Acquisition System

End-to-end pipeline for extracting, cleaning, and standardizing tea garden data from multiple sources.

## Features

- **Local file ingestion**: PDF, CSV, Excel files
- **Web scraping**: With automatic authentication detection and fallback
- **Geospatial extraction**: Google Maps API integration for estate discovery
- **Visual verification**: Automatic satellite imagery capture
- **Schema standardization**: Auto-maps varied column names to standard schema
- **Workforce filtering**: Configurable range (default: 26-49 workers)
- **Deduplication**: Removes duplicates based on name + phone
- **Export formats**: CSV, Excel (with summary sheet)

## Installation

```bash
# Install dependencies
uv sync

# Or with pip
pip install crawl4ai pypdf pydantic pandas openpyxl googlemaps shapely selenium python-dotenv
```

## Configuration

Create a `.env` file in the project root:

```bash
# Required for maps mode
GOOGLE_MAPS_API_KEY=your_api_key_here
```

Get a Google Maps API key from: https://developers.google.com/maps/documentation/places/web-service/get-api-key

## Usage

### Local File Mode

```bash
# CSV file
python src/main.py --mode=local --source-file=data/gardens.csv --output=results.csv

# PDF file
python src/main.py --mode=local --source-file=data/report.pdf --output=results.xlsx
```

### Web Scraping Mode

```bash
# Scrape specific URLs
python src/main.py --mode=web --urls=https://example.com/gardens --output=results.csv
```

### Geospatial Maps Mode (New)

Search for tea gardens using Google Maps API:

```bash
# Search specific districts
python src/main.py --mode=maps --districts="Dibrugarh,Jorhat,Tinsukia" --output=geospatial_master.csv

# Search all districts
python src/main.py --mode=maps --districts="all" --output=geospatial_master.csv

# With custom area thresholds
python src/main.py --mode=maps --districts="Dibrugarh" --min-area=0.3 --max-area=5.0 --output=results.csv

# Without screenshots (faster)
python src/main.py --mode=maps --districts="Dibrugarh" --no-screenshots --output=results.csv
```

**Simple runner script:**
```bash
python src/run_maps.py
```

### Auto Mode (Detects Source Type)

```bash
python src/main.py --source-file=data/gardens.csv --output=results.csv
```

### Advanced Options

```bash
python src/main.py \
  --mode=local \
  --source-file=data/gardens.csv \
  --output=results.xlsx \
  --format=excel \
  --min-workforce=26 \
  --max-workforce=49 \
  --verbose
```

## Command Line Arguments

| Argument | Description |
|----------|-------------|
| `--mode` | `local`, `web`, `auto`, or `maps` (default: auto) |
| `--source-file` | Path to local file (PDF, CSV, Excel) |
| `--urls` | URLs to scrape (space-separated) |
| `--fallback-file` | Local file if web scraping fails |
| `--output` | Output file path (default: output/tea_gardens.csv) |
| `--format` | `csv`, `excel`, or `both` (default: csv) |
| `--min-workforce` | Minimum workforce (default: 26) |
| `--max-workforce` | Maximum workforce (default: 49) |
| `--verbose` | Enable verbose logging |
| **Maps Mode Arguments** | |
| `--districts` | Comma-separated district names or `all` |
| `--api-key` | Google Maps API key (overrides env var) |
| `--min-area` | Minimum estate area in km² (default: 0.5) |
| `--max-area` | Maximum estate area in km² (default: 3.0) |
| `--workforce-multiplier` | Workers per km² (default: 25.0) |
| `--no-screenshots` | Disable visual verification screenshots |
| `--clear-cache` | Clear cached geometry data |

## Input Schema

The system auto-maps these column variations:

| Standard Field | Recognized As |
|----------------|---------------|
| `estate_name` | Name, Estate, Garden, Tea Garden, Property, Plantation |
| `workforce_count` | Workforce, Staff, Workers, Employees, Strength, Labour |
| `primary_phone` | Phone, Mobile, Telephone, Contact, Phone Number |
| `contact_person` | Manager, Owner, Contact Person, In-Charge, Agent |

## Output Schema

| Field | Description |
|-------|-------------|
| `estate_id` | Unique identifier (UUID) |
| `estate_name` | Standardized garden name |
| `workforce_count` | Verified worker count |
| `primary_phone` | Formatted phone number |
| `contact_person` | Manager/Owner name |
| `source_origin` | Data source identifier |
| `is_inferred` | Whether data was inferred |
| `latitude` | Estate latitude (maps mode) |
| `longitude` | Estate longitude (maps mode) |
| `area_km2` | Physical area in km² (maps mode) |
| `place_id` | Google Maps place_id (maps mode) |
| `address` | Formatted address (maps mode) |
| `visual_proof` | Screenshot path (if enabled) |
| `verification_status` | `verified`, `inferred`, or `pending` |

## Project Structure

```
src/
├── main.py                 # CLI entry point
├── models.py               # Pydantic models
├── pipeline.py             # Processing pipeline
├── ingestion.py            # File/web ingestion
├── parsers.py              # PDF/table parsing
├── config.py               # Configuration management
├── geospatial_extractor.py # Google Maps integration
├── visual_check.py         # Screenshot verification
├── run_maps.py             # Maps mode runner script
└── scrapers/               # Web scrapers
```

## Supported Districts (Assam)

The following districts are pre-configured for geospatial searches:

| District | Center (Lat, Lng) | Radius (km) |
|----------|-------------------|-------------|
| Dibrugarh | 27.4844°N, 94.9112°E | 50 |
| Jorhat | 26.7396°N, 94.2038°E | 45 |
| Tinsukia | 27.4934°N, 95.3560°E | 55 |
| Sivasagar | 26.9833°N, 94.6333°E | 40 |
| Golaghat | 26.5167°N, 93.9667°E | 45 |
| Kamrup | 26.1167°N, 91.5833°E | 50 |
| Sonitpur | 26.6167°N, 92.9167°E | 55 |
| Cachar | 24.8833°N, 92.7833°E | 50 |
| Nagaon | 26.3500°N, 92.6833°E | 45 |
| Lakhimpur | 27.2333°N, 94.1000°E | 50 |

## Geospatial Features

### Area-Based Workforce Estimation

The system estimates workforce from physical estate area:
```
Estimated Workers = Area_KM² × Workforce_Multiplier (default: 25)
```

### Visual Verification

When enabled (`--no-screenshots` flag omitted), the system:
1. Opens Google Maps at estate coordinates
2. Switches to satellite view
3. Captures screenshot of the area
4. Saves to `output/screenshots/`

Screenshots are stored for manual verification of estate boundaries.

## Example Output

The Excel output includes two sheets:
- **Validated_Gardens**: Filtered, standardized records
- **Summary**: Statistics (total records, unique gardens, with phone, inferred count)
