#!/usr/bin/env python3
"""
Job Search Tool — Mark Izrailev
Sources: LinkedIn (guest API), Indeed (scrape), RemoteOK (public API)
Output:  job_listings.json  +  console summary
"""

import requests, json, re, time, sys
from datetime import datetime
from bs4 import BeautifulSoup

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

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

DENVER_LOCATION  = "Denver, Colorado, United States"
DENVER_RADIUS_MI = 50

OUTPUT_FILE = r"C:\Users\Mark\Jobsearch\job_listings.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ── LinkedIn guest job search ─────────────────────────────────────────────────

def linkedin_search(query, location="", remote=False, start=0):
    """
    LinkedIn's unauthenticated job listing endpoint.
    Returns list of job dicts.
    """
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    params = {
        "keywords": query,
        "location": location,
        "start": start,
        "f_WT": "2" if remote else "",   # f_WT=2 = Remote filter
    }
    if remote:
        params["location"] = "United States"
    try:
        r = requests.get(base, params=params, headers=HEADERS, timeout=12)
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
                "description": "",
                "source":      "LinkedIn",
                "search_term": query,
            })
        return jobs
    except Exception as e:
        print(f"    [LinkedIn error — '{query}']: {e}")
        return []


# ── Indeed scrape ─────────────────────────────────────────────────────────────

def indeed_search(query, location="Denver, CO", remote=False):
    """Scrape Indeed search results page."""
    q = query.replace(" ", "+")
    l = "remote" if remote else location.replace(" ", "+").replace(",", "%2C")
    url = f"https://www.indeed.com/jobs?q={q}&l={l}&radius=50&sort=date&fromage=30"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
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
                "title":       title_el.get_text(strip=True),
                "company":     company_el.get_text(strip=True) if company_el else "",
                "location":    loc_el.get_text(strip=True)     if loc_el     else location,
                "link":        href,
                "date":        date_el.get_text(strip=True)    if date_el    else "",
                "description": "",
                "source":      "Indeed",
                "search_term": query,
            })
        return jobs
    except Exception as e:
        print(f"    [Indeed error — '{query}']: {e}")
        return []


# ── RemoteOK public API ───────────────────────────────────────────────────────

# RemoteOK: title must contain at least one of these phrases to be included
REMOTEOK_TITLE_PHRASES = [
    "demand plan", "supply plan", "inventory plan", "demand manager",
    "supply chain plan", "s&op", "replenishment", "forecast",
    "inventory manager", "supply chain analyst", "supply chain manager",
    "procurement plan", "materials plan",
]

def remoteok_search():
    """Pull all RemoteOK jobs and filter for supply chain relevance by title."""
    try:
        r = requests.get(
            "https://remoteok.com/api",
            headers={**HEADERS, "Accept": "application/json"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        jobs = []
        for job in data:
            if not isinstance(job, dict) or "position" not in job:
                continue
            title_lower = job.get("position", "").lower()
            if not any(phrase in title_lower for phrase in REMOTEOK_TITLE_PHRASES):
                continue
            desc = re.sub(r"<[^>]+>", " ", job.get("description", ""))
            desc = re.sub(r"\s+", " ", desc).strip()[:300]
            jobs.append({
                "title":       job.get("position", ""),
                "company":     job.get("company", ""),
                "location":    "Remote",
                "link":        job.get("url", ""),
                "date":        job.get("date", "")[:10] if job.get("date") else "",
                "description": desc,
                "source":      "RemoteOK",
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

    # ── LinkedIn — Denver area ──────────────────────────────────────────────
    print("LinkedIn  •  Denver area (50 mi)")
    for term in SEARCH_TERMS:
        jobs = linkedin_search(term, location=DENVER_LOCATION)
        n    = add_jobs(jobs)
        print(f"  {term:<30}  {n} new listings")
        time.sleep(0.8)

    # ── LinkedIn — Remote ───────────────────────────────────────────────────
    print("\nLinkedIn  •  Remote (US)")
    for term in SEARCH_TERMS:
        jobs = linkedin_search(term, remote=True)
        n    = add_jobs(jobs)
        print(f"  {term:<30}  {n} new listings")
        time.sleep(0.8)

    # ── Indeed — Denver area ────────────────────────────────────────────────
    print("\nIndeed  •  Denver, CO (50 mi)")
    for term in SEARCH_TERMS:
        jobs = indeed_search(term, location="Denver, CO")
        n    = add_jobs(jobs)
        print(f"  {term:<30}  {n} new listings")
        time.sleep(1.0)

    # ── Indeed — Remote ─────────────────────────────────────────────────────
    print("\nIndeed  •  Remote")
    for term in SEARCH_TERMS:
        jobs = indeed_search(term, remote=True)
        n    = add_jobs(jobs)
        print(f"  {term:<30}  {n} new listings")
        time.sleep(1.0)

    # ── RemoteOK ────────────────────────────────────────────────────────────
    print("\nRemoteOK  •  Remote")
    jobs = remoteok_search()
    n    = add_jobs(jobs)
    print(f"  Supply chain / demand planning roles: {n} new listings")

    # ── Save ────────────────────────────────────────────────────────────────
    output = {
        "generated": datetime.now().isoformat(),
        "total":     len(all_jobs),
        "jobs":      all_jobs,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # ── Summary ─────────────────────────────────────────────────────────────
    print(f"\n{'='*62}")
    print(f"  TOTAL: {len(all_jobs)} unique listings  |  Saved → job_listings.json")
    print(f"{'='*62}\n")

    by_source = {}
    for j in all_jobs:
        by_source.setdefault(j["source"], []).append(j)
    for src, jobs in sorted(by_source.items()):
        print(f"  {src:<12} {len(jobs)} listings")

    print(f"\n{'─'*62}")
    print("  ALL LISTINGS\n")
    for i, j in enumerate(all_jobs, 1):
        loc = j["location"] or "—"
        dt  = j["date"][:10] if j["date"] else ""
        print(f"  {i:>3}. {j['title']}")
        print(f"       {j['company']}  |  {loc}  |  {dt}  |  [{j['source']}]")
        if j["link"]:
            print(f"       {j['link'][:80]}")
        print()

if __name__ == "__main__":
    main()
