# Tea Garden Data Manager

Unified pipeline for extracting, processing, and managing tea garden contact data across Assam, West Bengal, and Tripura.

## Quick Start

```bash
# Install dependencies
uv sync

# Process all source files into the database
uv run python src/run.py process

# Launch the TUI to browse, filter, and export
uv run python src/run.py tui

# Crawl the web to discover emails
uv run python src/run.py crawl
```

## Commands

| Command | Description |
|---------|-------------|
| `uv run python src/run.py init` | Initialize a fresh database |
| `uv run python src/run.py migrate` | Migrate data from the old schema |
| `uv run python src/run.py process` | Process all source files into DB |
| `uv run python src/run.py crawl` | Crawl the web for tea garden emails |
| `uv run python src/run.py tui` | Launch the interactive TUI |
| `uv run python src/run.py stats` | Show database statistics |
| `uv run python src/run.py export` | Export to XLSX (with filters) |
| `uv run python src/run.py run-all` | Run all steps: init → migrate → process → crawl |

## Data Sources

The system processes these files from `data/`:

| File | Type | Records | What it provides |
|------|------|---------|-----------------|
| `Tea Estates.xlsx` | XLSX | 173 | Dibrugarh estates with area in Bigha |
| `Tea Estates number required.xlsx` | XLSX | 84 | Dibrugarh estates with phone numbers |
| `Grower_Details_Report_TINSUKIA_pdf823(1).xlsx` | XLSX | 106 | Tinsukia small grower details |
| `email assam.dooars teaestate.xlsx` | XLSX | 138 | Email addresses for Assam & Dooars estates |
| `Tea-Directory-Assam.xls` | XLS | 45 | Tea Board Assam directory |
| `Tea Directory-Assam.pdf` | PDF | 2111 | Tea Board Assam directory (PDF) |
| `Tea Directory-West Bengal.pdf` | PDF | 1269 | Tea Board West Bengal directory |
| `Tripura Tea Gardens Tea Board.pdf` | PDF | — | Tripura tea gardens |

## Database Schema

The SQLite database (`tea_gardens.db`) stores gardens with these key fields:

| Field | Description |
|-------|-------------|
| `name` | Tea garden/estate name |
| `phone` | Contact phone number |
| `email` | Email address |
| `email_confidence` | Email confidence score (0–1) |
| `website` | Website URL |
| `address` | Full address |
| `pincode` | Postal code |
| `district` | District name |
| `state` | State (Assam, West Bengal, Tripura) |
| `area_hectares` / `area_bigha` | Estate area |
| `confidence_score` | Overall data quality (0–1) |
| `data_source` | Where this record came from |
| `data_freshness` | When data was collected |
| `google_url` | Google Maps link |
| `latitude` / `longitude` | GPS coordinates |

## TUI

Launch with `uv run python src/run.py tui`.

### Controls

| Key | Action |
|-----|--------|
| `/` | Focus search bar |
| `Enter` | View garden details |
| `E` | Export filtered results to XLSX |
| `R` | Refresh data |
| `F` | Toggle filter bar |
| `PageUp` / `PageDown` | Paginate through results |
| `Home` / `End` | Jump to first/last page |
| `Q` | Quit |

### Filtering

The filter bar lets you narrow by:
- **Free text search** — matches name, address, email, phone
- **District** — dropdown of all districts in DB
- **Source** — filter by data origin (e.g. Tea Board PDF, XLSX file)
- **Has Phone** — show only records with/without phone numbers
- **Has Email** — show only records with/without email addresses

## Export

Export from CLI or TUI:

```bash
# Export everything
uv run python src/run.py export --output output/all_gardens.xlsx

# Filter by district
uv run python src/run.py export --output output/dibrugarh.xlsx --district Dibrugarh

# Only gardens with email
uv run python src/run.py export --output output/with_email.xlsx --has-email

# Only gardens with phone from West Bengal
uv run python src/run.py export --output output/wb_phones.xlsx --state "West Bengal" --has-phone
```

The XLSX output includes three sheets:
- **Gardens** — all matching records
- **Summary** — total count, phone/email stats, average confidence
- **By District** — breakdown by district

## Email Crawler

The crawler searches Google and estate websites to find email addresses:

```bash
# Default: process all gardens missing emails, batch of 50
uv run python src/run.py crawl

# Smaller batches (slower but safer)
uv run python src/run.py crawl --batch-size 20 --min-confidence 0.3
```

For each garden without an email:
1. Searches Google for `"[garden name]" tea estate email contact`
2. Extracts emails from search results using regex
3. Scores confidence based on name-domain match and page content
4. Saves the best email above the minimum confidence threshold

The crawler uses `crawl4ai` (already a dependency). It logs all attempts in the `email_crawl_log` table.

## Project Structure

```
src/
├── run.py              # Unified CLI entry point
├── db_v2.py            # Database schema, queries, export
├── process_sources.py  # Process all source files into DB
├── email_crawler.py    # Web crawler for email discovery
├── migrate_db.py       # Migrate old schema data
├── tui/
│   ├── app.py          # Textual TUI application
│   └── patch_rich.py   # Windows encoding fix
├── main.py             # Legacy CLI (maps mode)
├── models.py           # Pydantic data models
├── pipeline.py         # Processing pipeline
├── parsers.py          # PDF/table parsing
├── config.py           # Configuration
└── scrapers/           # Web scrapers
```

## Dependencies

All managed via `uv`:

```
crawl4ai     — Web crawling (email discovery)
textual      — Terminal UI
pandas       — Data processing
openpyxl     — Excel read/write
pypdf        — PDF text extraction
xlrd         — Legacy XLS file reading
pydantic     — Data validation
```

## Configuration

For Google Maps scraping (optional, legacy mode), create `.env`:

```
GOOGLE_MAPS_API_KEY=your_key_here
```
