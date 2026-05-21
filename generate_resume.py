#!/usr/bin/env python3
"""
Resume generator — importable module + standalone script.

Import:   from generate_resume import create_resume, make_headline, make_summary
Standalone: python generate_resume.py  (regenerates the Truewerk resume)
"""

import os, re, json
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, HRFlowable, Table, TableStyle

W, H = letter
TAILORED_DIR = Path(r"C:\Users\Mark\Jobsearch\Tailored_Resumes")

# ── Claude bullet tailoring ───────────────────────────────────────────────────

# Default bullets (used as fallback and as input to Claude)
DEFAULT_BULLETS = {
    "viega_demand": [
        "Own SKU-level demand forecasting for the company’s largest portfolio, consolidating historical demand, seasonality, and commercial inputs into a single consensus operating forecast",
        "Lead monthly S&amp;OP demand reviews with Sales and Operations, clearly framing forecast risks, channel opportunities, and drivers of change",
        "Improved forecast accuracy by ~10%, sustaining &gt;80% WAPE across portfolio; managed bias systematically to prevent over- and under-forecasting",
        "Built anomaly detection model (standard deviation + kurtosis) to identify non-organic ordering behavior and prevent downstream supply distortion",
    ],
    "viega_supply": [
        "Owned inventory strategy end-to-end, including safety stock, inventory targets, and replenishment logic",
        "Built Power BI–driven statistical safety stock engine, reducing excess inventory by ~5%",
        "Developed scalable inventory target framework integrating safety stock and lot-size logic",
        "Ensured inventory positioning supported fulfillment performance and service levels",
    ],
    "forum_brands": [
        "Planned and managed demand across 4 international markets and 7 fulfillment locations, supporting channel allocation across Amazon, DTC, and wholesale accounts",
        "Maintained &lt;1% out-of-stock rate during peak demand and COVID disruption through pre-season forecasting and inventory positioning across channels",
        "Led demand planning and launch of Amazon Canada, driving ~10% incremental revenue",
        "Built SQL/Looker dashboards and automated reporting, improving forecast vs. actual visibility and decision speed",
        "Automated shipment tracking processes, eliminating 15+ hours of manual work weekly",
    ],
}

# Plain-text versions sent to Claude (no HTML entities)
_PLAIN_BULLETS = {
    "viega_demand": [
        "Own SKU-level demand forecasting for the company's largest portfolio, consolidating historical demand, seasonality, and commercial inputs into a single consensus operating forecast",
        "Lead monthly S&OP demand reviews with Sales and Operations, clearly framing forecast risks, channel opportunities, and drivers of change",
        "Improved forecast accuracy by ~10%, sustaining >80% WAPE across portfolio; managed bias systematically to prevent over- and under-forecasting",
        "Built anomaly detection model (standard deviation + kurtosis) to identify non-organic ordering behavior and prevent downstream supply distortion",
    ],
    "viega_supply": [
        "Owned inventory strategy end-to-end, including safety stock, inventory targets, and replenishment logic",
        "Built Power BI-driven statistical safety stock engine, reducing excess inventory by ~5%",
        "Developed scalable inventory target framework integrating safety stock and lot-size logic",
        "Ensured inventory positioning supported fulfillment performance and service levels",
    ],
    "forum_brands": [
        "Planned and managed demand across 4 international markets and 7 fulfillment locations, supporting channel allocation across Amazon, DTC, and wholesale accounts",
        "Maintained <1% out-of-stock rate during peak demand and COVID disruption through pre-season forecasting and inventory positioning across channels",
        "Led demand planning and launch of Amazon Canada, driving ~10% incremental revenue",
        "Built SQL/Looker dashboards and automated reporting, improving forecast vs. actual visibility and decision speed",
        "Automated shipment tracking processes, eliminating 15+ hours of manual work weekly",
    ],
}

def _load_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        env_file = Path(r"C:\Users\Mark\Jobsearch\.env")
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    key = line.split("=", 1)[1].strip()
    return key

def _html_escape(text):
    return (text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("’", "'")
        .replace("–", "–"))

def tailor_bullets(jd_text, title, company):
    """
    Use Claude to rewrite the 3 key role bullet sets to match the job description.
    Returns dict with keys viega_demand, viega_supply, forum_brands.
    Falls back to DEFAULT_BULLETS if API key is unavailable or call fails.
    """
    api_key = _load_api_key()
    if not api_key:
        print("    [No ANTHROPIC_API_KEY — using default bullets]")
        return DEFAULT_BULLETS

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        bullet_block = ""
        for role, label in [
            ("viega_demand",  "Viega LLC — Senior Demand Planner"),
            ("viega_supply",  "Viega LLC — Senior Supply Planner"),
            ("forum_brands",  "Forum Brands — Supply Chain Specialist"),
        ]:
            bullet_block += f"\n[{label}]\n"
            for i, b in enumerate(_PLAIN_BULLETS[role], 1):
                bullet_block += f"{i}. {b}\n"

        prompt = f"""You are an elite executive resume writer for supply chain and demand planning roles.

TARGET ROLE: {title} at {company}

JOB DESCRIPTION:
{jd_text[:3000]}

CURRENT BULLETS TO REWRITE:
{bullet_block}

RULES:
- Rewrite/reorder bullets to emphasize what this JD prioritizes most
- Keep ALL existing metrics intact (%, $, numbers) — never fabricate new ones
- Use strong action verbs: Optimized, Engineered, Spearheaded, Systematized, Formulated, Reconfigured, Negotiated
- No weak language: facilitated, assisted, helped, supported, passionate, dynamic
- Each bullet must be under 155 characters
- Keep same bullet count per role: viega_demand=4, viega_supply=4, forum_brands=5
- Return ONLY valid JSON, no explanation, no markdown

JSON format:
{{
  "viega_demand": ["bullet1", "bullet2", "bullet3", "bullet4"],
  "viega_supply": ["bullet1", "bullet2", "bullet3", "bullet4"],
  "forum_brands": ["bullet1", "bullet2", "bullet3", "bullet4", "bullet5"]
}}"""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)

        # Validate structure and escape HTML
        result = {}
        for key, count in [("viega_demand", 4), ("viega_supply", 4), ("forum_brands", 5)]:
            bullets = data.get(key, [])
            if len(bullets) < count:
                bullets += _PLAIN_BULLETS[key][len(bullets):]
            result[key] = [_html_escape(b) for b in bullets[:count]]

        return result

    except Exception as e:
        print(f"    [Claude tailoring failed: {e} — using default bullets]")
        return DEFAULT_BULLETS

# ── Headline / summary generators ─────────────────────────────────────────────

def make_headline(title):
    t = title.lower()
    if any(w in t for w in ["demand plan", "demand manager"]):
        return "DEMAND PLANNER | FORECASTING & S&OP LEADER"
    if any(w in t for w in ["supply plan", "supply chain plan"]):
        return "SUPPLY PLANNER | INVENTORY & OPERATIONS LEADER"
    if any(w in t for w in ["inventory plan", "inventory manager"]):
        return "INVENTORY PLANNING LEADER | SUPPLY CHAIN OPERATIONS"
    if any(w in t for w in ["s&op", "sales and operations"]):
        return "S&OP LEADER | DEMAND PLANNING & SUPPLY CHAIN"
    if any(w in t for w in ["supply chain manager", "supply chain director", "supply chain lead"]):
        return "SUPPLY CHAIN LEADER | PLANNING & OPERATIONS"
    clean = re.sub(r"[^A-Za-z0-9\s&/]", "", title).strip().upper()
    return f"{clean} | SUPPLY CHAIN & OPERATIONS LEADER"


def make_summary(title, company, jd_text=""):
    t = (title + " " + jd_text).lower()
    if any(w in t for w in ["wape", "bias", "forecast accuracy", "demand sens"]):
        focus = "forecast accuracy, WAPE/bias management, and S&OP alignment"
    elif any(w in t for w in ["inventory optim", "safety stock", "replenishment", "weeks of supply"]):
        focus = "inventory optimization, replenishment strategy, and safety stock modeling"
    elif any(w in t for w in ["s&op", "sales and operations planning", "integrated business"]):
        focus = "S&OP process leadership, cross-functional alignment, and demand-supply integration"
    else:
        focus = "forecast accuracy, inventory efficiency, and S&OP alignment"

    co = f" at {company}" if company else ""
    return (
        f"Supply chain and demand planning leader with 10+ years of experience driving {focus} "
        f"across multi-channel environments. Targeting the {title} role{co} with proven expertise "
        f"in statistical forecasting, WAPE/bias management, and translating demand signals into "
        f"actionable inventory and supply decisions across DTC, Amazon, and wholesale channels."
    )


def safe_filename(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s[:40]


def _clean_title(title, company):
    """
    Strip brand/company prefix from title.
    Handles 'Smartwool: Senior Demand Planner' and 'Altra: Associate Demand Planner'
    where the prefix before ':' overlaps with the company name.
    """
    if ":" in title:
        prefix, rest = title.split(":", 1)
        prefix_l  = prefix.strip().lower()
        company_l = company.strip().lower()
        # Strip if prefix is a substring of company name or vice versa
        if prefix_l in company_l or company_l in prefix_l:
            return rest.strip()
    return title

def output_path_for(company, title):
    title = _clean_title(title, company)
    return TAILORED_DIR / f"Mark_Izrailev_Resume_{safe_filename(company)}_{safe_filename(title)}.pdf"


# ── PDF builder ────────────────────────────────────────────────────────────────

def _build_story(f, headline, summary, bullets=None):
    LM = RM = 0.50 * inch
    CW = W - LM - RM

    BODY = 8.0 * f
    LEAD = 10.0 * f
    NAME = 20.0 * f
    SEC  = 9.5  * f
    JOB  = 8.5  * f
    SB_SEC = 4.0 * f
    SB_JOB = 2.5 * f

    def ps(name, **kw):
        d = dict(fontName="Helvetica", fontSize=BODY, leading=LEAD, spaceAfter=0, spaceBefore=0)
        d.update(kw)
        return ParagraphStyle(name, **d)

    S_name    = ps("name",    fontName="Helvetica-Bold", fontSize=NAME, leading=NAME*1.15, spaceAfter=f)
    S_contact = ps("contact", fontSize=8.5*f, textColor=colors.HexColor("#444444"), spaceAfter=2*f)
    S_title   = ps("title",   fontName="Helvetica-Bold", fontSize=SEC, spaceBefore=2*f, spaceAfter=2*f)
    S_summary = ps("summary", fontSize=BODY, leading=LEAD, leftIndent=4, spaceAfter=2*f)
    S_section = ps("section", fontName="Helvetica-Bold", fontSize=SEC, spaceBefore=SB_SEC, spaceAfter=f)
    S_job_l   = ps("job_l",   fontName="Helvetica-Bold", fontSize=JOB, leading=LEAD)
    S_job_r   = ps("job_r",   fontSize=8*f, leading=LEAD, alignment=TA_RIGHT)
    S_bullet  = ps("bullet",  fontSize=BODY, leading=LEAD, leftIndent=8*f)

    def hr(before=0, after=None):
        return HRFlowable(width="100%", thickness=0.4, color=colors.black,
                          spaceBefore=before, spaceAfter=after if after is not None else 2*f)

    def section(t):
        return [Paragraph(t, S_section), hr()]

    def job_row(left, right):
        return Table(
            [[Paragraph(left, S_job_l), Paragraph(right, S_job_r)]],
            colWidths=[CW * 0.60, CW * 0.40],
            style=TableStyle([
                ("VALIGN",        (0,0), (-1,-1), "TOP"),
                ("LEFTPADDING",   (0,0), (-1,-1), 0),
                ("RIGHTPADDING",  (0,0), (-1,-1), 0),
                ("TOPPADDING",    (0,0), (-1,-1), SB_JOB),
                ("BOTTOMPADDING", (0,0), (-1,-1), 0),
            ])
        )

    def b(text):
        return Paragraph(f"• {text}", S_bullet)

    bl = bullets or DEFAULT_BULLETS

    story = []

    # Header
    story += [
        Paragraph("Mark Izrailev", S_name),
        Paragraph("Highlands Ranch, CO • (303) 875-7999 • Izrailev.Mark@gmail.com", S_contact),
        hr(before=0),
        Paragraph(headline, S_title),
        Paragraph(summary, S_summary),
    ]

    story += section("WORK EXPERIENCE")

    story += [job_row("Viega LLC — Senior Demand Planner", "June 2025 – Present | Broomfield, CO")]
    story += [b(bullet) for bullet in bl["viega_demand"]]

    story += [job_row("Viega LLC — Senior Supply Planner", "June 2024 – June 2025")]
    story += [b(bullet) for bullet in bl["viega_supply"]]

    story += [
        job_row("MIGG Consulting / SupplyCaddy — Principal / Interim Director of Logistics", "Sept 2023 – June 2024 | Remote"),
        b("Owned fulfillment operations across domestic and international networks, including 3PL performance, inventory flow, and order execution"),
        b("Managed 3PL partners against defined service expectations (speed, accuracy, receiving), improving time-to-serve by ~15%"),
        b("Led ERP/OMS implementation, defining workflows and ensuring data integrity across operations, inventory, and finance"),
        b("Reduced warehousing and fulfillment costs by ~5% through process improvements and partner negotiation"),
        b("Built processes to improve order accuracy and systematically resolve fulfillment issues"),
    ]

    story += [job_row("Forum Brands — Supply Chain Specialist", "Dec 2021 – Dec 2022 | New York, NY / Remote")]
    story += [b(bullet) for bullet in bl["forum_brands"]]

    story += [
        job_row("Unilever — Transportation Specialist", "Dec 2020 – Dec 2021 | Remote"),
        b("Managed carrier performance against delivery KPIs and service expectations"),
        b("Built exception management tool for outbound shipments, reducing manual tracking by ~100 hours per week"),
        b("Improved shipment visibility and accountability across network"),
    ]

    story += [
        job_row("Unilever — Factory Transportation Planner", "May 2020 – Dec 2020"),
        b("Coordinated transportation planning across 30+ manufacturing sites"),
        b("Identified and resolved SAP/TMS execution issues impacting operations"),
    ]

    story += [
        job_row("Cargo Systems — Supply Chain Associate", "Apr 2019 – Jan 2020 | New York, NY"),
        b("Managed end-to-end supply chain execution for campaigns generating $6M+ in revenue"),
        b("Managed 3PL warehouse partners and led warehouse transition, delivering ~$60K annual savings"),
        b("Reduced delivery times by ~60% through carrier renegotiation and process improvements"),
        b("Built returns and refurbishment strategy, reusing 10,000+ devices and generating $100K+ in savings"),
    ]

    story += [
        job_row("HelloFresh — Analyst, Supply Chain Planning &amp; Analytics", "Jan 2018 – Apr 2019 | New York, NY"),
        b("Built and managed data structures supporting forecasting, procurement, and fulfillment operations"),
        b("Improved produce quality by ~20% across three fulfillment centers"),
    ]

    story += [
        job_row("Samsung Electronics America — Financial Analyst (Operations)", "Oct 2016 – Jan 2018 | NJ"),
        b("Managed $15M+ in logistics and warehousing costs"),
        b("Partnered with 50+ vendors to ensure adherence to operational KPIs and budgets"),
    ]

    story += section("TECHNICAL SKILLS")
    story += [
        b("<b>Demand Planning &amp; S&amp;OP:</b> SKU-Level Forecasting, Bias &amp; WAPE Management, Seasonal &amp; Channel Forecasting, Inventory Optimization, Replenishment"),
        b("<b>Systems:</b> NetSuite, SAP, Oracle TMS, Netstock, Power BI, Tableau, Looker"),
        b("<b>Data &amp; Analytics:</b> SQL, Python, Snowflake, Databricks, Excel"),
    ]

    story += section("EDUCATION")
    story.append(Paragraph("Rutgers University — B.A. Economics", S_bullet))

    return story


def _build_to_file(path, f, headline, summary, bullets=None):
    LM = RM = 0.50 * inch
    TM = BM = (0.42 * f) * inch
    story = _build_story(f, headline, summary, bullets)
    page_nums = []
    def track(canvas, doc):
        page_nums.append(canvas.getPageNumber())
    doc = SimpleDocTemplate(str(path), pagesize=letter,
        leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
    doc.build(story, onFirstPage=track, onLaterPages=track)
    return max(page_nums) if page_nums else 1


def create_resume(output_path, headline, summary, bullets=None):
    """
    Generate a one-page tailored PDF resume.
    bullets: dict with keys viega_demand, viega_supply, forum_brands (from tailor_bullets()).
    Binary-searches for the largest scale factor that still fits on one page.
    Returns output_path.
    """
    output_path = str(output_path)
    temp_path   = output_path.replace(".pdf", "_tmp.pdf")

    lo, hi = 1.0, 1.40
    for _ in range(14):
        mid = (lo + hi) / 2
        pages = _build_to_file(temp_path, mid, headline, summary, bullets)
        if pages == 1:
            lo = mid
        else:
            hi = mid

    _build_to_file(output_path, lo, headline, summary, bullets)
    if os.path.exists(temp_path):
        os.remove(temp_path)
    return output_path


# ── Standalone entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    out = TAILORED_DIR / "Mark_Izrailev_Resume_Truewerk_DemandPlanner.pdf"
    create_resume(
        out,
        headline="DEMAND PLANNER | FORECASTING & S&OP LEADER",
        summary=(
            "Demand planning leader with 10+ years of experience driving forecast accuracy, inventory efficiency, and S&OP "
            "alignment across multi-channel environments. Proven track record building statistical forecasting models, managing "
            "WAPE and bias, and translating demand signals into actionable inventory and supply decisions across DTC, Amazon, and wholesale channels."
        ),
    )
    print(f"Generated: {out}")
