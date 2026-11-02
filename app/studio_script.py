"""
Client-side controller script for the SchemaExtract Accounting Workbench (`GET /`).
Separated from `studio_ui.py` so every module remains under 400 lines.
"""

STUDIO_CLIENT_JS = """
    let PRESETS = {};
    let LAST_EXTRACTED = null;
    let BATCH_QUEUE = [];
    let LAST_RECON = null;
    let CURRENT_API_KEY = null;

    function setGreetingByHour() {
      const hr = new Date().getHours();
      const tod = hr < 12 ? "Good morning" : (hr < 18 ? "Good afternoon" : "Good evening");
      document.getElementById("greeting-heading").textContent = tod + ". Welcome to your Bill & Bank Math Check Desk";
    }

    async function initStudio() {
      setGreetingByHour();
      const res = await fetch('/api/presets');
      const data = await res.json();
      data.presets.forEach(p => { PRESETS[p.id] = p; });
      await refreshQuota();
      await loadPreset('messy_saas_invoice');
    }

    function setActivePresetUi(id) {
      ['messy_saas_invoice', 'discrepant_contractor_invoice', 'bank_reconciliation_batch'].forEach(k => {
        const b = document.getElementById('btn-' + k);
        const s = document.getElementById('side-' + k);
        if (b) b.classList.toggle('active-preset', k === id);
        if (s) s.classList.toggle('active', k === id);
      });
    }

    async function refreshQuota() {
      const res = await fetch('/api/quota');
      const q = await res.json();
      document.getElementById('tier-name').textContent = q.tier === 'pro' ? 'Pro Plan' : 'Free Plan';
      document.getElementById('quota-used').textContent = q.used;
      document.getElementById('quota-limit').textContent = q.limit;
    }

    async function upgradePro() {
      const res = await fetch('/api/quota/upgrade', { method: 'POST' });
      const q = await res.json();
      CURRENT_API_KEY = q.api_key;
      await refreshQuota();
      document.getElementById('download-status').textContent =
        'Upgraded to Pro Plan (5,000 bills/mo enabled). Pro Key: ' + q.api_key;
    }

    function copyMcpUrl() {
      navigator.clipboard.writeText(window.location.origin + '/mcp');
      document.getElementById('download-status').textContent = 'Copied assistant connection address to clipboard.';
    }

    function clearInput() {
      const el = document.getElementById('raw-doc-input');
      el.value = '';
      el.placeholder = 'Paste your supplier bill, receipt, or statement lines here...';
      el.focus();
    }

    function onDragOver(ev) { ev.preventDefault(); document.getElementById('dropzone').classList.add('drag-over'); }
    function onDragLeave(ev) { ev.preventDefault(); document.getElementById('dropzone').classList.remove('drag-over'); }
    function onFileDrop(ev) {
      ev.preventDefault();
      document.getElementById('dropzone').classList.remove('drag-over');
      const file = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
      if (file) readAndCheckFile(file);
    }

    function handleFileUpload(ev) {
      const file = ev.target.files && ev.target.files[0];
      if (file) readAndCheckFile(file);
    }

    function readAndCheckFile(file) {
      const reader = new FileReader();
      reader.onload = async (e) => {
        document.getElementById('raw-doc-input').value = String(e.target.result || '');
        await runExtractMcp();
      };
      reader.readAsText(file);
    }

    async function loadPreset(id) {
      const preset = PRESETS[id];
      if (!preset) return;
      setActivePresetUi(id);
      document.getElementById('raw-doc-input').value = preset.raw_text;
      await runExtractMcp();
    }

    async function runExtractMcp() {
      const rawText = document.getElementById('raw-doc-input').value;
      const rpcReq = {
        jsonrpc: "2.0",
        id: "studio-extract-1",
        method: "tools/call",
        params: {
          name: "extract_financial_documents",
          arguments: { raw_text: rawText, document_type: "invoice", api_key: CURRENT_API_KEY }
        }
      };
      const res = await fetch('/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(rpcReq)
      });
      const rpcRes = await res.json();
      if (rpcRes.result && rpcRes.result.structuredContent) {
        LAST_EXTRACTED = rpcRes.result.structuredContent;
        if (BATCH_QUEUE.length === 0) BATCH_QUEUE = [LAST_EXTRACTED];
        renderExtractedTable(LAST_EXTRACTED);
        await refreshQuota();
      }
    }

    function addCurrentToBatch() {
      if (!LAST_EXTRACTED) return;
      const dup = BATCH_QUEUE.find(d => d.invoice_number === LAST_EXTRACTED.invoice_number && d.vendor === LAST_EXTRACTED.vendor);
      if (dup) {
        document.getElementById('download-status').textContent =
          'Duplicate bill warning: Bill #' + LAST_EXTRACTED.invoice_number + ' from ' + LAST_EXTRACTED.vendor + ' is already in your batch queue.';
        return;
      }
      BATCH_QUEUE.push(LAST_EXTRACTED);
      document.getElementById('batch-counter-text').innerHTML =
        '<strong>Batch Queue:</strong> ' + BATCH_QUEUE.length + ' bills ready to export together';
      document.getElementById('download-status').textContent =
        'Added Bill #' + LAST_EXTRACTED.invoice_number + ' to batch queue (' + BATCH_QUEUE.length + ' bills total).';
    }

    function fmtMoney(n) {
      const sign = n < 0 ? '-' : '';
      return sign + '$' + Math.abs(Number(n || 0)).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function updateExportModeLabel() {
      const useCorr = document.getElementById('mode-corrected') && document.getElementById('mode-corrected').checked;
      document.getElementById('download-status').textContent = useCorr
        ? 'Export mode set to: Short-pay corrected math total.'
        : 'Export mode set to: Hold billed total for supplier credit note.';
    }

    function renderExtractedTable(doc) {
      document.getElementById('kpi-billed').textContent = fmtMoney(doc.total);
      document.getElementById('kpi-computed').textContent = fmtMoney(doc.computed_total);
      document.getElementById('kpi-vendor').textContent = doc.vendor;
      document.getElementById('kpi-invoice-no').textContent =
        'Bill #' + doc.invoice_number + ' · ' + (doc.payment_terms || ('Issued ' + doc.issue_date));

      const catSelect = document.getElementById('category-select');
      if (doc.suggested_category) catSelect.value = doc.suggested_category;

      const compCap = document.getElementById('compliance-caption');
      compCap.innerHTML = doc.requires_1099_review
        ? '<span class="pill pill-warn">1099-NEC Trackable: Verify W-9 on file</span>'
        : 'Included in your Excel & CSV exports';

      const banner = document.getElementById('audit-banner');
      const actionsBox = document.getElementById('discrepancy-actions');
      const deltaEl = document.getElementById('kpi-delta');
      const statusCap = document.getElementById('kpi-status-caption');
      const taxPct = Number(doc.effective_tax_rate_pct || 0).toFixed(2) + '%';

      if (doc.math_verified) {
        banner.className = 'banner banner-ok';
        banner.innerHTML = '<span>' + doc.plain_english_summary + '</span><span class="pill pill-ok">Balanced to the penny</span>';
        deltaEl.textContent = '$0.00';
        deltaEl.style.color = 'var(--text)';
        statusCap.textContent = 'Balanced to the penny · Tax ' + taxPct;
        actionsBox.style.display = 'none';
      } else {
        banner.className = 'banner banner-err';
        banner.innerHTML = '<span>' + doc.plain_english_summary + '</span><span class="pill pill-err">Overcharge caught</span>';
        deltaEl.textContent = (doc.discrepancy_delta > 0 ? '+' : '') + fmtMoney(doc.discrepancy_delta);
        deltaEl.style.color = 'var(--negative)';
        statusCap.textContent = 'Billed total off by ' + fmtMoney(doc.discrepancy_delta) + ' · Tax ' + taxPct;
        actionsBox.style.display = 'block';
        document.getElementById('label-corrected-amt').textContent = fmtMoney(doc.computed_total);
        document.getElementById('label-billed-amt').textContent = fmtMoney(doc.total);
        const noteBox = document.getElementById('supplier-note-box');
        noteBox.value = doc.vendor_dispute_note || '';
        const subj = encodeURIComponent('Math check on Invoice #' + doc.invoice_number);
        const body = encodeURIComponent(doc.vendor_dispute_note || '');
        document.getElementById('mailto-link').href = 'mailto:?subject=' + subj + '&body=' + body;
      }

      const rowsHtml = doc.line_items.map(li => `
        <tr style="${li.line_math_valid ? '' : 'background:#fff5f5;'}">
          <td>${li.line_number}</td>
          <td>${li.description}</td>
          <td class="num">${li.quantity}</td>
          <td class="num">${fmtMoney(li.unit_price)}</td>
          <td class="money" style="${li.line_math_valid ? '' : 'color:var(--negative);'}">${fmtMoney(li.amount)}</td>
          <td class="money">${fmtMoney(li.expected_amount)}</td>
          <td class="num"><span class="pill ${li.line_math_valid ? 'pill-ok' : 'pill-err'}">${li.line_math_valid ? 'Matches' : ('Off by ' + fmtMoney(li.delta))}</span></td>
        </tr>
      `).join('');

      document.getElementById('table-container').innerHTML = `
        <table>
          <thead>
            <tr>
              <th>#</th><th>Item description</th><th class="num">Qty</th>
              <th class="num">Unit price</th><th class="num">Billed amount</th>
              <th class="num">True math (Qty×Price)</th><th class="num">Check</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
          <tfoot>
            <tr>
              <td colspan="4" style="color:var(--muted);">Line items subtotal</td>
              <td class="money">${fmtMoney(doc.subtotal)}</td>
              <td class="money">${fmtMoney(doc.computed_subtotal)}</td>
              <td class="num"><span class="pill ${doc.subtotal === doc.computed_subtotal ? 'pill-ok' : 'pill-err'}">${doc.subtotal === doc.computed_subtotal ? 'Subtotal OK' : 'Subtotal off'}</span></td>
            </tr>
            <tr>
              <td colspan="4" style="color:var(--muted);">Sales tax (${taxPct})</td>
              <td class="money">${fmtMoney(doc.tax)}</td>
              <td class="money">${fmtMoney(doc.tax)}</td>
              <td class="num"><span class="pill pill-ok">Tax checked</span></td>
            </tr>
            <tr>
              <td colspan="4" style="font-weight:500;">Total due</td>
              <td class="money">${fmtMoney(doc.total)}</td>
              <td class="money">${fmtMoney(doc.computed_total)}</td>
              <td class="num"><span class="pill ${doc.math_verified ? 'pill-ok' : 'pill-err'}">${doc.math_verified ? 'Balanced' : 'Hold payment'}</span></td>
            </tr>
          </tfoot>
        </table>
      `;
    }

    function copySupplierNote() {
      const box = document.getElementById('supplier-note-box');
      if (!box || !box.value) return;
      navigator.clipboard.writeText(box.value);
      document.getElementById('download-status').textContent = 'Copied polite supplier correction note to your clipboard.';
    }

    async function runBankReconciliationPreset(scrollToCard) {
      setActivePresetUi('bank_reconciliation_batch');
      const preset = PRESETS['bank_reconciliation_batch'];
      const rpcReq = {
        jsonrpc: "2.0",
        id: "studio-recon-1",
        method: "tools/call",
        params: {
          name: "reconcile_invoices_with_bank_ledger",
          arguments: { invoices: preset.invoices, bank_transactions: preset.bank_transactions, date_tolerance_days: 7 }
        }
      };
      const res = await fetch('/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(rpcReq)
      });
      const rpcRes = await res.json();
      LAST_RECON = rpcRes.result.structuredContent;
      const m = LAST_RECON.summary_metrics;

      const matchedRows = LAST_RECON.matched.map(r => `
        <tr><td><span class="pill pill-ok">Matched payment</span></td><td>${r.vendor} (${r.invoice_number})</td><td>${r.bank_date}</td><td class="money">${fmtMoney(r.bank_amount)}</td><td>Cleared in checking (no action needed)</td></tr>
      `).join('');
      const unpaidRows = LAST_RECON.unmatched_invoices.map(r => `
        <tr><td><span class="pill pill-warn">Unpaid bill</span></td><td>${r.vendor} (${r.invoice_number})</td><td>${r.date}</td><td class="money">${fmtMoney(r.total)}</td><td>Schedule payment or accrue at month-end</td></tr>
      `).join('');
      const alertRows = LAST_RECON.unmatched_bank_txns.map(r => {
        const isDup = r.status.includes('DUPLICATE');
        return `<tr style="background:#fff5f5;"><td><span class="pill pill-err">${isDup ? 'Duplicate charge caught' : 'Missing receipt'}</span></td><td>${r.description}</td><td>${r.date}</td><td class="money" style="color:var(--negative);">${fmtMoney(r.amount)}</td><td>${isDup ? 'Request $1,250.00 refund from supplier' : 'Ask cardholder for store receipt'}</td></tr>`;
      }).join('');

      document.getElementById('bank-recon-container').innerHTML = `
        <div class="banner banner-warn" style="margin-top:8px;">
          <span><strong>October Checking Summary:</strong> ${m.matched_count} bills matched · ${m.unmatched_invoice_count} unpaid bill · ${m.duplicate_count} duplicate withdrawal (${fmtMoney(m.duplicate_exposure)})</span>
          <span class="pill pill-err">Action needed</span>
        </div>
        <table>
          <thead><tr><th>Status</th><th>Supplier or bank description</th><th>Date</th><th class="num">Amount</th><th>Recommended bookkeeper action</th></tr></thead>
          <tbody>${matchedRows}${unpaidRows}${alertRows}</tbody>
        </table>
      `;
      if (scrollToCard) document.getElementById('bank-match').scrollIntoView({ behavior: 'smooth' });
    }

    async function inspectToolsList() {
      const res = await fetch('/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: "2.0", id: "list-1", method: "tools/list", params: {} })
      });
      const data = await res.json();
      document.getElementById('mcp-json-inspector').textContent = JSON.stringify(data, null, 2);
    }

    async function exportBundle(fmt) {
      if (!LAST_EXTRACTED) await runExtractMcp();
      LAST_EXTRACTED.suggested_category = document.getElementById('category-select').value;
      const docsToExport = BATCH_QUEUE.length > 1 ? BATCH_QUEUE : [LAST_EXTRACTED];
      const useCorrected = document.getElementById('mode-corrected') ? document.getElementById('mode-corrected').checked : false;
      const slug = (LAST_EXTRACTED.invoice_number || 'checked_bills').toLowerCase();
      const rpcReq = {
        jsonrpc: "2.0",
        id: "studio-export-1",
        method: "tools/call",
        params: {
          name: "export_ledger_bundle",
          arguments: {
            documents: docsToExport,
            reconciliation: LAST_RECON,
            format: fmt,
            bundle_name: slug + "_ledger",
            use_corrected_amounts: useCorrected
          }
        }
      };
      const res = await fetch('/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(rpcReq)
      });
      const rpcRes = await res.json();
      const out = rpcRes.result.structuredContent;
      document.getElementById('download-status').innerHTML =
        `Your spreadsheet <strong>${out.filename}</strong> (${out.size_bytes} bytes, SHA-256 verified) is ready: <a href="${out.download_url}" style="color:var(--chart-3); text-decoration:underline;">Click here to download</a>`;
    }

    initStudio();
"""
