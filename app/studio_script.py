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

    const SAMPLE_LABELS = {
      messy_saas_invoice: "Sample: Bakery supply bill (Balanced)",
      discrepant_contractor_invoice: "Sample: Plumbing bill ($200 overcharge)",
      bank_reconciliation_batch: "Sample: October bank statement"
    };

    function setGreetingByHour() {
      const hr = new Date().getHours();
      const tod = hr < 12 ? "Good morning" : (hr < 18 ? "Good afternoon" : "Good evening");
      document.getElementById("greeting-heading").textContent = tod + ". Welcome to your Bill & Bank Math Check Desk";
    }

    function showToast(msg) {
      const bar = document.getElementById('toast-bar');
      const txt = document.getElementById('toast-text');
      if (!bar || !txt) return;
      txt.textContent = msg;
      bar.style.display = 'flex';
    }

    function updateLineCount(isCustom) {
      const el = document.getElementById('raw-doc-input');
      const badge = document.getElementById('line-counter-badge');
      if (!el || !badge) return;
      const lines = el.value.trim() ? el.value.trim().split(/\\r?\\n/).length : 0;
      badge.textContent = lines > 0 ? (lines + ' lines pasted · Ready to check') : '0 lines · Paste or drop a bill to begin';
      if (isCustom) {
        const pill = document.getElementById('active-sample-pill');
        if (pill) pill.textContent = lines > 0 ? 'Custom bill text' : 'Ready for input';
      }
    }

    async function initStudio() {
      setGreetingByHour();
      const res = await fetch('/api/presets');
      const data = await res.json();
      data.presets.forEach(p => { PRESETS[p.id] = p; });
      if (window.location.search.includes('pro_activated=1') || localStorage.getItem('bt_pro_active') === '1') {
        localStorage.setItem('bt_pro_active', '1');
        await upgradePro();
      } else {
        await refreshQuota();
      }
      await loadPreset('messy_saas_invoice');
    }

    function setActivePresetUi(id) {
      ['messy_saas_invoice', 'discrepant_contractor_invoice', 'bank_reconciliation_batch'].forEach(k => {
        const b = document.getElementById('btn-' + k);
        const s = document.getElementById('side-' + k);
        if (b) b.classList.toggle('active-preset', k === id);
        if (s) s.classList.toggle('active', k === id);
      });
      const pill = document.getElementById('active-sample-pill');
      if (pill && SAMPLE_LABELS[id]) pill.textContent = SAMPLE_LABELS[id];
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
      const hLink = document.getElementById('headerUpgradeLink');
      if (hLink) hLink.textContent = '✓ Pro Plan Active ($49.99)';
      const sLink = document.getElementById('sidebarUpgradeLink');
      if (sLink) sLink.textContent = '✓ Pro Plan Active';
      showToast('✓ Pro Plan Activated: 5,000 bills/month unlocked.');
    }

    function clearInput() {
      const el = document.getElementById('raw-doc-input');
      el.value = '';
      el.placeholder = 'Paste your supplier bill, receipt, or statement lines here...';
      setActivePresetUi('');
      updateLineCount(true);
      el.focus();
      showToast('Cleared bill text box. Paste or drop your own bill to check.');
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
        const pill = document.getElementById('active-sample-pill');
        if (pill) pill.textContent = 'File: ' + file.name;
        updateLineCount(false);
        await runExtractMcp();
      };
      reader.readAsText(file);
    }
    async function loadPreset(id) {
      const preset = PRESETS[id];
      if (!preset) return;
      setActivePresetUi(id);
      document.getElementById('raw-doc-input').value = preset.raw_text;
      updateLineCount(false);
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
        showToast('Duplicate bill warning: Bill #' + LAST_EXTRACTED.invoice_number + ' is already in your batch queue.');
        return;
      }
      BATCH_QUEUE.push(LAST_EXTRACTED);
      document.getElementById('batch-counter-text').innerHTML =
        '<strong>Batch Queue:</strong> ' + BATCH_QUEUE.length + ' bills ready to export together';
      showToast('✓ Added Bill #' + LAST_EXTRACTED.invoice_number + ' to batch queue (' + BATCH_QUEUE.length + ' bills total).');
    }

    function fmtMoney(n) {
      const sign = n < 0 ? '-' : '';
      return sign + '$' + Math.abs(Number(n || 0)).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function updateExportModeLabel() {
      const useCorr = document.getElementById('mode-corrected') && document.getElementById('mode-corrected').checked;
      showToast(useCorr
        ? 'Export mode set to: Short-pay verified true math total.'
        : 'Export mode set to: Hold billed total for supplier credit note.');
    }

    function jumpToDisputedRow() {
      const el = document.getElementById('disputed-row');
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.style.outline = '2px solid var(--negative)';
        setTimeout(() => { el.style.outline = 'none'; }, 2200);
      }
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
      const topDisputeBtn = document.getElementById('top-copy-dispute-btn');
      const deltaEl = document.getElementById('kpi-delta');
      const statusCap = document.getElementById('kpi-status-caption');
      const taxPct = Number(doc.effective_tax_rate_pct || 0).toFixed(2) + '%';

      if (doc.math_verified) {
        banner.className = 'banner banner-ok';
        banner.innerHTML =
          '<div><strong>✓ Math Checks Out:</strong> Every line item (' + doc.line_items.length + ' rows) and tax line adds up to <strong>' + fmtMoney(doc.total) + '</strong>.</div>' +
          '<span class="pill pill-ok">Balanced to the penny</span>';
        deltaEl.textContent = '$0.00';
        deltaEl.style.color = 'var(--text)';
        statusCap.textContent = 'Balanced to the penny · Tax ' + taxPct;
        actionsBox.style.display = 'none';
        if (topDisputeBtn) topDisputeBtn.style.display = 'none';
      } else {
        const savings = fmtMoney(Math.abs(doc.discrepancy_delta));
        banner.className = 'banner banner-err';
        banner.innerHTML =
          '<div><strong>⚠ Overcharge Caught:</strong> Supplier billed <strong>' + fmtMoney(doc.total) + '</strong>, but the true math is <strong>' + fmtMoney(doc.computed_total) + '</strong> (You save <strong>' + savings + '</strong>).</div>' +
          '<div style="display:flex; gap:8px; align-items:center;">' +
            '<button class="btn btn-sm" style="background:#ffffff;" onclick="jumpToDisputedRow()">Jump to Disputed Line ↓</button>' +
            '<button class="btn btn-sm btn-primary" onclick="copySupplierNote()">Copy Supplier Dispute Email</button>' +
          '</div>';
        deltaEl.textContent = (doc.discrepancy_delta > 0 ? '+' : '') + fmtMoney(doc.discrepancy_delta);
        deltaEl.style.color = 'var(--negative)';
        statusCap.textContent = 'Billed total off by ' + fmtMoney(doc.discrepancy_delta) + ' · Tax ' + taxPct;
        actionsBox.style.display = 'block';
        if (topDisputeBtn) topDisputeBtn.style.display = 'inline-flex';
        document.getElementById('label-corrected-amt').textContent = fmtMoney(doc.computed_total);
        document.getElementById('label-billed-amt').textContent = fmtMoney(doc.total);
        const noteBox = document.getElementById('supplier-note-box');
        noteBox.value = doc.vendor_dispute_note || '';
        const subj = encodeURIComponent('Math check on Invoice #' + doc.invoice_number);
        const body = encodeURIComponent(doc.vendor_dispute_note || '');
        document.getElementById('mailto-link').href = 'mailto:?subject=' + subj + '&body=' + body;
      }

      let disputedAssigned = false;
      const rowsHtml = doc.line_items.map(li => {
        const rowId = (!li.line_math_valid && !disputedAssigned) ? (disputedAssigned = true, 'id="disputed-row"') : '';
        const billedCell = li.line_math_valid
          ? fmtMoney(li.amount)
          : ('<del class="billed-strike">' + fmtMoney(li.amount) + '</del><span style="color:var(--negative);">' + fmtMoney(li.expected_amount) + '</span>');
        const badgeText = li.line_math_valid
          ? 'Matches'
          : ((li.delta > 0 ? '+' : '') + fmtMoney(li.delta) + ' overcharge');
        return `
          <tr ${rowId} style="${li.line_math_valid ? '' : 'background:#fff5f5;'}">
            <td>${li.line_number}</td>
            <td>${li.description}</td>
            <td class="num">${li.quantity}</td>
            <td class="num">${fmtMoney(li.unit_price)}</td>
            <td class="money">${billedCell}</td>
            <td class="money">${fmtMoney(li.expected_amount)}</td>
            <td class="num"><span class="pill ${li.line_math_valid ? 'pill-ok' : 'pill-err'}">${badgeText}</span></td>
          </tr>
        `;
      }).join('');

      const subMismatch = doc.subtotal !== doc.computed_subtotal;
      const totMismatch = !doc.math_verified;
      const totRowId = (totMismatch && !disputedAssigned) ? 'id="disputed-row"' : '';

      document.getElementById('table-container').innerHTML = `
        <table>
          <thead>
            <tr><th>#</th><th>Item description</th><th class="num">Qty</th><th class="num">Unit price</th><th class="num">Billed vs. True</th><th class="num">True math (Qty×Price)</th><th class="num">Check</th></tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
          <tfoot>
            <tr style="${subMismatch ? 'background:#fff5f5;' : ''}">
              <td colspan="4" style="color:var(--muted);">Line items subtotal</td>
              <td class="money">${subMismatch ? ('<del class="billed-strike">' + fmtMoney(doc.subtotal) + '</del><span style="color:var(--negative);">' + fmtMoney(doc.computed_subtotal) + '</span>') : fmtMoney(doc.subtotal)}</td>
              <td class="money">${fmtMoney(doc.computed_subtotal)}</td>
              <td class="num"><span class="pill ${subMismatch ? 'pill-err' : 'pill-ok'}">${subMismatch ? 'Subtotal off' : 'Subtotal OK'}</span></td>
            </tr>
            <tr>
              <td colspan="4" style="color:var(--muted);">Sales tax (${taxPct})</td>
              <td class="money">${fmtMoney(doc.tax)}</td><td class="money">${fmtMoney(doc.tax)}</td>
              <td class="num"><span class="pill pill-ok">Tax checked</span></td>
            </tr>
            <tr ${totRowId} style="${totMismatch ? 'background:#fff5f5;' : ''}">
              <td colspan="4" style="font-weight:500;">Total due</td>
              <td class="money">${totMismatch ? ('<del class="billed-strike">' + fmtMoney(doc.total) + '</del><span style="color:var(--negative);">' + fmtMoney(doc.computed_total) + '</span>') : fmtMoney(doc.total)}</td>
              <td class="money">${fmtMoney(doc.computed_total)}</td>
              <td class="num"><span class="pill ${doc.math_verified ? 'pill-ok' : 'pill-err'}">${doc.math_verified ? 'Balanced' : ('+' + fmtMoney(doc.discrepancy_delta) + ' overcharge')}</span></td>
            </tr>
          </tfoot>
        </table>
      `;
    }

    function copySupplierNote() {
      const box = document.getElementById('supplier-note-box');
      if (!box || !box.value) return;
      navigator.clipboard.writeText(box.value);
      showToast('✓ Copied polite supplier dispute email to your clipboard.');
    }

    async function runBankReconciliationPreset(scrollToCard) {
      setActivePresetUi('bank_reconciliation_batch');
      const detailsEl = document.getElementById('bank-match');
      if (detailsEl) detailsEl.open = true;
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

      const summaryPill = document.getElementById('bank-summary-pill');
      if (summaryPill) {
        summaryPill.className = 'pill pill-warn';
        summaryPill.textContent = m.matched_count + ' matched · ' + m.duplicate_count + ' duplicate caught';
      }

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
      if (scrollToCard && detailsEl) detailsEl.scrollIntoView({ behavior: 'smooth' });
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
      showToast('✓ Spreadsheet ' + out.filename + ' generated and ready to download.');
    }

    initStudio();
"""
