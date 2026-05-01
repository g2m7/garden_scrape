import logging
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from db_v2 import init_db, upsert_garden, upsert_source_file

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')


def _extract_emails(text: str) -> list[str]:
    if not text or not isinstance(text, str):
        return []
    return list(set(m.group(0).lower() for m in EMAIL_RE.finditer(text)))


def _bigha_to_hectares(bigha: float) -> float:
    return bigha * 0.1338


def process_tea_estates_xlsx(conn) -> int:
    fpath = DATA_DIR / "Tea Estates.xlsx"
    if not fpath.exists():
        logger.warning(f"Missing: {fpath}")
        return 0

    df = pd.read_excel(fpath, header=None)
    count = 0

    header_row = None
    for idx, row in df.iterrows():
        vals = [str(v).strip().lower() for v in row if pd.notna(v)]
        if any("name" in v and ("estate" in v or "garden" in v or "dpe" in v) for v in vals):
            header_row = idx
            break

    if header_row is not None:
        df = pd.read_excel(fpath, header=header_row + 1) if header_row == 0 else pd.read_excel(fpath, skiprows=range(0, header_row + 1), header=0)
    else:
        df.columns = ["sl", "name", "garden_area", "factory_area", "total", "extra"]
        df = df.iloc[1:]

    for _, row in df.iterrows():
        name = None
        for col in row.index:
            cl = str(col).lower()
            if "name" in cl or "estate" in cl or "garden" in cl or "dpe" in cl:
                val = str(row[col]).strip() if pd.notna(row[col]) else None
                if val and val != "nan" and not val.replace(".", "").isdigit():
                    name = val
                    break

        if not name:
            first_val = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
            if not first_val.replace(".", "").isdigit():
                name = first_val

        if not name or name == "nan" or len(name) < 3:
            continue

        area_bigha = None
        area_hectares = None
        for col in row.index:
            col_lower = str(col).lower()
            if any(k in col_lower for k in ["area", "bigha", "size", "total", "garden"]):
                try:
                    val = row[col]
                    if pd.notna(val) and str(val).strip().upper() != "NIL":
                        fval = float(str(val).replace(",", "").strip())
                        if fval > 0:
                            if "total" in col_lower:
                                if area_bigha is None:
                                    area_bigha = fval
                                    area_hectares = _bigha_to_hectares(fval)
                            else:
                                area_bigha = fval
                                area_hectares = _bigha_to_hectares(fval)
                except (ValueError, TypeError):
                    pass

        data = {
            "name": name,
            "district": "Dibrugarh",
            "state": "Assam",
            "area_bigha": area_bigha,
            "area_hectares": area_hectares,
            "data_source": "Tea Estates.xlsx",
            "data_freshness": "2025-01-01",
            "_source_file": str(fpath.name),
        }

        result = upsert_garden(conn, data)
        if result:
            count += 1

    upsert_source_file(conn, "Tea Estates.xlsx", "xlsx", count, "Processed",
                       f"Dibrugarh estates with area")
    return count


def process_tea_estates_numbers_xlsx(conn) -> int:
    fpath = DATA_DIR / "Tea Estates number required.xlsx"
    if not fpath.exists():
        logger.warning(f"Missing: {fpath}")
        return 0

    df = pd.read_excel(fpath, header=None)

    header_idx = None
    for idx, row in df.iterrows():
        vals = [str(v).strip().lower() for v in row if pd.notna(v)]
        if any("name" in v and ("estate" in v or "dpe" in v) for v in vals):
            header_idx = idx
            break

    if header_idx is not None:
        df = pd.read_excel(fpath, skiprows=range(0, header_idx + 1), header=None)

    count = 0
    for _, row in df.iterrows():
        name = None
        phone = None

        for val in row:
            if pd.isna(val):
                continue

            if isinstance(val, (int, float)):
                clean = str(int(val)) if val == int(val) else f"{val:.0f}"
                if len(clean) >= 10:
                    phone = clean[-10:]
                continue

            s = str(val).strip()
            if not s or s == "nan":
                continue

            digits = re.sub(r'\D', '', s)
            if len(digits) >= 10:
                phone = digits[-10:]
            elif not name and not s.replace(".", "").replace(",", "").replace("-", "").isdigit():
                if len(s) > 3 and len(s) < 80:
                    name = s

        if not name or name == "nan":
            continue

        data = {
            "name": name,
            "district": "Dibrugarh",
            "state": "Assam",
            "phone": phone,
            "data_source": "Tea Estates number required.xlsx",
            "data_freshness": "2025-01-01",
            "_source_file": str(fpath.name),
        }

        result = upsert_garden(conn, data)
        if result:
            count += 1

    upsert_source_file(conn, "Tea Estates number required.xlsx", "xlsx", count, "Processed",
                       "Dibrugarh estates with phone numbers")
    return count


def process_tinsukia_growers_xlsx(conn) -> int:
    fpath = DATA_DIR / "Grower_Details_Report_TINSUKIA_pdf823(1).xlsx"
    if not fpath.exists():
        logger.warning(f"Missing: {fpath}")
        return 0

    df = pd.read_excel(fpath)
    count = 0

    for _, row in df.iterrows():
        name = None
        garden_name = None

        for col in row.index:
            col_lower = str(col).lower()
            if "name" in col_lower and "garden" not in col_lower:
                if pd.notna(row[col]):
                    name = str(row[col]).strip()
            if "garden" in col_lower or "estate" in col_lower:
                if pd.notna(row[col]):
                    garden_name = str(row[col]).strip()

        estate_name = garden_name or name
        if not estate_name or estate_name == "nan":
            continue

        data = {
            "name": estate_name,
            "district": "Tinsukia",
            "state": "Assam",
            "data_source": "Grower_Details_Report_TINSUKIA",
            "data_freshness": "2025-01-01",
            "_source_file": str(fpath.name),
        }

        for col in row.index:
            col_lower = str(col).lower()
            if "area" in col_lower and ("ha" in col_lower or "hectar" in col_lower):
                try:
                    val = float(row[col])
                    if val > 0:
                        data["area_hectares"] = val
                except (ValueError, TypeError):
                    pass
            if "phone" in col_lower or "mobile" in col_lower or "contact" in col_lower:
                phone = str(row[col]).strip() if pd.notna(row[col]) else None
                if phone and phone != "nan":
                    data["phone"] = phone
            if any(k in col_lower for k in ["community", "gender", "category"]):
                val = str(row[col]).strip() if pd.notna(row[col]) else None
                if val and val != "nan":
                    if not data.get("category"):
                        data["category"] = f"small_grower ({val})"

        result = upsert_garden(conn, data)
        if result:
            count += 1

    upsert_source_file(conn, "Grower_Details_Report_TINSUKIA_pdf823(1).xlsx", "xlsx", count, "Processed",
                       "Tinsukia small grower details")
    return count


def process_email_assam_dooars_xlsx(conn) -> int:
    fpath = DATA_DIR / "email assam.dooars teaestate.xlsx"
    if not fpath.exists():
        logger.warning(f"Missing: {fpath}")
        return 0

    df = pd.read_excel(fpath, header=None)
    count = 0

    emails_found = set()
    for _, row in df.iterrows():
        for val in row:
            if pd.notna(val):
                text = str(val).strip()
                emails = _extract_emails(text)
                for email in emails:
                    if email not in emails_found:
                        emails_found.add(email)

    for email in sorted(emails_found):
        domain = email.split("@")[1] if "@" in email else ""
        name_part = domain.split(".")[0].replace("-", " ").title()

        data = {
            "name": f"Tea Estate ({email})",
            "email": email,
            "email_confidence": 0.8,
            "data_source": "email_assam_dooars_list",
            "data_freshness": "2025-01-01",
            "state": "Assam",
            "_source_file": str(fpath.name),
        }

        if any(k in email.lower() for k in ["dooars", "doars", "bengal"]):
            data["state"] = "West Bengal"
            data["district"] = "Dooars"

        result = upsert_garden(conn, data)
        if result:
            count += 1

    upsert_source_file(conn, "email assam.dooars teaestate.xlsx", "xlsx", count, "Processed",
                       f"Email list for Assam & Dooars tea estates. {len(emails_found)} unique emails extracted.")
    return count


def process_tea_directory_assam_xls(conn) -> int:
    fpath = DATA_DIR / "Tea-Directory-Assam.xls"
    if not fpath.exists():
        logger.warning(f"Missing: {fpath}")
        return 0

    import xlrd
    wb = xlrd.open_workbook(fpath)
    count = 0

    for sheet_name in wb.sheet_names():
        sheet = wb.sheet_by_name(sheet_name)
        if sheet.nrows < 2:
            continue

        headers = [str(sheet.cell_value(0, c)).strip().lower() for c in range(sheet.ncols)]

        for r in range(1, sheet.nrows):
            row_data = {}
            for c in range(sheet.ncols):
                val = sheet.cell_value(r, c)
                if val != '':
                    row_data[headers[c]] = val

            estate_name = None
            for key in row_data:
                if any(k in key for k in ["name", "estate", "garden"]):
                    estate_name = str(row_data[key]).strip()
                    break

            if not estate_name or estate_name == "nan":
                continue

            data = {
                "name": estate_name,
                "state": "Assam",
                "data_source": "Tea-Directory-Assam.xls",
                "data_freshness": "2025-01-01",
                "_source_file": str(fpath.name),
            }

            for key, val in row_data.items():
                if key and "district" in key and len(key) < 20:
                    dv = str(val).strip()
                    if _is_valid_estate_name(dv) and len(dv) < 30:
                        data["district"] = dv
                elif "phone" in key or "tel" in key:
                    data["phone"] = str(val).strip()
                elif "email" in key or "mail" in key:
                    emails = _extract_emails(str(val))
                    if emails:
                        data["email"] = emails[0]
                        data["email_confidence"] = 0.9
                elif "address" in key or "location" in key:
                    data["address"] = str(val).strip()
                elif "area" in key or "size" in key:
                    try:
                        data["area_hectares"] = float(val)
                    except (ValueError, TypeError):
                        pass
                elif "pin" in key or "pincode" in key:
                    data["pincode"] = str(int(val)) if isinstance(val, (int, float)) else str(val).strip()

            result = upsert_garden(conn, data)
            if result:
                count += 1

    upsert_source_file(conn, "Tea-Directory-Assam.xls", "xls", count, "Processed",
                       "Assam tea directory from Tea Board")
    return count


def _is_valid_estate_name(name: str) -> bool:
    if not name or len(name) < 5 or len(name) > 80:
        return False
    if name.isdigit():
        return False
    if any(k in name.lower() for k in ["fax :", "tel :", "e-mail :", "sl.", "no.", "www.", "http", "page", "revenue", "sub-division"]):
        return False
    if name.count(" ") > 15:
        return False
    if not re.search(r'[A-Za-z]', name):
        return False
    digits_ratio = sum(1 for c in name if c.isdigit()) / max(len(name), 1)
    if digits_ratio > 0.4:
        return False
    return True


def _parse_pdf_directory(conn, fpath: Path, state: str, source_name: str) -> int:
    from pypdf import PdfReader
    reader = PdfReader(str(fpath))
    count = 0

    for page in reader.pages:
        text = page.extract_text()
        if not text:
            continue

        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if len(line) < 5 or len(line) > 300:
                continue

            emails = _extract_emails(line)
            phones = re.findall(r'(?:\+91[-.\s]?|0)?(?:\d{5}[-.\s]?\d{5}|\d{10})', line)
            pincode = re.search(r'\b(\d{6})\b', line)

            estate_name = None

            name_patterns = [
                r'^(\d+\s+([A-Z][A-Za-z\s.&-]+(?:T\.?E\.?|Tea\s+Estate|Garden|Plantation|T\.?\s*G\.?)))',
                r'([A-Z][A-Za-z\s.&-]+(?:T\.?E\.?|Tea\s+Estate|Garden|Plantation))',
                r'([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\s+T\.?\s*E\.?)',
            ]
            for pat in name_patterns:
                m = re.search(pat, line)
                if m:
                    candidate = m.group(1).strip()
                    candidate = re.sub(r'^\d+\s+', '', candidate).strip()
                    if _is_valid_estate_name(candidate):
                        estate_name = candidate
                        break

            if not estate_name and emails:
                for email in emails:
                    domain = email.split("@")[0].replace(".", " ").replace("_", " ").title()
                    if _is_valid_estate_name(domain):
                        estate_name = f"{domain} Tea Estate"
                        break

            if not estate_name:
                continue

            estate_name = estate_name.strip(" .,;-")
            if not _is_valid_estate_name(estate_name):
                continue

            data = {
                "name": estate_name,
                "state": state,
                "data_source": source_name,
                "data_freshness": "2025-01-01",
                "_source_file": str(fpath.name),
            }

            if emails:
                data["email"] = emails[0]
                data["email_confidence"] = 0.85
            if phones:
                phone_str = phones[0].strip()
                if len(phone_str) >= 10:
                    data["phone"] = phone_str[-10:]
            if pincode:
                data["pincode"] = pincode.group(1)

            result = upsert_garden(conn, data)
            if result:
                count += 1

    upsert_source_file(conn, str(fpath.name), "pdf", count, "Processed",
                       f"Tea Board {state} directory - PDF extracted")
    return count


def process_tea_directory_assam_pdf(conn) -> int:
    fpath = DATA_DIR / "Tea Directory-Assam.pdf"
    if not fpath.exists():
        logger.warning(f"Missing: {fpath}")
        return 0
    return _parse_pdf_directory(conn, fpath, "Assam", "Tea Directory-Assam.pdf")


def process_tea_directory_wb_pdf(conn) -> int:
    fpath = DATA_DIR / "Tea Directory-West Bengal.pdf"
    if not fpath.exists():
        logger.warning(f"Missing: {fpath}")
        return 0
    return _parse_pdf_directory(conn, fpath, "West Bengal", "Tea Directory-West Bengal.pdf")


def process_tripura_pdf(conn) -> int:
    fpath = DATA_DIR / "Tripura Tea Gardens Tea Board.pdf"
    if not fpath.exists():
        logger.warning(f"Missing: {fpath}")
        return 0
    return _parse_pdf_directory(conn, fpath, "Tripura", "Tripura Tea Gardens Tea Board.pdf")


def process_all_sources() -> dict[str, int]:
    conn = init_db()
    results = {}

    processors = [
        ("Tea Estates.xlsx", process_tea_estates_xlsx),
        ("Tea Estates number required.xlsx", process_tea_estates_numbers_xlsx),
        ("Grower_Details_Report_TINSUKIA", process_tinsukia_growers_xlsx),
        ("email assam.dooars teaestate", process_email_assam_dooars_xlsx),
        ("Tea-Directory-Assam.xls", process_tea_directory_assam_xls),
        ("Tea Directory-Assam.pdf", process_tea_directory_assam_pdf),
        ("Tea Directory-West Bengal.pdf", process_tea_directory_wb_pdf),
        ("Tripura Tea Gardens Tea Board.pdf", process_tripura_pdf),
    ]

    for name, processor in processors:
        logger.info(f"Processing: {name}")
        try:
            count = processor(conn)
            results[name] = count
            logger.info(f"  -> {count} records")
        except Exception as e:
            logger.error(f"  -> FAILED: {e}")
            results[name] = f"ERROR: {e}"

    conn.close()
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    results = process_all_sources()
    print("\n=== Source Processing Results ===")
    for name, count in results.items():
        print(f"  {name}: {count}")
