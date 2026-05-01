# Data Source Tracking

## Source Files (`data/`)

| # | File | Type | Records | Status | Notes |
|---|------|------|---------|--------|-------|
| 1 | `Tea Estates.xlsx` | XLSX | 174 | **Processed** | Dibrugarh district estates with area (Bigha). Used as primary input for `scrape_gm.py` / `scrape_v2.py`. |
| 2 | `Tea Estates number required.xlsx` | XLSX | 84 | **Processed** | Dibrugarh estates with personal phone numbers. Used as phone source for GM scrapers. Includes phone numbers column. |
| 3 | `tea_estate_contacts.xlsx` | XLSX | 173 | **Output** | Generated output from `scrape_gm.py` (Google Maps v1). Not a source file. |
| 4 | `tea_estate_contacts_v2.xlsx` | XLSX | 222 | **Output** | Generated output from `scrape_v2.py` (fuzzy match + email extraction). Includes discovered estates. |
| 5 | `Grower_Details_Report_TINSUKIA_pdf823(1).xlsx` | XLSX | 106 | **Not Processed** | Tinsukia district small grower details: name, garden, area (Ha), community, gender. From Tea Board. |
| 6 | `email assam.dooars teaestate.xlsx` | XLSX | 149 | **Not Processed** | Email list for Assam & Dooars tea estates. Single column of email addresses. |
| 7 | `Tea Directory-Assam.pdf` | PDF | TBD | **Not Processed** | Tea Board directory for Assam. Needs PDF table extraction. |
| 8 | `Tea Directory-West Bengal.pdf` | PDF | TBD | **Not Processed** | Tea Board directory for West Bengal (includes Dooars). Needs PDF table extraction. |
| 9 | `Tripura Tea Gardens Tea Board.pdf` | PDF | TBD | **Not Processed** | Tea Board data for Tripura tea gardens. New source. |
| 10 | `Tea-Directory-Assam.xls` | XLS | TBD | **Not Processed** | Assam tea directory in legacy XLS format. Requires `xlrd` to read. |
| 11 | `test_gardens.csv` | CSV | 8 | **Test Data** | Sample data used for pipeline testing. Not real source data. |

## Non-File Sources (Scraped)

| Source | Method | Records | Status | Notes |
|--------|--------|---------|--------|-------|
| Google Maps (pincode sweep) | `run_pincode.py` | 538 gardens | **Processed** | 10 Assam districts, 87 with phones, 82 pincodes completed. Stored in `tea_gardens.db`. |
| Wikipedia (List of tea gardens in Assam) | `run_wiki.py` | TBD | **Processed** | Garden names only, no workforce data. Output: `output/wikipedia_gardens.txt`. |
| Tea Board website (teaboard.gov.in) | `save_tbi.py` | N/A | **Partial** | Page saved but no structured data extracted. Auth-gated garden directory. |

## Database (`tea_gardens.db`)

| District | Gardens |
|----------|---------|
| Sonitpur | 81 |
| Dibrugarh | 68 |
| Jorhat | 59 |
| Golaghat | 58 |
| Tinsukia | 58 |
| Nagaon | 55 |
| Sivasagar | 51 |
| Cachar | 41 |
| Kamrup | 40 |
| Lakhimpur | 27 |

**Total:** 538 gardens | **With phone:** 87 | **Pincodes completed:** 82

## Processing Pipeline

```
Source files ──> ingestion.py ──> parsers.py ──> pipeline.py ──> output/
                   │                │               │
                   ├─ PDF tables    ├─ map_columns  ├─ dedup
                   ├─ CSV           ├─ extract_phone├─ filter (workforce 26-49)
                   └─ XLSX/XLS      └─ extract_workforce └─ standardize
```

## Next Steps

- [ ] Process `Grower_Details_Report_TINSUKIA_pdf823(1).xlsx` — small growers in Tinsukia
- [ ] Process `email assam.dooars teaestate.xlsx` — enrich contacts with email data
- [ ] Extract tables from `Tea Directory-Assam.pdf`
- [ ] Extract tables from `Tea Directory-West Bengal.pdf`
- [ ] Extract tables from `Tripura Tea Gardens Tea Board.pdf`
- [ ] Process `Tea-Directory-Assam.xls` (install `xlrd` first)
- [ ] Merge new data into `tea_gardens.db`
