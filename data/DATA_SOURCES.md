# Data Source Tracking

## Source Files (`data/`)

| # | File | Type | Records | Status | Notes |
|---|------|------|---------|--------|-------|
| 1 | `Tea Estates.xlsx` | XLSX | 172 | **Processed** | Dibrugarh district estates with area (Bigha). Area converted to hectares. |
| 2 | `Tea Estates number required.xlsx` | XLSX | 84 | **Processed** | Dibrugarh estates with phone numbers (scientific notation floats). 58 unique phones extracted. |
| 3 | `tea_estate_contacts.xlsx` | XLSX | — | **Output** | Generated output from `scrape_gm.py` (Google Maps v1). Not a source file. |
| 4 | `tea_estate_contacts_v2.xlsx` | XLSX | — | **Output** | Generated output from `scrape_v2.py`. Not a source file. |
| 5 | `Grower_Details_Report_TINSUKIA_pdf823(1).xlsx` | XLSX | 105 | **Processed** | Tinsukia district small grower details: name, garden, area (Ha), community, gender. |
| 6 | `email assam.dooars teaestate.xlsx` | XLSX | 138 | **Processed** | Email list for Assam & Dooars tea estates. 138 unique emails extracted and linked. |
| 7 | `Tea Directory-Assam.pdf` | PDF | 2111 | **Processed** | Tea Board directory for Assam. PDF table extraction with regex. Major source. |
| 8 | `Tea Directory-West Bengal.pdf` | PDF | 1269 | **Processed** | Tea Board directory for West Bengal (includes Dooars). PDF table extraction. |
| 9 | `Tripura Tea Gardens Tea Board.pdf` | PDF | 0 | **Processed** | PDF structure didn't match expected patterns. No estates extracted. |
| 10 | `Tea-Directory-Assam.xls` | XLS | 45 | **Processed** | Assam tea directory in legacy XLS format. 45 estates with structured column data. |
| 11 | `test_gardens.csv` | CSV | — | **Test Data** | Sample data used for pipeline testing. Not real source data. |

## Non-File Sources (Scraped)

| Source | Method | Records | Status | Notes |
|--------|--------|---------|--------|-------|
| Google Maps (pincode sweep) | `run_pincode.py` | 538 gardens | **Processed** | 10 Assam districts, 87 with phones. **Data lost in schema migration** — needs re-scrape. |
| Wikipedia (List of tea gardens in Assam) | `run_wiki.py` | TBD | **Processed** | Garden names only, no workforce data. Output: `output/wikipedia_gardens.txt`. |
| Tea Board website (teaboard.gov.in) | `save_tbi.py` | N/A | **Partial** | Page saved but no structured data extracted. Auth-gated garden directory. |

## Database (`tea_gardens.db`) — New Schema v2

**Total:** 3841 gardens | **With phone:** 58 | **With email:** 2010 | **Avg confidence:** 0.194

### New Schema Features
- `email`, `email_confidence` — email addresses with confidence scoring
- `confidence_score` — overall data quality (0–1)
- `data_source` — where each record came from (comma-separated for merged records)
- `data_freshness` — when data was collected
- `state` — supports Assam, West Bengal, Tripura
- `website` — for future website crawling
- `data_provenance` — tracks field-level data lineage
- `email_crawl_log` — tracks email discovery attempts
- `source_files` — tracks processing status of each file

### By State
| State | Gardens |
|-------|---------|
| Assam | 2488 |
| West Bengal | 1269 |
| Tripura | 0 |

### By District (top)
| District | Gardens |
|----------|---------|
| Dibrugarh | 173 |
| Tinsukia | 105 |
| Dooars | 5 |

## Processing Pipeline

```
Source files ──> process_sources.py ──> db_v2.py (upsert_garden)
                       │                      │
                       ├─ XLSX/XLS parsing    ├─ Deduplication (name + pincode + district)
                       ├─ PDF text extraction  ├─ Phone normalization
                       ├─ Email extraction     ├─ Confidence scoring
                       └─ Area conversion      └─ Provenance tracking

Email crawl ──> email_crawler.py ──> crawl4ai ──> Google search ──> db_v2.py
                       │
                       ├─ Search "[garden name] tea estate email"
                       ├─ Extract emails with regex
                       ├─ Score confidence (name-domain match)
                       └─ Update gardens table

TUI ──> tui/app.py ──> Textual TUI
          │
          ├─ Filter by: district, state, source, phone, email, search
          ├─ View garden details
          ├─ Export filtered results to XLSX
          └─ Pagination (PageUp/PageDown)
```

## Next Steps

- [ ] Re-scrape Google Maps pincode data (lost in migration)
- [ ] Run email crawler: `python src/run.py crawl`
- [ ] Fix Tripura PDF extraction
- [ ] Enrich districts for PDF-sourced records (most are missing district)
- [ ] Build phone number enrichment from Google Maps re-scrape
