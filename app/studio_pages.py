"""
Public HTML Pages for BillTally MCP (`/docs`, `/documentation`, `/about`, `/privacy`, `/terms`).
Styled with the `achromatic-ledger` design system (`#f8f8f8` paper ground, `#ffffff` surface card,
Geist & Geist Mono tabular numerals, zero em-dashes).
"""

BILLTALLY_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">'
    '<rect width="48" height="48" rx="11" fill="#111827" stroke="#374151" stroke-width="2"/>'
    '<rect x="8" y="8" width="23" height="26" rx="3" fill="#1F2937" stroke="#4B5563" stroke-width="1.2"/>'
    '<rect x="11.5" y="10.5" width="26" height="27.5" rx="3.5" fill="#F8FAFC" stroke="#E2E8F0" stroke-width="1.2"/>'
    '<path d="M11.5 14C11.5 12.1 13.1 10.5 15 10.5H34C35.9 10.5 37.5 12.1 37.5 14V16.5H11.5V14Z" fill="#141414"/>'
    '<rect x="14" y="12.7" width="9" height="1.8" rx="0.9" fill="#F8FAFC"/>'
    '<rect x="29.5" y="12.7" width="5.5" height="1.8" rx="0.9" fill="#34D399"/>'
    '<rect x="14" y="19.5" width="11" height="2" rx="1" fill="#475569"/>'
    '<rect x="27.5" y="19" width="7.5" height="3" rx="1.2" fill="#DCFCE7"/>'
    '<rect x="14" y="24.5" width="9.5" height="2" rx="1" fill="#475569"/>'
    '<rect x="27.5" y="24" width="7.5" height="3" rx="1.2" fill="#DCFCE7"/>'
    '<rect x="14" y="29.5" width="10.5" height="2" rx="1" fill="#475569"/>'
    '<rect x="27.5" y="29" width="7.5" height="3" rx="1.2" fill="#FEE2E2"/>'
    '<circle cx="35" cy="35" r="6.5" fill="#16A34A" stroke="#F8FAFC" stroke-width="1.5"/>'
    '<path d="M32.3 35.1L34.1 36.9L37.9 33.1" stroke="#FFFFFF" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    "</svg>"
)

SHARED_PAGE_STYLE = """
  <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
  <link rel="icon" type="image/png" href="/icon.png" />
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;700&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --ground: #f8f8f8; --surface: #ffffff; --border: #e6e6e6; --text: #0a0a0a;
      --muted: #6b6b6b; --accent: #141414; --positive: #2e7d32; --chart-3: #1d5fbf;
      --sans: "Geist", -apple-system, BlinkMacSystemFont, sans-serif;
      --mono: "Geist Mono", ui-monospace, SFMono-Regular, monospace;
    }
    * { box-sizing: border-box; }
    body { background: var(--ground); color: var(--text); font-family: var(--sans); margin: 0; padding: 40px 20px; line-height: 1.65; font-size: 15px; }
    main { max-width: 840px; margin: 0 auto; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 36px 40px; }
    nav.top-nav { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; padding-bottom: 18px; margin-bottom: 24px; border-bottom: 1px solid var(--border); font-size: 13.5px; }
    nav.top-nav .links { display: flex; gap: 18px; }
    h1 { font-size: 26px; font-weight: 600; letter-spacing: -0.02em; margin: 0 0 8px; color: var(--text); }
    h2 { font-size: 17px; font-weight: 600; margin: 28px 0 8px; color: var(--text); }
    p, li { color: var(--text); max-width: 72ch; }
    ul { padding-left: 20px; }
    li { margin-bottom: 6px; }
    code { font-family: var(--mono); background: #f2f2f2; padding: 2px 6px; border-radius: 4px; font-size: 13px; }
    table { width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 13.5px; }
    th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }
    th { font-weight: 500; color: var(--muted); background: var(--ground); }
    a { color: var(--chart-3); text-decoration: none; font-weight: 500; }
    a:hover { text-decoration: underline; }
  </style>
"""

TOP_NAV_HTML = """
  <nav class="top-nav" aria-label="Public page navigation">
    <a href="/">← Return to BillTally Check Desk</a>
    <div class="links">
      <a href="/about">About</a>
      <a href="/docs">Documentation</a>
      <a href="/privacy">Privacy Policy</a>
      <a href="/terms">Terms</a>
    </div>
  </nav>
"""


def render_docs_html() -> str:
    """Return the Public User & IT Administrator Documentation page for Claude/ChatGPT MCP review."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>User &amp; IT Admin Documentation | BillTally: Bill Math Checker &amp; Bank Statement Matcher</title>
  {SHARED_PAGE_STYLE}
</head>
<body>
  <main>
    {TOP_NAV_HTML}
    <h1>User &amp; IT Administrator Documentation</h1>
    <p><strong>Connector Name:</strong> BillTally: Bill Math Checker &amp; Bank Statement Matcher<br/>
    <strong>Remote MCP Endpoint:</strong> <code>https://schemaextract-mcp-production.up.railway.app/mcp</code><br/>
    <strong>Support Contact:</strong> <a href="mailto:mulak1@gmail.com">mulak1@gmail.com</a></p>

    <h2>1. Overview for Bookkeepers, Accountants &amp; Small Business Teams</h2>
    <p>BillTally connects directly to Claude and ChatGPT to turn supplier bills, receipts, and monthly bank statements into verified spreadsheets. It checks every line item (Quantity multiplied by Unit Price) and sales tax total to the penny using fixed-decimal arithmetic, matches bills against bank withdrawals to catch duplicate charges, and exports multi-tab Microsoft Excel (<code>.xlsx</code>) workbooks with live <code>=SUM()</code> and <code>=ROUND()</code> formulas or accounting CSV files.</p>

    <h2>2. Security &amp; IT Administrator Review Summary</h2>
    <ul>
      <li><strong>100% Read-Only &amp; Idempotent Tools:</strong> All three exposed MCP tools (<code>extract_financial_documents</code>, <code>reconcile_invoices_with_bank_ledger</code>, and <code>export_ledger_bundle</code>) are strictly stateless, read-only (<code>readOnlyHint: true</code>), non-destructive (<code>destructiveHint: false</code>), and closed-world (<code>openWorldHint: false</code>). The connector cannot mutate, delete, or modify any external accounting systems, bank accounts, or user records.</li>
      <li><strong>Zero Model Training &amp; Ephemeral Memory:</strong> Submitted bill text, bank statement rows, and generated spreadsheet exports are processed in ephemeral memory solely to fulfill the immediate request. No customer financial documents are stored in persistent databases or used to train AI models.</li>
      <li><strong>Transport &amp; Authentication Security:</strong> All traffic is encrypted over HTTPS (TLS 1.3). The server works immediately for read-only evaluation without external setup and also supports OAuth 2.1 with S256 PKCE discovery at <code>/.well-known/oauth-authorization-server</code>.</li>
    </ul>

    <h2>3. Included MCP Tools &amp; Permission Scope</h2>
    <table>
      <thead>
        <tr><th>Tool Name</th><th>Permission Scope</th><th>Plain-English Description</th></tr>
      </thead>
      <tbody>
        <tr>
          <td><code>extract_financial_documents</code></td>
          <td>Read-Only · Idempotent</td>
          <td>Extracts supplier name, bill number, dates, payment terms, currency, line items, subtotal, sales tax, and total from supplier bills, receipts, and statements. Verifies cent-exact math (sum of line items plus tax equals billed total), flags 1099-NEC review items, and drafts a polite supplier correction note when an overcharge is found.</td>
        </tr>
        <tr>
          <td><code>reconcile_invoices_with_bank_ledger</code></td>
          <td>Read-Only · Idempotent</td>
          <td>Matches extracted supplier bills against bank statement withdrawals using date and amount tolerances. Flags matched payments, unpaid bills, bank withdrawals missing a receipt, and duplicate bank charges.</td>
        </tr>
        <tr>
          <td><code>export_ledger_bundle</code></td>
          <td>Read-Only · Idempotent</td>
          <td>Generates a downloadable 3-tab Microsoft Excel (<code>.xlsx</code>) workbook with native <code>=SUM()</code> and <code>=ROUND()</code> formulas or a clean CSV spreadsheet for accounting import.</td>
        </tr>
      </tbody>
    </table>

    <h2>4. Example Prompts to Try in Claude</h2>
    <ul>
      <li><em>"Use BillTally to check this supplier bill from Oakridge Plumbing (Invoice #INV-2026-119, dated 2026-10-15: 1. Main Water Valve Replacement 2 x $425.00 = $850.00, 2. Copper Pipe Fittings 5 x $38.00 = $190.00, Subtotal $1,040.00, Sales Tax $85.80, Billed Total $1,325.80) and draft a correction note if the math is off."</em></li>
      <li><em>"Use BillTally to match our October supplier bills against our business checking withdrawals and flag any duplicate charges or missing receipts."</em></li>
      <li><em>"Use BillTally to export these checked bills into a 3-tab Excel (.xlsx) workbook with live =SUM() formulas using the corrected math total."</em></li>
    </ul>

    <h2>5. Policies, Repository &amp; Support</h2>
    <ul>
      <li><strong>About BillTally:</strong> <a href="/about">https://schemaextract-mcp-production.up.railway.app/about</a></li>
      <li><strong>Privacy &amp; Confidentiality Policy:</strong> <a href="/privacy">https://schemaextract-mcp-production.up.railway.app/privacy</a></li>
      <li><strong>Terms of Service:</strong> <a href="/terms">https://schemaextract-mcp-production.up.railway.app/terms</a></li>
      <li><strong>GitHub Repository:</strong> <a href="https://github.com/mulak1/billtally-mcp">https://github.com/mulak1/billtally-mcp</a></li>
      <li><strong>Support Email:</strong> <a href="mailto:mulak1@gmail.com">mulak1@gmail.com</a></li>
    </ul>
  </main>
</body>
</html>"""


def render_about_html() -> str:
    """Return the About & Company Information page for BillTally."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>About BillTally | Bill Math Checker &amp; Bank Statement Matcher</title>
  {SHARED_PAGE_STYLE}
</head>
<body>
  <main>
    {TOP_NAV_HTML}
    <h1>About BillTally</h1>
    <p><strong>BillTally</strong> builds plain-English bill math verification, bank statement matching, and spreadsheet export tools designed to work both as a standalone bookkeeping workbench and natively inside AI assistants via the Model Context Protocol (MCP).</p>

    <h2>Our Mission</h2>
    <p>Bookkeepers, accountants, and small business owners spend hours re-keying supplier bills, checking whether line items and sales tax actually add up to the billed total, and hunting for duplicate withdrawals on monthly bank statements. BillTally gives every team instant, penny-exact fixed-decimal verification, polite supplier dispute notes when an overcharge is caught, and clean 3-tab Microsoft Excel (<code>.xlsx</code>) workbooks with live <code>=SUM()</code> formulas.</p>

    <h2>Privacy &amp; Security by Design</h2>
    <ul>
      <li><strong>Zero Model Training:</strong> We never train AI models on your supplier bills, receipts, or bank statements.</li>
      <li><strong>Read-Only &amp; Ephemeral Architecture:</strong> All MCP tools are stateless, read-only, and idempotent. Financial documents and exported spreadsheets are processed only in ephemeral memory.</li>
      <li><strong>Deterministic Fixed-Decimal Arithmetic:</strong> Every line item and tax calculation is verified using exact <code>Decimal</code> arithmetic rather than floating-point approximation.</li>
    </ul>

    <h2>Company &amp; Leadership</h2>
    <ul>
      <li><strong>Organization:</strong> BillTally</li>
      <li><strong>Founder &amp; Creator:</strong> Kader Mula</li>
      <li><strong>Website:</strong> <a href="https://schemaextract-mcp-production.up.railway.app">https://schemaextract-mcp-production.up.railway.app</a></li>
      <li><strong>Documentation:</strong> <a href="/docs">https://schemaextract-mcp-production.up.railway.app/docs</a></li>
      <li><strong>GitHub:</strong> <a href="https://github.com/mulak1/billtally-mcp">https://github.com/mulak1/billtally-mcp</a></li>
      <li><strong>Contact &amp; Support:</strong> <a href="mailto:mulak1@gmail.com">mulak1@gmail.com</a></li>
    </ul>
  </main>
</body>
</html>"""


def render_privacy_html() -> str:
    """Return the plain-English Privacy & Confidentiality Policy page."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Privacy &amp; Confidentiality Policy | BillTally</title>
  {SHARED_PAGE_STYLE}
</head>
<body>
  <main>
    {TOP_NAV_HTML}
    <h1>Privacy &amp; Confidentiality Policy</h1>
    <p><strong>Effective Date:</strong> November 2, 2026. Your financial documents belong strictly to you. We never train AI models on your bills, receipts, or bank statements, and we never sell or share your data.</p>

    <h2>1. Zero Training on Customer Financial Data</h2>
    <p>Supplier bills, invoices, receipts, and bank statement rows submitted through the BillTally Check Desk or via the Claude and ChatGPT connectors are processed solely to verify line-item math, reconcile statement rows, and generate your requested spreadsheet export. Your content is never used to train, fine-tune, or improve foundation models (`trains_on_customer_data: false`).</p>

    <h2>2. Ephemeral In-Memory Processing</h2>
    <p>All calculations use deterministic fixed-decimal arithmetic (`deterministic_math_engine: true`) in memory. Generated Excel (<code>.xlsx</code>) and CSV files are held temporarily in memory solely so you can download them during your active session. We do not maintain permanent archives of your financial records.</p>

    <h2>3. Transport &amp; Authentication Security</h2>
    <p>All connections use HTTPS (TLS 1.3) encryption in transit, and authentication via Claude and ChatGPT supports OAuth 2.1 with S256 PKCE verification.</p>

    <h2>4. Contact &amp; Data Inquiries</h2>
    <p>Questions regarding privacy, security, or IT administrator reviews may be directed to Kader Mula at <a href="mailto:mulak1@gmail.com">mulak1@gmail.com</a>.</p>
  </main>
</body>
</html>"""


def render_terms_html() -> str:
    """Return the plain-English Terms of Service & Bookkeeping Disclaimer page."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Terms of Service &amp; Disclaimer | BillTally</title>
  {SHARED_PAGE_STYLE}
</head>
<body>
  <main>
    {TOP_NAV_HTML}
    <h1>Terms of Service &amp; Bookkeeping Disclaimer</h1>
    <p><strong>Effective Date:</strong> November 2, 2026. By using BillTally via our web workbench or the Claude and ChatGPT connectors, you agree to the following plain-English terms.</p>

    <h2>1. Bookkeeping &amp; Accounting Assistance Disclaimer</h2>
    <p>BillTally provides automated fixed-decimal arithmetic verification, bank statement matching, and spreadsheet formatting tools. BillTally is not a certified public accounting (CPA) firm and does not provide formal tax, audit, or legal advice. Always confirm final tax filings, 1099-NEC reporting, and accounting entries with your qualified accountant or tax advisor.</p>

    <h2>2. Read-Only &amp; Non-Destructive Operation</h2>
    <p>All BillTally MCP tools operate in a stateless, read-only manner on the text and figures you provide in your session. You remain in full control of which bills to approve, short-pay, or import into your accounting software.</p>

    <h2>3. Service Plans &amp; Fair Use</h2>
    <p>BillTally provides a Free tier (up to 15 bill checks per month at $0) and a Pro tier (up to 5,000 bill checks per month at $29/month, `pro_price_usd_monthly: 29`) for high-volume bookkeeping practices.</p>

    <h2>4. Contact</h2>
    <p>For support, billing, or terms inquiries, please contact Kader Mula at <a href="mailto:mulak1@gmail.com">mulak1@gmail.com</a>.</p>
  </main>
</body>
</html>"""
