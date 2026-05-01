"""Enhanced PDF parser focusing on table extraction."""

import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd
from pypdf import PdfReader

logger = logging.getLogger(__name__)

# Column name mappings for standardization
COLUMN_MAPPINGS = {
    # Name variations
    "estate_name": [
        "name", "estate", "garden", "tea garden", "tea estate",
        "estate name", "garden name", "property", "plantation"
    ],
    # Workforce variations
    "workforce_count": [
        "workforce", "staff", "workers", "employees", "strength",
        "labour", "labor", "no. of workers", "worker count",
        "staff count", "employment", "manpower"
    ],
    # Phone variations
    "primary_phone": [
        "phone", "mobile", "telephone", "tel", "contact",
        "contact number", "phone no", "mobile no", "phone number"
    ],
    # Contact person variations
    "contact_person": [
        "manager", "owner", "contact person", "in-charge",
        "in charge", "agent", "proprietor", "representative"
    ],
    # Location variations
    "location": [
        "location", "district", "area", "region", "place",
        "village", "city", "town", "address"
    ],
}


def parse_pdf_tables(file_path: str) -> pd.DataFrame:
    """
    Parse PDF file with focus on table extraction.

    Strategy:
    1. First try to extract tables using tabula-like detection
    2. If no tables found, fall back to text parsing
    3. Map columns to standard schema

    Args:
        file_path: Path to PDF file

    Returns:
        DataFrame with standardized columns
    """
    logger.info(f"Parsing PDF: {file_path}")

    reader = PdfReader(file_path)
    total_pages = len(reader.pages)
    logger.info(f"PDF has {total_pages} pages")

    # Try to extract tables from each page
    all_tables = []

    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text()
        if text:
            tables = _extract_tables_from_text(text, page_num)
            all_tables.extend(tables)

    if all_tables:
        logger.info(f"Found {len(all_tables)} table(s) in PDF")
        df = pd.concat(all_tables, ignore_index=True)
        # Map columns to standard schema
        df = map_columns(df)
        return df
    else:
        logger.warning("No tables found, falling back to text extraction")
        return _parse_text_fallback(reader)


def _extract_tables_from_text(text: str, page_num: int) -> list[pd.DataFrame]:
    """
    Extract table-like structures from plain text.

    This implements tabula-like logic without external dependency.
    """
    tables = []

    # Look for patterns that suggest a table:
    # - Multiple lines with similar spacing patterns
    # - Header-like rows followed by data rows
    lines = text.split('\n')

    # Find potential table rows (lines with multiple tab/delimiter separated values)
    potential_rows = []
    for line in lines:
        # Check if line looks like a table row
        if _looks_like_table_row(line):
            potential_rows.append(line)

    if len(potential_rows) > 2:  # Need at least header + 1 data row
        # Try to parse as table
        try:
            # Detect delimiter
            delimiter = _detect_delimiter(potential_rows[0])

            if delimiter:
                # Parse the rows
                data = []
                for row in potential_rows:
                    values = [v.strip() for v in row.split(delimiter) if v.strip()]
                    if len(values) > 1:  # At least 2 columns
                        data.append(values)

                if data and len(data) > 1:
                    # First row is likely header
                    headers = data[0]
                    rows = data[1:]

                    df = pd.DataFrame(rows, columns=headers)
                    df["_source_page"] = page_num
                    tables.append(df)
                    logger.debug(f"Extracted table from page {page_num} with {len(df)} rows")
        except Exception as e:
            logger.debug(f"Failed to parse table on page {page_num}: {e}")

    return tables


def _looks_like_table_row(line: str) -> bool:
    """Check if a line looks like a table row."""
    # Must have multiple values separated by delimiters
    # Common delimiters: tabs, multiple spaces, pipes, commas

    # Skip empty lines
    if not line.strip():
        return False

    # Skip lines that are too short
    if len(line.strip()) < 20:
        return False

    # Check for multiple tab/space separated values
    # or pipe/comma delimited values
    delimiters = ["\t", " | ", ",", "  "]  # tab, pipe-space, comma, double-space

    for delim in delimiters:
        parts = line.split(delim)
        if len(parts) >= 3:  # At least 3 columns
            # Check if parts look like data (not just random words)
            return True

    return False


def _detect_delimiter(row: str) -> str | None:
    """Detect the delimiter used in a table row."""
    # Count occurrences of each delimiter
    tab_count = row.count("\t")
    pipe_count = row.count(" | ")
    comma_count = row.count(",") - row.count(", ")  # Standalone commas

    if tab_count >= 2:
        return "\t"
    elif pipe_count >= 2:
        return " | "
    elif comma_count >= 2:
        return ","
    else:
        # Try multiple spaces
        parts = re.split(r"\s{2,}", row)
        if len(parts) >= 3:
            return r"\s{2,}"

    return None


def _parse_text_fallback(reader: PdfReader) -> pd.DataFrame:
    """
    Fallback text parsing when no tables are detected.

    This method extracts structured data using regex patterns.
    Records extracted this way are flagged for manual review.
    """
    records = []
    flag_for_review = True

    for page in reader.pages:
        text = page.extract_text()
        if text:
            # Look for patterns like:
            # "Garden Name - 30 workers - Phone: XXX"
            # "1. Garden Estate: 50 staff"

            # Pattern 1: Name - Number - Phone
            pattern1 = r'([A-Z][A-Za-z\s]+?(?:Tea Garden|T\.G\.|Estate))[^-]*?-?\s*(\d{2,3})\s*(?:workers|staff|employees)'
            matches = re.finditer(pattern1, text)

            for match in matches:
                records.append({
                    "estate_name": match.group(1).strip(),
                    "workforce_count": match.group(2),
                    "_needs_review": flag_for_review
                })

    if records:
        logger.warning(f"Extracted {len(records)} records from text (flagged for review)")
        return pd.DataFrame(records)
    else:
        logger.error("Could not extract any data from PDF")
        return pd.DataFrame()


def map_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Map source-specific column names to standard schema.

    Args:
        df: Input DataFrame with source columns

    Returns:
        DataFrame with standardized column names
    """
    if df.empty:
        return df

    # Create mapping dictionary
    column_map = {}
    source_columns = {col.lower().strip(): col for col in df.columns}

    for standard_name, variations in COLUMN_MAPPINGS.items():
        for variation in variations:
            if variation.lower() in source_columns:
                source_col = source_columns[variation.lower()]
                column_map[source_col] = standard_name
                break

    # Apply mapping
    if column_map:
        df = df.rename(columns=column_map)
        logger.debug(f"Mapped columns: {column_map}")

    # Add missing standard columns
    for col in ["estate_name", "workforce_count", "primary_phone", "contact_person"]:
        if col not in df.columns:
            df[col] = None

    # Ensure core columns exist
    if "estate_name" not in df.columns or df["estate_name"].isna().all():
        logger.warning("No estate_name column found - data may not be valid")

    return df


def extract_workforce(value: Any) -> int | None:
    """
    Extract workforce count from various string formats.

    Examples:
        "30" -> 30
        "30 workers" -> 30
        "Approx 30" -> 30
        "25-30" -> 27 (average)
    """
    if pd.isna(value):
        return None

    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None

    if isinstance(value, str):
        # Extract numbers
        match = re.search(r"(\d{2,3})", value.replace(",", ""))
        if match:
            return int(match.group(1))

        # Check for range like "25-30"
        range_match = re.search(r"(\d{2})\s*[-–to]\s*(\d{2})", value)
        if range_match:
            low, high = int(range_match.group(1)), int(range_match.group(2))
            return (low + high) // 2

    return None


def extract_phone(value: Any) -> str | None:
    """Extract phone number from various formats."""
    if pd.isna(value):
        return None

    if isinstance(value, str):
        # Extract digits
        digits = re.sub(r"\D", "", value)
        if len(digits) >= 10:
            return digits[-10:]  # Last 10 digits

    return str(value) if value else None
