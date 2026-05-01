# Digital Data Gathering Possibilities (Desk-Based)

## Tier 1: Low Effort (No Coding Required - Copy & Paste / Simple Tools)

These methods rely on finding pre-built tables or using browser extensions.

### A. Google Sheets IMPORTHTML Function

| Attribute | Description |
|-----------|-------------|
| **What it does** | Pulls an entire HTML table directly from a specified webpage into a Google Sheet cell with one formula. |
| **How to use it** | Find any TBI page that displays data in a standard HTML table format (e.g., "Top 50 Producing Estates"). Paste the URL into the sheet and use: `=IMPORTHTML("URL_HERE", "table", N)` (where N is the table number on that page, starting at 1). |
| **Best For** | Quick extraction of a single, well-formatted list. |

### B. Web Scraper Extensions (Chrome/Firefox)

| Attribute | Description |
|-----------|-------------|
| **What it does** | You visually "click" on the data you want to extract (e.g., click on all Estate Names → Click on all Phone Numbers). The extension builds the scraping logic for you and exports it as a CSV file. |
| **How to use it** | Install an extension (like Web Scraper, Data Miner). Navigate to the TBI page. Open the extension, define your "Selector" (what data point you want), and run the scrape. |
| **Best For** | Complex tables where columns are not perfectly aligned or when data is spread across multiple sections of one long webpage. |

### C. PDF Conversion & Parsing

| Attribute | Description |
|-----------|-------------|
| **What it does** | Converts static, image-based data from TBI Annual Reports into editable spreadsheet cells. |
| **How to use it** | Upload the official TBI report (usually a massive PDF) to an online tool like Smallpdf, Adobe Acrobat Online, or Tabula. Tabula is excellent because it lets you draw a box around the table you want, and it extracts only that section. |
| **Best For** | Extracting data from official annual reports where the list might be buried deep inside an appendix. |

---

## Tier 2: Medium Effort (Requires Basic Scripting - Python Recommended)

These methods require installing a simple programming environment (like Anaconda/VS Code with Python installed).

### D. Targeted Web Scraping (BeautifulSoup + Pandas)

| Attribute | Description |
|-----------|-------------|
| **What it does** | This is the industry standard for structured scraping. You write code that tells the computer exactly where to look on the page's underlying HTML code. |
| **How to use it** | 1. Use Developer Tools (F12 in Chrome) → Inspect Element on the TBI page.<br>2. Identify the unique CSS class or ID surrounding the data you want (e.g., `<td class="estate-name">`).<br>3. Write a Python script using `requests` to fetch the page, and `BeautifulSoup` to find all elements matching that class.<br>4. Use `Pandas` to organize these findings into a clean DataFrame (which is essentially an Excel table). |
| **Best For** | When data is spread across multiple pages (pagination) or when you need to scrape specific attributes (e.g., only estates with "Tea" in the name AND a workforce > 30). |

### E. API Hunting (The Holy Grail)

| Attribute | Description |
|-----------|-------------|
| **What it does** | If TBI has an Application Programming Interface (API), this is the cleanest method. Instead of scraping HTML, you send a direct request to their server and ask for data in JSON format. |
| **How to use it** | Use tools like Postman or Python's `requests` library. You test different endpoints on the TBI website until you find one that returns structured data (JSON). You then tell your script: "Give me all records where workforce_size > 25 AND workforce_size < 50." |
| **Best For** | The most efficient, scalable method. If they have an API, this is the fastest way to get perfect data. |

---

## Tier 3: High Effort (Advanced Automation)

These methods simulate a human user interacting with the site.

### F. Headless Browser Scraping (Selenium)

| Attribute | Description |
|-----------|-------------|
| **What it does** | Instead of just reading the HTML code, Selenium launches a real browser instance in the background (a "headless" mode). This is necessary when data loads dynamically using JavaScript after the page initially loads. |
| **How to use it** | You write Python code that tells Selenium: "Go to TBI URL → Wait 5 seconds for JS to load → Click the 'Next Page' button → Extract all table rows → Repeat until no more pages." |
| **Best For** | Modern, complex websites where the data isn't visible in the initial HTML source code. |

---

## Summary Decision Tree: Which Method to Choose?

| If your TBI Page is... | Use This Tier/Method | Tool Recommendation | Effort Level |
|------------------------|---------------------|---------------------|--------------|
| Simple Table on One Page | Tier 1A (IMPORTHTML) | Google Sheets | ⋆ (Very Low) |
| Complex Table / Spread Across Sections | Tier 1B (Web Scraper Extension) | Web Scraper Chrome Extension | ⋆⋆ (Low) |
| Data Locked in a PDF Report | Tier 1C (PDF Parsing) | Tabula or Smallpdf | ⋆⋆ (Low-Medium) |
| Structured Data, but needs filtering/pagination | Tier 2D (BeautifulSoup/Pandas) | Python Script | ⋆⋆⋆ (Medium) |
| Data Loads via JavaScript (Dynamic) | Tier 2E (API Hunting) or Tier 3F (Selenium) | Postman / Selenium + Python | ⋆⋆⋆ to ⋆⋆⋆⋆ (Medium-High) |

---

# Automated Tea Garden Data Acquisition System Specification Document (ATGDAS)

## Project Goal

To build an end-to-end, autonomous system capable of sourcing, cleaning, standardizing, and compiling contact information for tea gardens in Assam meeting the criteria: **Workforce > 25 AND Workforce < 50**.

## Target Output

A single, master CSV/Excel file containing standardized fields.

---

## System Architecture Overview (The Pipeline)

The ATGDAS will operate as a multi-stage pipeline, where the output of one module feeds directly into the input of the next.

```
Data Sources → Ingestion Layer → Processing/Cleaning Layer → Standardization Layer → Output Layer
```

---

## Module 1: Data Ingestion Layer (The Collectors)

This layer is responsible for finding and pulling raw data from all available sources.

| Source Type | Required Technique | Key Deliverable | Notes/Dependencies |
|-------------|-------------------|-----------------|-------------------|
| TBI Portal | API Hunting / Headless Scraping (Selenium) | Raw JSON/HTML Data Set 1 | Must handle pagination and dynamic loading. Prioritize finding a direct REST API endpoint. |
| PDF Reports | Intelligent PDF Parsing (Tabula/PyPDF2) | Raw Table Data Set 2 | Needs to identify tables even if they span multiple pages within the document. |
| Web Listings (Google Maps/Directories) | Targeted Web Scraping (BeautifulSoup) | Raw List of Name + Phone Number Pairs (Set 3) | Requires scraping specific CSS selectors for phone numbers on listing cards. |
| Social Media (WhatsApp/FB Groups) | API Integration / Advanced NLP Parsing | Semi-Structured Text Data Set 4 | Needs to parse unstructured text replies into [Name], [Workforce Range] pairs. |

---

## Module 2: Processing & Cleaning Layer (The Filter)

This layer takes the raw, messy data and applies initial filtering rules.

### Core Functions

1. **Deduplication**: Identify and merge duplicate entries across all four datasets using a combination of Estate Name and Phone Number as primary keys.

2. **Noise Reduction**: Remove irrelevant entries (e.g., "Tea Dealer," "Supplier Office") that are not the main estate contact.

3. **Initial Filtering**: Apply hard constraints: Filter out any record where Workforce ≤ 25 OR Workforce ≥ 50.

---

## Module 3: Standardization Layer (The Refiner)

This is the "AI" component—it fixes inconsistencies and fills gaps.

### Core Functions

1. **Name Normalization**: Standardize estate names (e.g., converting "Brookfields Tea Garden," "B.F.T.G.," and "Brookfield" all to "Brookfields Tea Garden").

2. **Workforce Standardization**: Convert varied inputs ("~30 staff," "30+", "Approx 45") into a single integer format (e.g., 32, 38).

3. **Contact Enrichment (Gap Filling)**: If the phone number is missing, use the Estate Name to query Google Maps/LinkedIn API again for that specific name and pull the primary contact number.

---

## Module 4: Output Layer (The Deliverable)

This layer presents the final, usable product.

### Final Master Database Schema

| Field Name | Data Type | Description | Source Priority | Notes |
|------------|-----------|-------------|-----------------|-------|
| Estate_ID | Unique String | System-generated unique identifier. | System Generated | Primary Key for tracking lineage. |
| Estate_Name | String | Standardized, clean name of the garden. | Module 3 (Standardization) | Must be consistent across all records. |
| Workforce_Count | Integer | The verified employee count. | Module 2/3 (Filtering/Refining) | Must be between 26 and 49 inclusive. |
| Primary_Phone | String | Verified primary contact number. | Module 3 (Enrichment) | Standardized format: +91-XX-XXXXXXX. |
| Contact_Person | String | Name of the Estate Manager/Owner. | Module 2/3 (Cleaning/Refining) | If unknown, default to "Estate Management." |
| Source_Origin | String | Where this specific record came from. | Module 1 (Ingestion) | E.g., TBI_API, FB_Group_X, Vendor_Ledger. |

---

## Non-Negotiable Requirements (Zero Compromise Checklist)

- **Idempotency**: Running the script twice with the same inputs must yield the exact same final output file without creating duplicate records.

- **Error Logging**: The system must log every failure: API timeouts, parsing errors, failed deduplication attempts, and data points that fail the 25-50 filter.

- **Human Review Queue**: A dedicated section in the final CSV must flag records where Source_Origin is ambiguous or where the Workforce_Count was inferred (e.g., "Inferred from Vendor Ledger").
