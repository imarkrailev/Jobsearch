#!/usr/bin/env python3
"""
Job Search Tool — Mark Izrailev
Sources: LinkedIn (guest API), Indeed (scrape), RemoteOK (public API)
Output:  Google Sheets spreadsheet  (new rows only — preserves existing Status/Notes)

── FIRST-TIME SETUP ────────────────────────────────────────────────────────────
1. Go to https://console.cloud.google.com/
2. Create a new project (or select an existing one)
3. Enable APIs:  search "Google Sheets API" → Enable
                 search "Google Drive API"  → Enable
4. Create credentials:
     Credentials → + Create Credentials → OAuth client ID
     Application type: Desktop app  → Name it anything → Create
5. Download the JSON → save it as  credentials.json  in this folder
6. Run this script — a browser window will open once for authorization
   After that, a token.json is saved and no browser is needed again.
────────────────────────────────────────────────────────────────────────────────
"""

import requests, json, re, time, sys, os
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR      = Path(r"C:\Users\Mark\Jobsearch")
CREDS_FILE    = BASE_DIR / "credentials.json"
TOKEN_FILE    = BASE_DIR / "token.json"
CONFIG_FILE   = BASE_DIR / "sheets_config.json"   # stores spreadsheet ID after first run

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_TITLE = "Job Listings — Mark Izrailev"

HEADERS_ROW = [
    "#", "Date Found", "Title", "Company", "Location",
    "Source", "Date Posted", "Link", "Status", "Notes",
]

# ── Config ────────────────────────────────────────────────────────────────────

SEARCH_TERMS = [
    "Demand Planner",
    "Senior Demand Planner",
    "Supply Planner",
    "Inventory Planner",
    "S&OP Manager",
    "Demand Planning Manager",
    "Supply Chain Planner",
]

DENVER_LOCATION = "Denver, Colorado, United States"

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Google Sheets auth & setup ────────────────────────────────────────────────

def get_gspread_client():
    if not CREDS_FILE.exists():
        print("\n[ERROR] credentials.json not found.")
        print("See setup instructions at the top of this file.")
        sys.exit(1)

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())

    return gspread.authorize(creds)


def get_or_create_sheet(client):
    """Open existing spreadsheet by saved ID, or create a new one."""
    spreadsheet_id = None
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
        spreadsheet_id = cfg.get("spreadsheet_id")

    if spreadsheet_id:
        try:
            sh = client.open_by_key(spreadsheet_id)
            print(f"  Opened existing sheet: {sh.url}")
            return sh
        except Exception:
            print("  Saved sheet not found — creating a new one.")

    # Create new spreadsheet
    sh = client.create(SHEET_TITLE)
    sh.share(None, perm_type="anyone", role="writer")  # makes URL shareable
    CONFIG_FILE.write_text(json.dumps({"spreadsheet_id": sh.id}, indent=2))
    print(f"  Created new sheet: {sh.url}")
    return sh


def init_worksheet(sh):
    """Return the main worksheet, creating it with headers if needed."""
    ws = sh.sheet1
    ws.update_title("Listings")

    existing = ws.get_all_values()
    if not existing or existing[0] != HEADERS_ROW:
        ws.clear()
        ws.append_row(HEADERS_ROW, value_input_option="RAW")
        # Format header row
        ws.format("A1:J1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
        })
        # Set column widths
        body = {"requests": [
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                           "startIndex": i, "endIndex": i+1},
                "properties": {"pixelSize": w},
                "fields": "pixelSize",
            }}
            for i, w in enumerate([40, 100, 240, 180, 160, 90, 100, 400, 120, 200])
        ]}
        sh.batch_update(body)
        # Freeze header row
        sh.batch_update({"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": ws.id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }}]})

    return ws


def push_to_sheet(ws, new_jobs):
    """Append only jobs whose links aren't already in the sheet."""
    existing_rows = ws.get_all_values()
    existing_links = {row[7] for row in existing_rows[1:] if len(row) > 7}

    date_found = datetime.now().strftime("%Y-%m-%d")
    rows_to_add = []
    start_num = len(existing_rows)  # row counter continues from last row

    for job in new_jobs:
        link = job.get("link", "")
        if link and link in existing_links:
            continue
        existing_links.add(link)
        start_num += 1
        rows_to_add.append([
            start_num - 1,              # #
            date_found,                 # Date Found
            job.get("title", ""),       # Title
            job.get("company", ""),     # Company
            job.get("location", ""),    # Location
            job.get("source", ""),      # Source
            job.get("date", "")[:10] if job.get("date") else "",  # Date Posted
            link,                       # Link
            "",                         # Status (user fills in)
            "",                         # Notes (user fills in)
        ])

    if rows_to_add:
        ws.append_rows(rows_to_add, value_input_option="RAW")

    return len(rows_to_add)


# ── Job scrapers ──────────────────────────────────────────────────────────────

def linkedin_search(query, location="", remote=False):
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    params = {"keywords": query, "location": location, "start": 0, "f_WT": "2" if remote else ""}
    if remote:
        params["location"] = "United States"
    try:
        r = requests.get(base, params=params, headers=HTTP_HEADERS, timeout=12)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        jobs = []
        for card in soup.select("li"):
            title_el   = card.select_one(".base-search-card__title")
            company_el = card.select_one(".base-search-card__subtitle")
            loc_el     = card.select_one(".job-search-card__location")
            link_el    = card.select_one("a.base-card__full-link")
            date_el    = card.select_one("time")
            if not title_el:
                continue
            jobs.append({
                "title":       title_el.get_text(strip=True),
                "company":     company_el.get_text(strip=True) if company_el else "",
                "location":    loc_el.get_text(strip=True)     if loc_el     else location,
                "link":        link_el["href"].split("?")[0]   if link_el    else "",
                "date":        date_el.get("datetime", "")     if date_el    else "",
                "source":      "LinkedIn",
                "search_term": query,
            })
        return jobs
    except Exception as e:
        print(f"    [LinkedIn error — '{query}']: {e}")
        return []


def indeed_search(query, location="Denver, CO", remote=False):
    q = query.replace(" ", "+")
    l = "remote" if remote else location.replace(" ", "+").replace(",", "%2C")
    url = f"https://www.indeed.com/jobs?q={q}&l={l}&radius=50&sort=date&fromage=30"
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=12)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        jobs = []
        for card in soup.select("div.job_seen_beacon, div.tapItem"):
            title_el   = card.select_one("h2.jobTitle span[title], h2.jobTitle a span")
            company_el = card.select_one("[data-testid='company-name'], .companyName")
            loc_el     = card.select_one("[data-testid='text-location'], .companyLocation")
            link_el    = card.select_one("h2.jobTitle a")
            date_el    = card.select_one("[data-testid='myJobsStateDate'], .date")
            if not title_el:
                continue
            href = link_el["href"] if link_el else ""
            if href and not href.startswith("http"):
                href = "https://www.indeed.com" + href
            jobs.append({
                "title":    title_el.get_text(strip=True),
                "company":  company_el.get_text(strip=True) if company_el else "",
                "location": loc_el.get_text(strip=True)     if loc_el     else location,
                "link":     href,
                "date":     date_el.get_text(strip=True)    if date_el    else "",
                "source":   "Indeed",
                "search_term": query,
            })
        return jobs
    except Exception as e:
        print(f"    [Indeed error — '{query}']: {e}")
        return []


REMOTEOK_TITLE_PHRASES = [
    "demand plan", "supply plan", "inventory plan", "demand manager",
    "supply chain plan", "s&op", "replenishment", "forecast",
    "inventory manager", "supply chain analyst", "supply chain manager",
    "procurement plan", "materials plan",
]

def remoteok_search():
    try:
        r = requests.get(
            "https://remoteok.com/api",
            headers={**HTTP_HEADERS, "Accept": "application/json"},
            timeout=15,
        )
        r.raise_for_status()
        jobs = []
        for job in r.json():
            if not isinstance(job, dict) or "position" not in job:
                continue
            if not any(p in job.get("position", "").lower() for p in REMOTEOK_TITLE_PHRASES):
                continue
            jobs.append({
                "title":    job.get("position", ""),
                "company":  job.get("company", ""),
                "location": "Remote",
                "link":     job.get("url", ""),
                "date":     job.get("date", "")[:10] if job.get("date") else "",
                "source":   "RemoteOK",
                "search_term": "supply chain / demand planning",
            })
        return jobs
    except Exception as e:
        print(f"    [RemoteOK error]: {e}")
        return []


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*62}")
    print("  JOB SEARCH — Mark Izrailev  |  Supply Chain / Demand Planning")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*62}\n")

    # ── Scrape ─────────────────────────────────────────────────────────────
    all_jobs   = []
    seen_links = set()

    def add_jobs(jobs):
        added = 0
        for j in jobs:
            key = j["link"] or (j["title"] + j["company"])
            if key and key not in seen_links:
                seen_links.add(key)
                all_jobs.append(j)
                added += 1
        return added

    print("LinkedIn  •  Denver area (50 mi)")
    for term in SEARCH_TERMS:
        n = add_jobs(linkedin_search(term, location=DENVER_LOCATION))
        print(f"  {term:<30}  {n} new listings")
        time.sleep(0.8)

    print("\nLinkedIn  •  Remote (US)")
    for term in SEARCH_TERMS:
        n = add_jobs(linkedin_search(term, remote=True))
        print(f"  {term:<30}  {n} new listings")
        time.sleep(0.8)

    print("\nIndeed  •  Denver, CO (50 mi)")
    for term in SEARCH_TERMS:
        n = add_jobs(indeed_search(term, location="Denver, CO"))
        print(f"  {term:<30}  {n} new listings")
        time.sleep(1.0)

    print("\nIndeed  •  Remote")
    for term in SEARCH_TERMS:
        n = add_jobs(indeed_search(term, remote=True))
        print(f"  {term:<30}  {n} new listings")
        time.sleep(1.0)

    print("\nRemoteOK  •  Remote")
    n = add_jobs(remoteok_search())
    print(f"  Supply chain / demand planning roles: {n} new listings")

    # ── Push to Google Sheets ───────────────────────────────────────────────
    print(f"\n{'─'*62}")
    print("  Connecting to Google Sheets...")
    client = get_gspread_client()
    sh     = get_or_create_sheet(client)
    ws     = init_worksheet(sh)
    added  = push_to_sheet(ws, all_jobs)

    # ── Summary ─────────────────────────────────────────────────────────────
    print(f"\n{'='*62}")
    print(f"  Scraped: {len(all_jobs)} listings  |  New rows added to sheet: {added}")
    print(f"  Sheet:   {sh.url}")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    main()
