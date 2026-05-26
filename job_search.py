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
4. IAM & Admin → Service Accounts → + Create Service Account → name it → Done
5. Click the service account → Keys tab → Add Key → Create new key → JSON
6. Save the downloaded file as  service_account.json  in this folder
7. Run this script — no browser needed, works every time automatically.
────────────────────────────────────────────────────────────────────────────────
"""

import requests, json, re, time, sys, os, webbrowser, argparse, subprocess
import datetime as dt
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from generate_resume import create_resume, make_headline, make_summary, output_path_for, tailor_bullets, TAILORED_DIR

import gspread
from google.oauth2 import service_account

try:
    import pyperclip
    _CLIPBOARD = True
except ImportError:
    _CLIPBOARD = False

try:
    import anthropic as _anthropic
    _ANTHROPIC = True
except ImportError:
    _ANTHROPIC = False

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR    = Path(r"C:\Users\Mark\Jobsearch")
SA_FILE     = BASE_DIR / "service_account.json"
CONFIG_FILE = BASE_DIR / "sheets_config.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_TITLE = "Job Listings — Mark Izrailev"

HEADERS_ROW = [
    "#", "Date Added", "Title", "Company", "Location",
    "Source", "Date Posted", "Salary", "Link", "Reviewed?", "Resume Created", "Status", "Notes",
    "Applied?", "Date Applied", "Cover Letter",
]
# Column indices (0-based in data rows)
COL_SALARY         = 7
COL_LINK           = 8
COL_REVIEWED       = 9
COL_RESUME_CREATED = 10
COL_STATUS         = 11
COL_NOTES          = 12
COL_APPLIED        = 13
COL_DATE_APPLIED   = 14
COL_COVER_LETTER   = 15

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
    if not SA_FILE.exists():
        print("\n[ERROR] service_account.json not found.")
        print("See setup instructions at the top of this file.")
        sys.exit(1)
    creds = service_account.Credentials.from_service_account_file(str(SA_FILE), scopes=SCOPES)
    return gspread.authorize(creds)


def get_service_account_email():
    return json.loads(SA_FILE.read_text()).get("client_email", "")

def get_or_create_sheet(client):
    """Open spreadsheet by saved ID, or prompt user to create and share one."""
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
        spreadsheet_id = cfg.get("spreadsheet_id")
        if spreadsheet_id:
            try:
                sh = client.open_by_key(spreadsheet_id)
                print(f"  Opened sheet: {sh.url}")
                return sh
            except Exception as e:
                print(f"  Could not open sheet: {e}")

    sa_email = get_service_account_email()
    print(f"""
  [SETUP REQUIRED — one time only]
  1. Go to https://sheets.google.com and create a blank spreadsheet
     Name it: Job Listings — Mark Izrailev
  2. Click Share → paste this email → set role to Editor → Send:
     {sa_email}
  3. Copy the spreadsheet ID from the URL:
     https://docs.google.com/spreadsheets/d/  SPREADSHEET_ID  /edit
  4. Paste it here:""")

    spreadsheet_id = input("  Spreadsheet ID: ").strip()
    CONFIG_FILE.write_text(json.dumps({"spreadsheet_id": spreadsheet_id}, indent=2))
    sh = client.open_by_key(spreadsheet_id)
    print(f"  Connected: {sh.url}")
    return sh


def _add_checkboxes(sh, ws, start_row, end_row):
    """Add checkbox data validation to Reviewed? and Applied? columns for given rows (1-indexed)."""
    if start_row > end_row:
        return
    sh.batch_update({"requests": [
        {
            "setDataValidation": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": start_row - 1,
                    "endRowIndex": end_row,
                    "startColumnIndex": col,
                    "endColumnIndex": col + 1,
                },
                "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True},
            }
        }
        for col in (COL_REVIEWED, COL_APPLIED)
    ]})


def init_worksheet(sh):
    """Return the main worksheet, migrating old column structure if needed."""
    ws = sh.sheet1
    ws.update_title("Listings")
    existing = ws.get_all_values()

    if existing and existing[0] == HEADERS_ROW:
        return ws  # already up to date

    if existing and len(existing[0]) == 15 and existing[0][14] == "Cover Letter":
        # 15-column structure — insert Salary between Date Posted and Link
        print("  Migrating sheet: adding Salary column...")
        sh.batch_update({"requests": [{
            "insertDimension": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                          "startIndex": 7, "endIndex": 8},
                "inheritFromBefore": False,
            }
        }]})
        ws.update_cell(1, 8, "Salary")
        print("  Migration complete.")
        return ws

    if existing and len(existing[0]) == 12 and existing[0][12 - 1] == "Notes":
        # 12-column structure — append Applied?, Date Applied, Cover Letter
        print("  Migrating sheet: adding Applied?, Date Applied, Cover Letter columns...")
        sh.batch_update({"requests": [{
            "appendDimension": {
                "sheetId": ws.id, "dimension": "COLUMNS", "length": 3,
            }
        }]})
        ws.update_cell(1, COL_APPLIED + 1,      "Applied?")
        ws.update_cell(1, COL_DATE_APPLIED + 1, "Date Applied")
        ws.update_cell(1, COL_COVER_LETTER + 1, "Cover Letter")
        num_data_rows = len(existing) - 1
        if num_data_rows > 0:
            _add_checkboxes(sh, ws, 2, num_data_rows + 1)
        print("  Migration complete.")
        return ws

    if existing and len(existing[0]) == 10 and existing[0][1] in ("Date Found", "Date Added"):
        # Old 10-column structure — insert Reviewed? and Resume Created before Status
        print("  Migrating sheet to new column structure...")
        sh.batch_update({"requests": [{
            "insertDimension": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                          "startIndex": COL_REVIEWED, "endIndex": COL_REVIEWED + 2},
                "inheritFromBefore": False,
            }
        }]})
        ws.update_cell(1, COL_REVIEWED + 1, "Reviewed?")
        ws.update_cell(1, COL_RESUME_CREATED + 1, "Resume Created")
        ws.update_cell(1, 2, "Date Added")
        num_data_rows = len(existing) - 1
        if num_data_rows > 0:
            _add_checkboxes(sh, ws, 2, num_data_rows + 1)
        print("  Migration complete.")
        return ws

    # Fresh init
    ws.clear()
    ws.append_row(HEADERS_ROW, value_input_option="RAW")
    ws.format("A1:P1", {
        "textFormat": {"bold": True},
        "backgroundColor": {"red": 0.18, "green": 0.18, "blue": 0.18},
    })
    col_widths = [40, 100, 240, 180, 160, 90, 100, 120, 380, 90, 130, 120, 200, 90, 110, 400]
    sh.batch_update({"requests": [
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": i, "endIndex": i+1},
            "properties": {"pixelSize": w}, "fields": "pixelSize",
        }} for i, w in enumerate(col_widths)
    ]})
    sh.batch_update({"requests": [{"updateSheetProperties": {
        "properties": {"sheetId": ws.id, "gridProperties": {"frozenRowCount": 1}},
        "fields": "gridProperties.frozenRowCount",
    }}]})
    return ws


def push_to_sheet(ws, sh, new_jobs):
    """Append only jobs not already in the sheet; add checkboxes to new rows."""
    existing_rows = ws.get_all_values()
    existing_links = {row[COL_LINK] for row in existing_rows[1:] if len(row) > COL_LINK}

    date_added = datetime.now().strftime("%Y-%m-%d")
    rows_to_add = []
    start_num = len(existing_rows)

    for job in new_jobs:
        link = job.get("link", "")
        if link and link in existing_links:
            continue
        existing_links.add(link)
        start_num += 1
        rows_to_add.append([
            start_num - 1,
            date_added,
            job.get("title", ""),
            job.get("company", ""),
            job.get("location", ""),
            job.get("source", ""),
            job.get("date", "")[:10] if job.get("date") else "",
            job.get("salary", ""),   # Salary
            link,
            False,   # Reviewed?
            "",      # Resume Created
            "",      # Status
            "",      # Notes
            False,   # Applied?
            "",      # Date Applied
            "",      # Cover Letter
        ])

    if rows_to_add:
        first_new_row = len(existing_rows) + 1
        last_new_row  = first_new_row + len(rows_to_add) - 1
        ws.append_rows(rows_to_add, value_input_option="USER_ENTERED")
        _add_checkboxes(sh, ws, first_new_row, last_new_row)

    return len(rows_to_add)


# ── LinkedIn job description fetcher ─────────────────────────────────────────

def fetch_jd_text(url):
    """Fetch job description text from a LinkedIn job URL."""
    if not url or "linkedin.com" not in url:
        return ""
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=12)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        for sel in [
            "div.show-more-less-html__markup",
            "div.description__text",
            "section.show-more-less-html",
        ]:
            el = soup.select_one(sel)
            if el:
                text = re.sub(r"\s+", " ", el.get_text(" ")).strip()
                return text[:3000]
    except Exception:
        pass
    return ""


# ── Resume generation for reviewed rows ──────────────────────────────────────

def generate_pending_resumes(ws, sh):
    """Generate PDFs for rows where Reviewed?=TRUE and Resume Created is blank."""
    rows = ws.get_all_values()
    pending = []
    for i, row in enumerate(rows[1:], start=2):   # i = 1-indexed sheet row
        reviewed = str(row[COL_REVIEWED]).upper() if len(row) > COL_REVIEWED else ""
        created  = row[COL_RESUME_CREATED] if len(row) > COL_RESUME_CREATED else ""
        if reviewed == "TRUE" and not created.strip():
            pending.append((i, row))

    if not pending:
        return 0

    print(f"\n  Generating resumes for {len(pending)} reviewed listing(s)...")
    count = 0
    for sheet_row, row in pending:
        title   = row[2] if len(row) > 2 else ""
        company = row[3] if len(row) > 3 else ""
        link    = row[COL_LINK] if len(row) > COL_LINK else ""

        print(f"  → {title} at {company}")
        jd_text  = fetch_jd_text(link)
        headline = make_headline(title)
        summary  = make_summary(title, company, jd_text)
        bullets  = tailor_bullets(jd_text, title, company)
        out_path = output_path_for(company, title)

        try:
            create_resume(out_path, headline, summary, bullets)
            filename = out_path.name
            ws.update_cell(sheet_row, COL_RESUME_CREATED + 1, filename)
            print(f"    Saved: {filename}")
            count += 1
        except Exception as e:
            print(f"    [Error generating resume]: {e}")
        time.sleep(0.5)

    return count


# ── Cover letter generation & application launcher ────────────────────────────

def _load_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    key = line.split("=", 1)[1].strip()
    return key


def generate_cover_letter(jd_text, title, company):
    """Generate a targeted 3-paragraph cover letter via Claude API."""
    if not _ANTHROPIC:
        return ""
    api_key = _load_api_key()
    if not api_key:
        return ""
    client = _anthropic.Anthropic(api_key=api_key)
    prompt = f"""You are an elite executive career coach writing a cover letter for Mark Izrailev, a senior supply chain and demand planning professional based in Highlands Ranch, CO.

Role: {title} at {company}

Job Description:
{jd_text[:3000]}

Write a concise, high-impact 3-paragraph cover letter (150–200 words total).
- Paragraph 1: Open with a specific metric or achievement that directly addresses the company's most pressing operational need visible in the JD.
- Paragraph 2: Two or three concrete examples drawn from experience (Viega, Forum Brands) that map to the role's stated priorities. Quantify everything possible.
- Paragraph 3: Direct, confident close — no fluff. State availability and conviction.

Rules: Strong operational verbs only. Zero filler phrases ("I am passionate about", "dynamic", "synergy"). Output only the letter body — no salutation, no signature."""
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"    [Cover letter generation failed]: {e}")
        return ""


def apply_pending_jobs(ws, sh):
    """Interactive launcher: for each job with a resume but not yet applied,
    generate a cover letter, open the job URL, copy resume path to clipboard,
    then mark Applied + Date Applied on confirmation."""
    rows = ws.get_all_values()
    pending = []
    for i, row in enumerate(rows[1:], start=2):
        resume_created = row[COL_RESUME_CREATED] if len(row) > COL_RESUME_CREATED else ""
        applied        = str(row[COL_APPLIED]).upper() if len(row) > COL_APPLIED else ""
        if resume_created.strip() and applied not in ("TRUE",):
            pending.append((i, row))

    if not pending:
        print("  No pending applications (all reviewed jobs already applied or no resumes generated yet).")
        return 0

    print(f"\n  {len(pending)} job(s) queued for application.\n")
    count = 0
    for sheet_row, row in pending:
        title   = row[2]   if len(row) > 2              else ""
        company = row[3]   if len(row) > 3              else ""
        link    = row[COL_LINK] if len(row) > COL_LINK  else ""
        resume_file = row[COL_RESUME_CREATED]
        resume_path = TAILORED_DIR / resume_file

        print(f"  ┌─ {title} @ {company}")
        print(f"  │  Resume: {resume_file}")

        # Cover letter — generate if not already stored
        cover = row[COL_COVER_LETTER].strip() if len(row) > COL_COVER_LETTER else ""
        if not cover:
            print("  │  Generating cover letter...", end=" ", flush=True)
            jd_text = fetch_jd_text(link)
            cover   = generate_cover_letter(jd_text, title, company)
            if cover:
                ws.update_cell(sheet_row, COL_COVER_LETTER + 1, cover)
                print("done.")
            else:
                print("skipped (API unavailable).")
        else:
            print("  │  Cover letter: already on file.")

        # Print cover letter preview
        if cover:
            preview = cover[:300] + ("…" if len(cover) > 300 else "")
            print(f"  │\n  │  {preview.replace(chr(10), chr(10) + '  │  ')}\n  │")

        # Copy resume path to clipboard
        if _CLIPBOARD:
            try:
                pyperclip.copy(str(resume_path))
                print(f"  │  Clipboard: resume path copied.")
            except Exception:
                print(f"  │  Clipboard unavailable — path: {resume_path}")
        else:
            print(f"  │  Resume path: {resume_path}")

        # Open job URL in Chrome
        if link:
            try:
                subprocess.Popen(f'start chrome "{link}"', shell=True)
            except Exception:
                webbrowser.open(link)
            print(f"  │  Opened job URL in Chrome.")

        # Confirm
        try:
            answer = input("  └─ Mark as applied? [y / n / q=quit] → ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if answer == "q":
            break
        elif answer == "y":
            today = dt.date.today().isoformat()
            ws.update_cell(sheet_row, COL_APPLIED + 1,      True)
            ws.update_cell(sheet_row, COL_DATE_APPLIED + 1, today)
            print(f"  ✓  Applied — recorded {today}\n")
            count += 1
        else:
            print("  –  Skipped.\n")

    return count


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
            salary_el  = card.select_one(".job-search-card__salary-info")
            if not title_el:
                continue
            jobs.append({
                "title":       title_el.get_text(strip=True),
                "company":     company_el.get_text(strip=True) if company_el else "",
                "location":    loc_el.get_text(strip=True)     if loc_el     else location,
                "link":        link_el["href"].split("?")[0]   if link_el    else "",
                "date":        date_el.get("datetime", "")     if date_el    else "",
                "salary":      re.sub(r"\s+", " ", salary_el.get_text(strip=True)) if salary_el else "",
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
            salary_el  = card.select_one("[data-testid='attribute_snippet_testid'], .salary-snippet-container, .estimated-salary")
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
                "salary":   re.sub(r"\s+", " ", salary_el.get_text(strip=True)) if salary_el else "",
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
            s_min = job.get("salary_min")
            s_max = job.get("salary_max")
            if s_min and s_max:
                salary = f"${int(s_min)//1000}k – ${int(s_max)//1000}k"
            elif s_min:
                salary = f"${int(s_min)//1000}k+"
            else:
                salary = ""
            jobs.append({
                "title":    job.get("position", ""),
                "company":  job.get("company", ""),
                "location": "Remote",
                "link":     job.get("url", ""),
                "date":     job.get("date", "")[:10] if job.get("date") else "",
                "salary":   salary,
                "source":   "RemoteOK",
                "search_term": "supply chain / demand planning",
            })
        return jobs
    except Exception as e:
        print(f"    [RemoteOK error]: {e}")
        return []


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Job search pipeline — Mark Izrailev")
    parser.add_argument(
        "--apply", action="store_true",
        help="Skip scraping; launch interactive application workflow for reviewed jobs with resumes.",
    )
    args = parser.parse_args()

    print(f"\n{'='*62}")
    print("  JOB SEARCH — Mark Izrailev  |  Supply Chain / Demand Planning")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*62}\n")

    if args.apply:
        print("  Mode: Application Launcher\n")
        client  = get_gspread_client()
        sh      = get_or_create_sheet(client)
        ws      = init_worksheet(sh)
        applied = apply_pending_jobs(ws, sh)
        print(f"\n{'='*62}")
        print(f"  Applications recorded this session: {applied}")
        print(f"  Sheet: {sh.url}")
        print(f"{'='*62}\n")
        return

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

    print("\nLinkedIn  •  Remote (US, f_WT=2 filter)")
    for term in SEARCH_TERMS:
        n = add_jobs(linkedin_search(term, remote=True))
        print(f"  {term:<30}  {n} new listings")
        time.sleep(0.8)

    print("\nLinkedIn  •  Remote (keyword, no location filter)")
    for term in SEARCH_TERMS:
        n = add_jobs(linkedin_search(term + " remote", location=""))
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
    client   = get_gspread_client()
    sh       = get_or_create_sheet(client)
    ws       = init_worksheet(sh)
    added    = push_to_sheet(ws, sh, all_jobs)
    resumes  = generate_pending_resumes(ws, sh)

    # ── Summary ─────────────────────────────────────────────────────────────
    print(f"\n{'='*62}")
    print(f"  Scraped: {len(all_jobs)} listings  |  New rows added: {added}  |  Resumes generated: {resumes}")
    print(f"  Sheet:   {sh.url}")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    main()
