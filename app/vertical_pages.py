"""
High-Intent Organic Vertical Destination Pages & Sitemap/Robots Generators for BillTally.
Each vertical route renders a focused, plain-English accounting utility landing page with:
- 1-click handoff into the pre-configured live BillTally workbench (`/?vertical=<slug>`)
- Vertical-specific error checklist & math rules
- SoftwareApplication + FAQPage JSON-LD structured data
- Zero B2B middleware leaks and zero Reddit/social posting bloat.
"""

import html
import json
import os
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode

from app.quota_manager import CHECK2QBO_COMPANION_URL

_TRACKING_PARAM_KEYS = ("gclid", "gbraid", "wbraid", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")


def get_google_ads_tag_id() -> str:
    raw = os.environ.get("GOOGLE_ADS_TAG_ID", "AW-18526471751").strip()
    if raw and all(ch.isalnum() or ch in ("-", "_") for ch in raw):
        return raw
    return "AW-18526471751"


def render_gtag_head(csp_nonce: str = "") -> str:
    """Return CSP-compliant Google Tag (gtag.js) snippet for Google Ads attribution & conversion tracking."""
    tag_id = get_google_ads_tag_id()
    if not tag_id:
        return ""
    nonce_attr = f' nonce="{_esc(csp_nonce)}"' if csp_nonce else ""
    t_esc = _esc(tag_id)
    return (
        f'  <script async src="https://www.googletagmanager.com/gtag/js?id={t_esc}"{nonce_attr}></script>\n'
        f'  <script{nonce_attr}>window.__BT_GADS_ID="{t_esc}";window.dataLayer=window.dataLayer||[];'
        f"function gtag(){{dataLayer.push(arguments);}}gtag('js',new Date());gtag('config','{t_esc}');</script>"
    )


def _merge_tracking_params(base_href: str, incoming_qs: str) -> str:
    if not incoming_qs:
        return base_href
    preserved = [(k, v) for k, v in parse_qsl(incoming_qs, keep_blank_values=False) if k.lower() in _TRACKING_PARAM_KEYS and v]
    if not preserved:
        return base_href
    sep = "&" if "?" in base_href else "?"
    return f"{base_href}{sep}{urlencode(preserved)}"

VERTICAL_PAGES: Dict[str, Dict[str, Any]] = {
    "bank-statement-to-qbo-csv": {
        "slug": "bank-statement-to-qbo-csv",
        "path": "/convert/bank-statement-to-qbo-csv",
        "preset_id": "bank_reconciliation_batch",
        "open_recon": True,
        "title": "Bank Statement to QuickBooks & Xero CSV Converter (Free Math Check)",
        "meta_description": (
            "Match monthly business checking statements against supplier bills, spot duplicate bank withdrawals "
            "and missing receipts, and export clean QuickBooks CSV or 3-tab Excel (.xlsx) files."
        ),
        "eyebrow": "Bookkeeper Utility · Bank Reconciliation & CSV Export",
        "h1": "Bank Statement to QuickBooks CSV Converter & Duplicate Charge Checker",
        "lead": (
            "Turn monthly checking withdrawals and supplier bills into a balanced QuickBooks CSV or 3-tab Excel "
            "workbook with live =SUM() formulas. Spots double-charged ACH debits, unpaid bills, and missing receipts before close."
        ),
        "cta_label": "Open Bank Statement Matcher & CSV Exporter →",
        "sample_callout": "Loads a real October business checking statement with 3 matched bills, 1 unpaid invoice, and 1 duplicate $1,250.00 debit caught automatically.",
        "checks": [
            ("Duplicate ACH & card debits", "Flags repeated withdrawals for the same vendor and dollar amount within your date tolerance window."),
            ("Missing-receipt bank withdrawals", "Lists every bank debit that has no matching supplier bill so you know exactly which receipts to request."),
            ("Unpaid supplier bills", "Separates approved bills that have not yet cleared the checking account."),
            ("QuickBooks-ready CSV & 3-tab Excel", "Exports clean columns with DDE-safe text and live =SUM() / =ROUND() accounting formulas."),
        ],
        "faqs": [
            ("Are my bank statements uploaded to train AI models?", "No. Plain text and CSV inputs are checked in ephemeral memory only, never stored permanently, and never used to train models."),
            ("What formats can I export for QuickBooks Online or Xero?", "You can download a QuickBooks-formatted CSV or a 3-tab Microsoft Excel (.xlsx) workbook with live =SUM() formulas."),
        ],
        "show_check2qbo_link": True,
    },
    "supplier-invoice": {
        "slug": "supplier-invoice",
        "path": "/check/supplier-invoice",
        "preset_id": "messy_saas_invoice",
        "open_recon": False,
        "title": "Supplier & Wholesale Invoice Math Checker (Catch Line-Item Overcharges)",
        "meta_description": (
            "Verify every Quantity x Unit Price line item, pallet credit, and sales tax total on wholesale food, "
            "beverage, and trade supplier invoices to the penny before approving payment."
        ),
        "eyebrow": "Wholesale, Restaurant & Trade AP Audit",
        "h1": "Supplier & Wholesale Invoice Math Checker",
        "lead": (
            "Check multi-line food distributor, linen, and trade supply bills to the penny before paying. "
            "Verifies every Quantity × Unit Price row, negative credit lines, and sales tax with fixed-decimal arithmetic."
        ),
        "cta_label": "Check a Supplier Invoice Free →",
        "sample_callout": "Loads a 5-line wholesale bakery & kitchen supply bill including a -$400.00 returned pallet deposit credit.",
        "checks": [
            ("Quantity × Unit Price tie-out", "Recalculates every row in fixed-decimal cents so silent extension typos cannot slip past AP."),
            ("Returned pallet & loyalty credits", "Verifies negative credit line items actually reduce the subtotal instead of being ignored or added."),
            ("Sales tax verification", "Checks that Subtotal + Sales Tax equals the billed Total Due to the exact penny."),
            ("1-click Verified Dispute Link", "Generates a read-only proof link and polite supplier email when an overcharge is caught."),
        ],
        "faqs": [
            ("Does BillTally work on PDF and photo supplier invoices?", "Yes. Drop a digital PDF, receipt photo (.png/.jpg/.webp), Excel sheet, or CSV directly on the workbench."),
            ("Why not just eyeball the subtotal?", "Distributors frequently mistype a single line extension or omit a credit memo; fixed-decimal line checks catch errors in seconds."),
        ],
        "show_check2qbo_link": False,
    },
    "contractor-invoice": {
        "slug": "contractor-invoice",
        "path": "/check/contractor-invoice",
        "preset_id": "discrepant_contractor_invoice",
        "open_recon": False,
        "title": "Contractor Invoice Math & Overcharge Checker (With Dispute Note)",
        "meta_description": (
            "Check plumbing, electrical, HVAC, and repair contractor invoices for labor-hour math mistakes, "
            "tax errors, and 1099-NEC review flags. Drafts a polite supplier correction email in 1 click."
        ),
        "eyebrow": "Trades, Repairs & 1099-NEC Contractor Audit",
        "h1": "Contractor Invoice Math & Overcharge Checker",
        "lead": (
            "Catch mistyped labor hours, inflated line extensions, and tax calculation mistakes on plumbing, HVAC, "
            "and repair bills before cutting the check. Includes a 1099-NEC review flag and a polite correction note."
        ),
        "cta_label": "Audit a Contractor Invoice Free →",
        "sample_callout": "Loads a commercial plumbing repair bill with a hidden +$200.00 overcharge on Line 3 (14 hrs × $165.00 billed as $2,510.00).",
        "checks": [
            ("Labor hours × hourly rate check", "Catches arithmetic slips on after-hours labor, trip fees, and materials line items."),
            ("Short-pay vs. billed export toggle", "Choose whether your Excel or QuickBooks CSV records the verified true math total or the original paper figure."),
            ("1099-NEC service review flag", "Highlights service-based contractor bills so you remember to collect a W-9 before year-end."),
            ("Polite supplier dispute packet", "Generates a calm, line-by-line correction note with a shareable Verified Audit Link."),
        ],
        "faqs": [
            ("How do I share an overcharge finding with my contractor?", "Click 'Copy Verified Dispute Link' on the workbench to get a clean, read-only math breakdown page you can paste into an email."),
            ("Can I export the corrected total to Excel?", "Yes. Toggle 'Use Verified Math Total' and download a 3-tab Excel workbook with live =SUM() formulas."),
        ],
        "show_check2qbo_link": False,
    },
    "cam-reconciliation": {
        "slug": "cam-reconciliation",
        "path": "/check/cam-reconciliation",
        "preset_id": "cam_reconciliation_statement",
        "open_recon": False,
        "title": "Commercial Lease CAM Reconciliation & NNN Expense Audit Checker",
        "meta_description": (
            "Verify annual commercial lease CAM reconciliation statements and NNN operating expense true-ups "
            "for line-item math errors, pro-rata share mistakes, and overbilled admin fees."
        ),
        "eyebrow": "Commercial Tenants & Property Managers · NNN / CAM Audit",
        "h1": "Commercial Lease CAM Reconciliation & NNN Statement Checker",
        "lead": (
            "Annual Common Area Maintenance (CAM) true-ups often contain pro-rata math mistakes or misapplied "
            "monthly escrow credits. Verify every operating-expense line to the penny and generate a clean audit link."
        ),
        "cta_label": "Audit a CAM Statement Free →",
        "sample_callout": "Loads an annual commercial retail CAM reconciliation statement with a +$350.00 math overcharge in the pro-rata subtotal.",
        "checks": [
            ("Operating expense line-item tie-out", "Verifies landscaping, snow removal, property insurance, and management fee extensions to the penny."),
            ("Monthly CAM escrow credit check", "Confirms your 12 monthly estimated CAM payments are properly subtracted from the annual balance due."),
            ("Printable audit proof page", "Creates a clean, read-only verification receipt with SHA-256 checksum to attach to landlord correspondence."),
            ("Multi-tab Excel workpaper", "Exports Executive Summary and Normalized Line Items tabs with live =SUM() formulas for your CPA."),
        ],
        "faqs": [
            ("What is a CAM reconciliation statement?", "It is the landlord's annual true-up comparing actual building Common Area Maintenance costs against the estimated monthly CAM fees you already paid."),
            ("Does BillTally save my lease or CAM numbers?", "No. Your statement is verified in ephemeral memory and never retained for model training."),
        ],
        "show_check2qbo_link": False,
    },
}


def _esc(val: Any) -> str:
    return html.escape(str(val if val is not None else ""), quote=True)


def _safe_jsonld(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def render_vertical_page_html(
    slug: str,
    public_base_url: str = "",
    *,
    csp_nonce: str = "",
    query_string: str = "",
) -> str:
    """Render an SEO-ready, plain-English BillTally vertical destination page."""
    cfg = VERTICAL_PAGES[slug]
    base = (public_base_url or "https://billtally.app").rstrip("/")
    canonical_url = f"{base}{cfg['path']}"
    og_image = f"{base}/icon.png"
    workbench_href = _merge_tracking_params(f"/?vertical={cfg['slug']}", query_string)
    upload_href = _merge_tracking_params(
        f"/?vertical={cfg['slug']}&mode=upload" if cfg.get("open_recon") else "/?mode=upload",
        query_string,
    )
    gtag_html = render_gtag_head(csp_nonce)

    app_ld = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": f"BillTally — {cfg['h1']}",
        "applicationCategory": "FinanceApplication",
        "operatingSystem": "Web",
        "url": canonical_url,
        "description": cfg["meta_description"],
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
    }
    faq_ld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in cfg["faqs"]
        ],
    }

    checks_html = "".join(
        f'<div class="check-item"><h3>{_esc(title)}</h3><p>{_esc(desc)}</p></div>'
        for title, desc in cfg["checks"]
    )
    faqs_html = "".join(
        f'<details class="faq-item"><summary>{_esc(q)}</summary><p>{_esc(a)}</p></details>'
        for q, a in cfg["faqs"]
    )
    other_links = "".join(
        f'<a class="pill-link" href="{_esc(v["path"])}">{_esc(v["h1"])}</a>'
        for k, v in VERTICAL_PAGES.items()
        if k != slug
    )
    companion_html = (
        f'<p class="companion">Need scanned PDF checks converted directly to QuickBooks <code>.QBO</code>? '
        f'<a href="{_esc(CHECK2QBO_COMPANION_URL)}" target="_blank" rel="noopener noreferrer">Try Check2QBO →</a></p>'
        if cfg.get("show_check2qbo_link")
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="color-scheme" content="light" />
  <title>{_esc(cfg['title'])} | BillTally</title>
  <meta name="description" content="{_esc(cfg['meta_description'])}" />
  <link rel="canonical" href="{_esc(canonical_url)}" />
  <meta property="og:type" content="website" />
  <meta property="og:title" content="{_esc(cfg['title'])} | BillTally" />
  <meta property="og:description" content="{_esc(cfg['meta_description'])}" />
  <meta property="og:url" content="{_esc(canonical_url)}" />
  <meta property="og:image" content="{_esc(og_image)}" />
  <meta name="twitter:card" content="summary" />
  <meta name="twitter:title" content="{_esc(cfg['title'])} | BillTally" />
  <meta name="twitter:description" content="{_esc(cfg['meta_description'])}" />
  <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
  <script type="application/ld+json">{_safe_jsonld(app_ld)}</script>
  <script type="application/ld+json">{_safe_jsonld(faq_ld)}</script>
{gtag_html}
  <style>
    :root {{
      color-scheme: light;
      --ground:#f8f8f8; --surface:#ffffff; --border:#e6e6e6; --text:#0a0a0a; --muted:#595959; --accent:#141414;
      --pill-ok-bg:#dcfae5; --pill-ok-ink:#04250e;
      --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      --mono:ui-monospace,SFMono-Regular,Menlo,monospace;
    }}
    * {{ box-sizing:border-box; margin:0; padding:0; }}
    body {{ background:var(--ground); color:var(--text); font-family:var(--sans); font-size:15px; line-height:1.6; padding:24px 16px 64px; }}
    .wrap {{ max-width:880px; margin:0 auto; }}
    nav.top {{ display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:12px; padding-bottom:18px; border-bottom:1px solid var(--border); margin-bottom:28px; }}
    .brand {{ font-weight:600; font-size:15px; color:var(--text); text-decoration:none; }}
    .nav-links {{ display:flex; flex-wrap:wrap; gap:14px; font-size:13px; }}
    .nav-links a {{ color:var(--muted); text-decoration:none; }}
    .nav-links a:hover {{ color:var(--text); text-decoration:underline; }}
    .eyebrow {{ display:inline-block; font-family:var(--mono); font-size:11.5px; background:var(--pill-ok-bg); color:var(--pill-ok-ink); padding:3px 9px; border-radius:4px; margin-bottom:12px; font-weight:600; }}
    h1 {{ font-size:30px; line-height:1.2; letter-spacing:-0.02em; font-weight:600; margin-bottom:12px; }}
    .lead {{ font-size:16px; color:var(--muted); max-width:720px; margin-bottom:20px; }}
    .cta-card {{ background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:22px; margin-bottom:24px; }}
    .cta-row {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-bottom:10px; }}
    .btn {{ display:inline-flex; align-items:center; gap:6px; min-height:42px; padding:9px 18px; border-radius:6px; border:1px solid #949494; background:#eeeeee; color:var(--text); font-size:14px; font-weight:600; text-decoration:none; }}
    .btn-primary {{ background:var(--accent); color:#ffffff; border-color:var(--accent); }}
    .btn-primary:hover {{ background:#2b2b2b; }}
    .sample-note {{ font-size:13px; color:var(--muted); }}
    .privacy-bar {{ display:flex; flex-wrap:wrap; gap:10px 18px; font-size:12.5px; color:var(--muted); margin-top:14px; padding-top:14px; border-top:1px solid var(--border); }}
    h2 {{ font-size:18px; font-weight:600; margin:24px 0 12px; }}
    .checks-grid {{ display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:12px; }}
    .check-item {{ background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:16px; }}
    .check-item h3 {{ font-size:14.5px; font-weight:600; margin-bottom:4px; }}
    .check-item p {{ font-size:13.5px; color:var(--muted); }}
    .faq-item {{ background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:12px 16px; margin-bottom:8px; }}
    .faq-item summary {{ font-weight:600; cursor:pointer; font-size:14px; }}
    .faq-item p {{ margin-top:8px; font-size:13.5px; color:var(--muted); }}
    .other-wrap {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }}
    .pill-link {{ display:inline-flex; align-items:center; padding:8px 12px; border-radius:6px; background:var(--surface); border:1px solid var(--border); font-size:13px; color:var(--text); text-decoration:none; }}
    .pill-link:hover {{ border-color:var(--accent); }}
    .companion {{ margin-top:16px; font-size:13.5px; color:var(--muted); }}
    .companion a {{ color:var(--text); font-weight:600; }}
    a:focus-visible, summary:focus-visible {{ outline:2px solid #0b57d0; outline-offset:2px; }}
    @media (max-width: 640px) {{
      h1 {{ font-size:24px; }}
      .checks-grid {{ grid-template-columns:1fr; }}
    }}
    @media (max-width: 768px), (pointer: coarse) {{
      .btn, .nav-links a, .pill-link, .brand, .companion a {{ min-height:44px; display:inline-flex; align-items:center; }}
      .faq-item summary {{ display:list-item; padding:10px 0; min-height:44px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <nav class="top" aria-label="Primary navigation">
      <a class="brand" href="/">BillTally · Bill &amp; Bank Check Desk</a>
      <div class="nav-links">
        <a href="/">Open Workbench</a>
        <a href="/docs">Documentation</a>
        <a href="/privacy">Privacy</a>
        <a href="/about">About</a>
      </div>
    </nav>

    <main>
      <span class="eyebrow">{_esc(cfg['eyebrow'])}</span>
      <h1>{_esc(cfg['h1'])}</h1>
      <p class="lead">{_esc(cfg['lead'])}</p>

      <section class="cta-card" aria-label="Launch pre-configured workbench">
        <div class="cta-row">
          <a class="btn btn-primary" href="{_esc(upload_href)}">{'Upload & Convert My Bank CSV Now →' if cfg.get('open_recon') else 'Upload Your Own PDF / CSV →'}</a>
          <a class="btn" href="{_esc(workbench_href)}">{_esc(cfg['cta_label'])}</a>
        </div>
        <p class="sample-note"><strong>1-Click Sample Ready:</strong> {_esc(cfg['sample_callout'])}</p>
        <div class="privacy-bar">
          <span><strong>Local-First Privacy:</strong> Plain text &amp; CSV checked in-browser/ephemeral memory.</span>
          <span><strong>Fixed-Decimal Math:</strong> Zero rounding guesswork.</span>
          <span><strong>No Signup Required:</strong> Free instant audit.</span>
        </div>
      </section>

      <h2>What BillTally Checks Automatically</h2>
      <div class="checks-grid">
        {checks_html}
      </div>

      <h2>Frequently Asked Questions</h2>
      <div>
        {faqs_html}
      </div>
      {companion_html}

      <h2>More Free BillTally Checkers</h2>
      <div class="other-wrap">
        {other_links}
      </div>
    </main>
  </div>
</body>
</html>"""


def render_sitemap_xml(public_base_url: str) -> str:
    """Generate a standards-compliant sitemap.xml covering the workbench, docs, and all vertical pages."""
    base = (public_base_url or "https://billtally.app").rstrip("/")
    paths: List[str] = ["/", "/about", "/docs", "/privacy", "/terms"] + [v["path"] for v in VERTICAL_PAGES.values()]
    urls = "".join(f"  <url><loc>{_esc(base + p)}</loc></url>\n" for p in paths)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n'


def render_robots_txt(public_base_url: str) -> str:
    base = (public_base_url or "https://billtally.app").rstrip("/")
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /v/\n"
        "Disallow: /api/\n"
        "Disallow: /downloads/\n"
        "Disallow: /analytics\n"
        "Disallow: /oauth/\n"
        "Disallow: /webhooks/\n"
        "Disallow: /openapi-docs\n"
        "Disallow: /manifests/\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
