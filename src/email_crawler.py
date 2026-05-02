import asyncio
import io
import logging
import os
import re
import sys
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).parent))

os.environ["CRAWL4AI_DISABLE_LOGGING"] = "1"

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

SKIP_EMAIL_DOMAINS = {
    "example.com", "test.com", "email.com", "domain.com",
    "yourdomain.com", "company.com", "website.com",
    "sentry.io", "wixpress.com", "wordpress.com",
    "google.com", "facebook.com", "twitter.com", "instagram.com",
    "linkedin.com", "youtube.com", "wikipedia.org", "pinterest.com",
    "reddit.com", "quora.com", "medium.com", "github.com",
    "microsoft.com", "apple.com", "amazon.com", "cloudflare.com",
    "gravatar.com", "schema.org", "w3.org",
}

SKIP_EMAIL_LOCAL = {
    "noreply", "no-reply", "webmaster", "postmaster", "abuse",
    "admin@", "info@twitter", "hostmaster", "mailer-daemon",
}


def extract_emails(text: str) -> list[str]:
    if not text:
        return []
    found = []
    for m in EMAIL_RE.finditer(text):
        email = m.group(0).lower().rstrip(".")
        domain = email.split("@")[1] if "@" in email else ""
        local = email.split("@")[0] if "@" in email else ""

        skip = False
        if domain in SKIP_EMAIL_DOMAINS:
            skip = True
        for pattern in SKIP_EMAIL_LOCAL:
            if pattern in email:
                skip = True
        if email.endswith((".png", ".jpg", ".gif", ".svg", ".css", ".js", ".webp")):
            skip = True
        if len(email) > 60:
            skip = True
        if len(local) < 2:
            skip = True

        if not skip:
            found.append(email)
    return list(dict.fromkeys(found))


def score_email(email: str, garden_name: str, page_text: str) -> float:
    score = 0.3
    domain = email.split("@")[1] if "@" in email else ""
    local = email.split("@")[0] if "@" in email else ""

    name_lower = garden_name.lower()
    name_words = [w for w in re.split(r'[\s,.\-()&]+', name_lower) if len(w) > 2 and w not in (
        "tea", "estate", "garden", "pt", "pvt", "ltd", "private", "limited",
        "the", "and", "co", "company", "division", "group", "industries",
        "plantation", "associates", "enterprises",
    )]

    domain_clean = domain.replace(".com", "").replace(".in", "").replace(".org", "").replace(".net", "")
    for word in name_words:
        if word in domain_clean or word in local:
            score += 0.2
            break

    if domain.endswith(".in") and domain != "gmail.in":
        score += 0.1

    if any(k in domain for k in ("tea", "estate", "garden", "plantation", "tgi", "mcLeod")):
        score += 0.15

    if "gmail.com" in domain:
        tea_keywords = ["manager", "assistant", "tea", "estate", "garden", "plantation",
                        "sr.", "jr.", "md.", "office", "admin", "contact"]
        for kw in tea_keywords:
            if kw in local:
                score += 0.1
                break

    if garden_name.lower() in page_text.lower()[:2000]:
        score += 0.1

    return min(score, 1.0)


def extract_urls_from_serp(text: str) -> list[str]:
    if not text:
        return []
    urls = []
    skip_hosts = {
        "google.com", "google.co.in", "googleapis.com", "gstatic.com",
        "youtube.com", "accounts.google.com", "support.google.com",
        "maps.google.com", "play.google.com", "policies.google.com",
    }
    for m in re.finditer(r'\[([^\]]*)\]\((https?://[^)]+)\)', text):
        url = m.group(2)
        host = url.split("/")[2].split(":")[0] if len(url) > 8 else ""
        if any(d in host for d in skip_hosts):
            continue
        if "/url?q=" in url:
            try:
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(url).query)
                url = qs.get("q", [url])[0]
            except Exception:
                pass
        urls.append(url)
    return list(dict.fromkeys(urls))[:8]


def build_google_dork_urls(garden_name: str, district: str = "", state: str = "") -> list[str]:
    queries = [
        f'"{garden_name}" email contact',
        f'"{garden_name}" site:vakilsearch.com OR site:zaubacorp.com OR site:tofler.in OR site:indiacompanyinfo.com',
        f'"{garden_name}" {district} tea estate contact' if district else None,
        f'"{garden_name}" site:teaboard.gov.in' if "assam" in state.lower() else None,
    ]
    urls = []
    for q in queries:
        if q:
            urls.append(f"https://www.google.com/search?q={quote_plus(q)}&num=10&gl=in")
    return urls


async def crawl_for_emails(
    garden_name: str,
    garden_id: int,
    district: str = "",
    state: str = "Assam",
) -> list[dict[str, Any]]:
    from crawl4ai import AsyncWebCrawler, BrowserConfig

    results = []
    all_emails = {}
    collected_result_urls = []

    browser_config = BrowserConfig(headless=True, verbose=False)
    serp_urls = build_google_dork_urls(garden_name, district, state)

    null_out = io.StringIO()
    null_err = io.StringIO()

    async with AsyncWebCrawler(config=browser_config) as crawler:

        for url in serp_urls:
            try:
                with redirect_stdout(null_out), redirect_stderr(null_err):
                    result = await crawler.arun(url=url)

                if not result or not hasattr(result, 'markdown') or not result.markdown:
                    continue

                text = result.markdown.raw_markdown if hasattr(result.markdown, 'raw_markdown') else str(result.markdown)

                emails = extract_emails(text)
                for email in emails:
                    if email not in all_emails:
                        confidence = score_email(email, garden_name, text)
                        all_emails[email] = {
                            "email": email,
                            "confidence": confidence,
                            "source_url": url,
                            "garden_id": garden_id,
                        }

                result_urls = extract_urls_from_serp(text)
                collected_result_urls.extend(result_urls)

                await asyncio.sleep(2)

            except Exception as e:
                logger.debug(f"  SERP error for {url[:80]}: {e}")
                continue

        seen = set()
        unique_result_urls = []
        for u in collected_result_urls:
            if u not in seen:
                seen.add(u)
                unique_result_urls.append(u)

        for result_url in unique_result_urls[:5]:
            try:
                with redirect_stdout(null_out), redirect_stderr(null_err):
                    page_result = await crawler.arun(url=result_url)

                if not page_result or not hasattr(page_result, 'markdown') or not page_result.markdown:
                    continue

                page_text = page_result.markdown.raw_markdown if hasattr(page_result.markdown, 'raw_markdown') else str(page_result.markdown)

                page_emails = extract_emails(page_text)
                for email in page_emails:
                    if email not in all_emails:
                        confidence = score_email(email, garden_name, page_text)
                        all_emails[email] = {
                            "email": email,
                            "confidence": confidence,
                            "source_url": result_url,
                            "garden_id": garden_id,
                        }

                await asyncio.sleep(2)

            except Exception as e:
                logger.debug(f"  Page error for {result_url[:80]}: {e}")
                continue

        for email, entry in all_emails.items():
            website_url = None
            if entry["confidence"] >= 0.6:
                domain = email.split("@")[1]
                if domain not in ("gmail.com", "yahoo.com", "hotmail.com", "rediffmail.com", "outlook.com"):
                    website_url = f"https://{domain}"

            entry["website"] = website_url
            results.append(entry)

    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results


async def crawl_all_emails(
    batch_size: int = 50,
    min_confidence: float = 0.0,
    max_concurrent: int = 3,
    retry_failed: bool = False,
) -> dict[str, int]:
    from db_v2 import init_db, add_garden_email, get_connection

    conn = init_db()

    if retry_failed:
        rows = conn.execute(
            """SELECT g.id, g.name, g.district, g.state
               FROM gardens g
               WHERE g.id NOT IN (SELECT DISTINCT garden_id FROM garden_emails)
               ORDER BY g.confidence_score DESC"""
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT g.id, g.name, g.district, g.state
               FROM gardens g
               LEFT JOIN garden_emails ge ON ge.garden_id = g.id
               WHERE ge.id IS NULL
               ORDER BY g.confidence_score DESC"""
        ).fetchall()

    total = len(rows)
    logger.info(f"Found {total} gardens without any email")

    results = {"crawled": 0, "emails_found": 0, "gardens_with_email": 0, "errors": 0}

    for i in range(0, total, batch_size):
        batch = rows[i:i + batch_size]
        logger.info(f"Batch {i // batch_size + 1}: {i+1}-{min(i+batch_size, total)} of {total}")

        for row in batch:
            garden_id = row["id"]
            name = row["name"]
            district = row["district"] or ""
            state = row["state"] or "Assam"

            logger.info(f"  [{i+1}/{total}] {name} ({district})")

            try:
                email_results = await crawl_for_emails(
                    garden_name=name,
                    garden_id=garden_id,
                    district=district,
                    state=state,
                )

                for er in email_results:
                    if er["confidence"] >= min_confidence:
                        add_garden_email(
                            conn, garden_id, er["email"],
                            confidence=er["confidence"],
                            source_url=er["source_url"],
                            source_type="google_crawl",
                        )
                        results["emails_found"] += 1

                        primary_email = conn.execute(
                            "SELECT email FROM gardens WHERE id = ?", (garden_id,)
                        ).fetchone()["email"]

                        if not primary_email:
                            conn.execute(
                                "UPDATE gardens SET email = ?, email_confidence = ? WHERE id = ?",
                                (er["email"], er["confidence"], garden_id),
                            )
                            conn.commit()

                        website = er.get("website")
                        if website:
                            existing_website = conn.execute(
                                "SELECT website FROM gardens WHERE id = ?", (garden_id,)
                            ).fetchone()["website"]
                            if not existing_website:
                                conn.execute(
                                    "UPDATE gardens SET website = ? WHERE id = ?",
                                    (website, garden_id),
                                )
                                conn.commit()

                if email_results:
                    results["gardens_with_email"] += 1
                    logger.info(f"    -> Found {len(email_results)} email(s): {', '.join(e['email'] for e in email_results[:3])}")
                else:
                    logger.info(f"    -> No emails found")

                conn.execute(
                    """INSERT INTO email_crawl_log (garden_id, garden_name, url_crawled, emails_found, status)
                       VALUES (?,?,?,?,?)""",
                    (garden_id, name, "google_dork",
                     ";".join(e["email"] for e in email_results),
                     "found" if email_results else "no_email_found"),
                )
                conn.commit()

                results["crawled"] += 1

            except Exception as e:
                logger.error(f"    -> Error: {e}")
                results["errors"] += 1
                try:
                    conn.execute(
                        """INSERT INTO email_crawl_log (garden_id, garden_name, url_crawled, emails_found, status, error)
                           VALUES (?,?,?,?,?,?)""",
                        (garden_id, name, "google_dork", "", "error", str(e)),
                    )
                    conn.commit()
                except Exception:
                    pass

            await asyncio.sleep(2)

    conn.close()
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    results = asyncio.run(crawl_all_emails(batch_size=50))
    print(f"\n=== Email Crawl Complete ===")
    print(f"  Crawled: {results['crawled']}")
    print(f"  Total emails found: {results['emails_found']}")
    print(f"  Gardens with email: {results['gardens_with_email']}")
    print(f"  Errors: {results['errors']}")
