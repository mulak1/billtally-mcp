"""
Plain-English Bookkeeper & Small Business Bill Math Checker & Bank Statement Workbench (`GET /`).
Built on the `achromatic-ledger` design system (`#f8f8f8` paper ground, `#ffffff` flat ledger cards,
Geist & Geist Mono tabular numerals, <1% chroma budget reserved for verified/discrepancy signals).
"""

from app.studio_script import STUDIO_CLIENT_JS


def render_studio_html() -> str:
    """Return the complete HTML document for the SchemaExtract Accounting Workbench."""
    return (
        """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>BillTally: Bill Math Checker, Bank Statement Matcher & Spreadsheet Exporter</title>
  <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
  <link rel="icon" type="image/png" href="/icon.png" />
  <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;700&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --ground: #f8f8f8; --surface: #ffffff; --raised: #eeeeee; --border: #e6e6e6; --rule: #f0f0f0;
      --control: #d4d4d4; --text: #0a0a0a; --muted: #6b6b6b; --accent: #141414;
      --positive: #2e7d32; --negative: #c4242a; --warning: #92400e; --chart-3: #1d5fbf;
      --pill-positive-bg: #dcfae5; --pill-positive-ink: #04250e;
      --pill-negative-bg: #ffedea; --pill-negative-ink: #831c1e;
      --pill-warning-bg: #fffbeb; --pill-warning-ink: #92400e;
      --pill-neutral-bg: #eeeeee; --pill-neutral-ink: #3d3d3d;
      --radius-card: 8px; --radius-control: 6px;
      --sans: "Geist", -apple-system, BlinkMacSystemFont, sans-serif;
      --mono: "Geist Mono", ui-monospace, SFMono-Regular, monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: var(--ground); color: var(--text); font-family: var(--sans); font-size: 14px; line-height: 1.5; font-variant-numeric: tabular-nums; }
    .shell { display: grid; grid-template-columns: 252px 1fr; min-height: 100vh; }
    .sidebar { background: var(--ground); border-right: 1px solid var(--border); padding: 28px 16px; display: flex; flex-direction: column; justify-content: space-between; }
    .brand { display: flex; align-items: center; gap: 10px; padding: 0 8px 18px; border-bottom: 1px solid var(--border); }
    .brand-mark { width: 34px; height: 34px; border-radius: 8px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
    .nav-group-label { font-size: 12px; color: var(--muted); padding: 18px 8px 6px; }
    .nav-item { display: flex; align-items: center; height: 32px; padding: 0 10px; border-radius: 6px; color: var(--text); text-decoration: none; font-size: 13.5px; margin-bottom: 2px; cursor: pointer; }
    .nav-item.active { background: #e9e9e9; font-weight: 500; }
    .canvas { padding: 32px 36px 64px; max-width: 1240px; }
    .greeting-bar { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 16px; }
    h1 { font-size: 24px; font-weight: 500; letter-spacing: -0.02em; color: var(--text); }
    .greeting-sub { color: var(--muted); font-size: 14px; margin-top: 4px; max-width: 720px; }
    .trust-strip { display: flex; flex-wrap: wrap; gap: 16px; font-size: 12px; color: var(--muted); margin-bottom: 14px; padding: 8px 12px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-control); }
    .steps-strip { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px; }
    .step-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-card); padding: 12px 16px; font-size: 13px; }
    .step-num { font-family: var(--mono); font-size: 11px; color: var(--muted); display: block; margin-bottom: 2px; }
    .kpi-strip { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-card); display: grid; grid-template-columns: repeat(4, 1fr); margin-bottom: 16px; }
    .kpi-cell { padding: 16px 20px; border-right: 1px solid var(--border); }
    .kpi-cell:last-child { border-right: none; }
    .kpi-label { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
    .kpi-val { font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
    .kpi-caption { font-size: 12px; color: var(--muted); margin-top: 4px; }
    .workbench { display: grid; grid-template-columns: 1fr 1.38fr; gap: 16px; align-items: start; }
    .card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-card); padding: 20px; margin-bottom: 16px; }
    .card-title { font-size: 16px; font-weight: 500; margin-bottom: 4px; }
    .card-sub { font-size: 12px; color: var(--muted); margin-bottom: 14px; }
    .btn-row { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
    .btn { height: 36px; padding: 0 13px; border-radius: var(--radius-control); border: 1px solid var(--control); background: var(--raised); color: var(--text); font-family: var(--sans); font-size: 13px; font-weight: 500; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; text-decoration: none; }
    .btn:hover { background: #e2e2e2; }
    .btn.active-preset { border-color: var(--text); background: #e0e0e0; }
    .btn-primary { background: var(--accent); color: #ffffff; border-color: var(--accent); }
    .btn-primary:hover { background: #2b2b2b; }
    .dropzone { border: 1px dashed var(--control); border-radius: var(--radius-control); padding: 10px 12px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: var(--muted); background: #fcfcfc; }
    .dropzone.drag-over { border-color: var(--chart-3); background: #f0f6ff; }
    textarea { width: 100%; min-height: 220px; border: 1px solid var(--border); border-radius: var(--radius-control); padding: 12px; font-family: var(--mono); font-size: 12px; color: var(--text); background: #fcfcfc; resize: vertical; margin-bottom: 12px; line-height: 1.55; }
    .banner { padding: 12px 14px; border-radius: var(--radius-control); font-size: 13px; margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; gap: 12px; }
    .banner-ok { background: var(--pill-positive-bg); color: var(--pill-positive-ink); }
    .banner-err { background: var(--pill-negative-bg); color: var(--pill-negative-ink); }
    .banner-warn { background: var(--pill-warning-bg); color: var(--pill-warning-ink); }
    .pill { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }
    .pill-ok { background: var(--pill-positive-bg); color: var(--pill-positive-ink); }
    .pill-err { background: var(--pill-negative-bg); color: var(--pill-negative-ink); }
    .pill-warn { background: var(--pill-warning-bg); color: var(--pill-warning-ink); }
    table { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
    th, td { height: 42px; padding: 6px 10px; border-bottom: 1px solid var(--rule); text-align: left; }
    th { font-size: 12px; font-weight: 500; color: var(--muted); border-bottom: 1px solid var(--border); }
    th.num, td.num { text-align: right; }
    td.money { font-weight: 700; text-align: right; }
    select.input-select { height: 34px; width: 100%; border: 1px solid var(--control); border-radius: var(--radius-control); padding: 0 8px; font-family: var(--sans); font-size: 13px; background: var(--surface); color: var(--text); }
    .top-bar-links { display: flex; justify-content: flex-end; gap: 18px; padding-bottom: 14px; margin-bottom: 18px; border-bottom: 1px solid var(--border); font-size: 13px; }
    .top-bar-links a { color: var(--muted); text-decoration: none; font-weight: 500; }
    .top-bar-links a:hover { color: var(--text); text-decoration: underline; }
    footer.site-footer { margin-top: 28px; padding-top: 16px; border-top: 1px solid var(--border); display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px; font-size: 12.5px; color: var(--muted); }
    footer.site-footer a { color: var(--muted); text-decoration: none; font-weight: 500; }
    footer.site-footer a:hover { color: var(--text); text-decoration: underline; }
    @media (max-width: 960px) {
      .shell { grid-template-columns: 1fr; }
      .sidebar { border-right: none; border-bottom: 1px solid var(--border); padding: 16px; }
      .steps-strip, .kpi-strip, .workbench { grid-template-columns: 1fr; }
      .kpi-cell { border-right: none; border-bottom: 1px solid var(--border); }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar" aria-label="Workspace Navigation">
      <div>
        <div class="brand">
          <div class="brand-mark" aria-hidden="true">
            <svg width="34" height="34" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect width="48" height="48" rx="11" fill="#111827" stroke="#374151" stroke-width="2"/>
              <rect x="8" y="8" width="23" height="26" rx="3" fill="#1F2937" stroke="#4B5563" stroke-width="1.2"/>
              <rect x="11.5" y="10.5" width="26" height="27.5" rx="3.5" fill="#F8FAFC" stroke="#E2E8F0" stroke-width="1.2"/>
              <path d="M11.5 14C11.5 12.1 13.1 10.5 15 10.5H34C35.9 10.5 37.5 12.1 37.5 14V16.5H11.5V14Z" fill="#141414"/>
              <rect x="14" y="12.7" width="9" height="1.8" rx="0.9" fill="#F8FAFC"/>
              <rect x="29.5" y="12.7" width="5.5" height="1.8" rx="0.9" fill="#34D399"/>
              <rect x="14" y="19.5" width="11" height="2" rx="1" fill="#475569"/>
              <rect x="27.5" y="19" width="7.5" height="3" rx="1.2" fill="#DCFCE7"/>
              <rect x="14" y="24.5" width="9.5" height="2" rx="1" fill="#475569"/>
              <rect x="27.5" y="24" width="7.5" height="3" rx="1.2" fill="#DCFCE7"/>
              <rect x="14" y="29.5" width="10.5" height="2" rx="1" fill="#475569"/>
              <rect x="27.5" y="29" width="7.5" height="3" rx="1.2" fill="#FEE2E2"/>
              <circle cx="35" cy="35" r="6.5" fill="#16A34A" stroke="#F8FAFC" stroke-width="1.5"/>
              <path d="M32.3 35.1L34.1 36.9L37.9 33.1" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
          <div>
            <div style="font-weight:500; font-size:14px;">BillTally</div>
            <div style="font-size:12px; color:var(--muted);">Bill & Bank Check Desk</div>
          </div>
        </div>
        <div class="nav-group-label">Daily bookkeeping</div>
        <a class="nav-item active" id="nav-bill" href="#workbench" onclick="loadPreset('messy_saas_invoice')">1. Check a supplier bill</a>
        <a class="nav-item" id="nav-bank" href="#bank-match" onclick="runBankReconciliationPreset(true)">2. Match bank statement</a>
        <a class="nav-item" id="nav-export" href="#export-bar" onclick="exportBundle('xlsx')">3. Export spreadsheet (.xlsx)</a>
        <div class="nav-group-label">Sample bills to try</div>
        <a class="nav-item" id="side-messy_saas_invoice" href="#workbench" onclick="loadPreset('messy_saas_invoice')">Bakery supply bill (Balanced)</a>
        <a class="nav-item" id="side-discrepant_contractor_invoice" href="#workbench" onclick="loadPreset('discrepant_contractor_invoice')">Plumbing bill ($200 error)</a>
        <a class="nav-item" id="side-bank_reconciliation_batch" href="#bank-match" onclick="runBankReconciliationPreset(true)">October checking statement</a>
        <div class="nav-group-label">Company &amp; Policies</div>
        <a class="nav-item" href="/about">About BillTally</a>
        <a class="nav-item" href="/docs">Documentation</a>
        <a class="nav-item" href="/privacy">Privacy Policy</a>
        <a class="nav-item" href="/terms">Terms of Service</a>
      </div>

      <div style="border-top:1px solid var(--border); padding-top:14px; font-size:12px;">
        <div style="color:var(--muted); margin-bottom:4px;">Monthly plan usage</div>
        <div style="margin-bottom:8px;">
          <strong id="tier-name">Free Plan</strong> · <span id="quota-used">0</span> of <span id="quota-limit">15</span> bills checked
        </div>
        <a id="sidebarUpgradeLink" class="btn btn-primary" href="https://buy.stripe.com/bJedR9cK12BN90903MfAc01" target="_blank" rel="noopener" style="width:100%; justify-content:center; margin-bottom:6px;">Upgrade via Stripe ($49.99) →</a>
        <button class="btn" style="width:100%; justify-content:center; font-size:11.5px;" onclick="upgradePro()">Upgrade to Pro ($29/mo)</button>
      </div>
    </aside>

    <main class="canvas" id="workbench">
      <nav class="top-bar-links" aria-label="Company and documentation links">
        <a href="/about">About</a>
        <a href="/docs">Documentation</a>
        <a href="/analytics">Live Analytics</a>
        <a href="/privacy">Privacy Policy</a>
        <a href="/terms">Terms</a>
        <a id="headerUpgradeLink" href="https://buy.stripe.com/bJedR9cK12BN90903MfAc01" target="_blank" rel="noopener" style="color:var(--positive); font-weight:600;">Upgrade ($49.99) →</a>
      </nav>
      <header class="greeting-bar">
        <div>
          <h1 id="greeting-heading">Good morning. Welcome to your Bill & Bank Math Check Desk</h1>
          <p class="greeting-sub">
            Drop a file or paste any supplier bill, receipt, or monthly bank statement below. We check every line item
            (Quantity × Unit Price) and sales tax to the penny before you pay the bill or export your spreadsheet.
          </p>
        </div>
        <div class="btn-row" id="export-bar">
          <button class="btn btn-primary" onclick="exportBundle('xlsx')">Download Excel (.xlsx with =SUM)</button>
          <button class="btn" onclick="exportBundle('quickbooks_csv')">Download Accounting CSV</button>
        </div>
      </header>

      <div class="trust-strip" role="note" aria-label="Privacy and math guarantee">
        <span><strong>100% Penny-Exact Math:</strong> Every line item is verified with fixed-decimal arithmetic, never guessed.</span>
        <span>·</span>
        <span><strong>Private & Confidential:</strong> Bills are checked in memory and never used to train models.</span>
        <span>·</span>
        <span id="batch-counter-text"><strong>Batch Queue:</strong> 1 bill ready to export</span>
      </div>

      <section class="steps-strip" aria-label="How this works in 3 plain steps">
        <div class="step-card">
          <span class="step-num">Step 1 of 3 · Add your bill</span>
          Pick one of the sample bills below, drag and drop a <code>.txt</code> or <code>.csv</code> file, or paste text from an email or PDF.
        </div>
        <div class="step-card">
          <span class="step-num">Step 2 of 3 · Automatic penny check</span>
          Every line item is multiplied out and added up so overcharges and duplicate bank withdrawals are caught immediately.
        </div>
        <div class="step-card">
          <span class="step-num">Step 3 of 3 · Export or reply</span>
          Download a clean 3-tab Excel workbook with live <code>=SUM()</code> formulas, or copy a polite correction note to your supplier.
        </div>
      </section>

      <section class="kpi-strip" aria-label="Bill summary figures">
        <div class="kpi-cell">
          <div class="kpi-label">Billed total (on paper)</div>
          <div class="kpi-val" id="kpi-billed">$6,928.00</div>
          <div class="kpi-caption" id="kpi-vendor">Heartland Flour & Pantry Supply Co.</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">True math total (Qty × Price + Tax)</div>
          <div class="kpi-val" id="kpi-computed">$6,928.00</div>
          <div class="kpi-caption" id="kpi-invoice-no">Bill #INV-2026-0842 · Net 30 (Due 2026-10-31)</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">Math check result</div>
          <div class="kpi-val" id="kpi-delta">$0.00</div>
          <div class="kpi-caption" id="kpi-status-caption">Balanced to the penny · Tax 8.25%</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">Expense category</div>
          <div style="margin-top:6px;">
            <select id="category-select" class="input-select" aria-label="Expense category">
              <option value="Cost of Goods Sold: Food & Pantry">Cost of Goods Sold: Food & Pantry</option>
              <option value="Repairs & Building Maintenance">Repairs & Building Maintenance</option>
              <option value="Utilities & Occupancy">Utilities & Occupancy</option>
              <option value="Outside Services & Operations">Outside Services & Operations</option>
              <option value="General Operating Expense">General Operating Expense</option>
            </select>
          </div>
          <div class="kpi-caption" id="compliance-caption">Included in your Excel & CSV exports</div>
        </div>
      </section>

      <div id="download-status" style="margin-bottom:12px; font-size:13px; color:var(--chart-3); font-weight:500;"></div>

      <section class="workbench">
        <div class="card">
          <div class="card-title">Step 1 · Bill or statement text</div>
          <div class="card-sub">Try a sample small-business bill with one click, drop a file from your computer, or paste your own text.</div>

          <div class="btn-row">
            <button class="btn active-preset" id="btn-messy_saas_invoice" onclick="loadPreset('messy_saas_invoice')">Bakery supply bill ($6,928)</button>
            <button class="btn" id="btn-discrepant_contractor_invoice" onclick="loadPreset('discrepant_contractor_invoice')">Plumbing bill ($200 math error)</button>
            <button class="btn" id="btn-bank_reconciliation_batch" onclick="runBankReconciliationPreset(true)">October bank statement match</button>
          </div>

          <div class="dropzone" id="dropzone" ondragover="onDragOver(event)" ondragleave="onDragLeave(event)" ondrop="onFileDrop(event)">
            <span>Drag & drop a <code>.txt</code> or <code>.csv</code> file here, or choose from computer</span>
            <label class="btn" style="height:28px; font-size:12px; cursor:pointer;">
              Choose file (.txt / .csv)
              <input type="file" id="file-upload" accept=".txt,.csv" style="display:none" onchange="handleFileUpload(event)" />
            </label>
          </div>

          <label for="raw-doc-input" style="font-size:12px; color:var(--muted); display:block; margin-bottom:4px;">Bill or statement lines</label>
          <textarea id="raw-doc-input" spellcheck="false"></textarea>

          <div class="btn-row" style="margin-bottom:0;">
            <button class="btn btn-primary" onclick="runExtractMcp()">Check bill math to the penny</button>
            <button class="btn" onclick="addCurrentToBatch()">Add bill to batch queue</button>
            <button class="btn" onclick="clearInput()">Clear & paste your own</button>
          </div>
        </div>

        <div>
          <div class="card">
            <div class="card-title">Step 2 · Line-by-line penny check</div>
            <div class="card-sub">Every row is checked by multiplying Quantity × Unit Price and comparing against the billed amount.</div>

            <div id="audit-banner" class="banner banner-ok">
              <span id="banner-text">All 5 line items and tax add up to the penny ($6,928.00). Ready to approve and export.</span>
              <span class="pill pill-ok" id="confidence-pill">Verified</span>
            </div>

            <div id="discrepancy-actions" style="display:none; margin-bottom:14px; padding:14px; background:#fffafa; border:1px solid #f5c2c7; border-radius:6px;">
              <div style="font-weight:500; font-size:13px; color:var(--pill-negative-ink); margin-bottom:8px;">
                How would you like to handle this overcharge when exporting?
              </div>
              <div style="display:flex; flex-wrap:wrap; gap:14px; align-items:center; font-size:13px; margin-bottom:10px;">
                <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
                  <input type="radio" name="export-mode" id="mode-corrected" value="corrected" checked onchange="updateExportModeLabel()" />
                  Export true math total (<strong id="label-corrected-amt">$6,505.30</strong>, short-pay corrected bill)
                </label>
                <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
                  <input type="radio" name="export-mode" id="mode-billed" value="billed" onchange="updateExportModeLabel()" />
                  Export billed total (<strong id="label-billed-amt">$6,705.30</strong>, hold for supplier credit note)
                </label>
              </div>
              <label for="supplier-note-box" style="font-size:12px; color:var(--muted); display:block; margin-bottom:4px;">
                Polite note to supplier (you can edit before copying or emailing):
              </label>
              <textarea id="supplier-note-box" style="min-height:110px; background:#ffffff; margin-bottom:8px;"></textarea>
              <div class="btn-row" style="margin-bottom:0;">
                <button class="btn btn-primary" onclick="copySupplierNote()">Copy note to supplier</button>
                <a class="btn" id="mailto-link" href="mailto:billing@supplier.example">Open in email app</a>
              </div>
            </div>

            <div id="table-container"></div>
          </div>

          <div class="card" id="bank-match">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <div>
                <div class="card-title">Monthly bank statement vs. supplier bills</div>
                <div class="card-sub" style="margin-bottom:0;">Matches your bills against checking withdrawals to catch unpaid bills and duplicate charges.</div>
              </div>
              <button class="btn" onclick="runBankReconciliationPreset(false)">Run October bank check</button>
            </div>
            <div id="bank-recon-container" style="font-size:13px; color:var(--muted);">
              Click "Run October bank check" to compare 4 supplier bills against 5 business checking withdrawals.
            </div>
          </div>
        </div>
      </section>

      <footer class="site-footer">
        <div>BillTally · Founder &amp; Creator: Kader Mula · Support: <a href="mailto:mulak1@gmail.com">mulak1@gmail.com</a></div>
        <div style="display:flex; gap:16px;">
          <a href="/about">About</a>
          <a href="/docs">Documentation</a>
          <a href="/privacy">Privacy Policy</a>
          <a href="/terms">Terms</a>
        </div>
      </footer>
    </main>
  </div>
  <script>"""
        + STUDIO_CLIENT_JS
        + """</script>
</body>
</html>"""
    )
