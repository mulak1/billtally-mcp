"""
Client-side controller script for the SchemaExtract Accounting Workbench (`GET /`).
Combines `STUDIO_RENDER_JS` with event/network/quota controllers (< 400 lines per module).
"""

from app.studio_render import STUDIO_RENDER_JS

STUDIO_CONTROLLER_JS = """
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

    function safeGetStorage(key) {
      try { return window.localStorage ? window.localStorage.getItem(key) : null; }
      catch (_e) { return null; }
    }

    function safeSetStorage(key, val) {
      try { if (window.localStorage) window.localStorage.setItem(key, val); }
      catch (_e) { /* restricted storage context */ }
    }

    function setGreetingByHour() {
      const hr = new Date().getHours();
      const tod = hr < 12 ? "Good morning" : (hr < 18 ? "Good afternoon" : "Good evening");
      const h = document.getElementById("greeting-heading");
      if (h) h.textContent = tod + ". Welcome to your Bill & Bank Math Check Desk";
    }

    function showToast(msg) {
      const bar = document.getElementById('toast-bar');
      const txt = document.getElementById('toast-text');
      if (!bar || !txt) return;
      txt.textContent = msg;
      bar.style.display = 'flex';
    }

    function renderBatchCounter() {
      const el = document.getElementById('batch-counter-text');
      if (!el) return;
      if (BATCH_QUEUE.length === 0) {
        el.innerHTML = '<strong>Batch Queue:</strong> 0 bills queued (exports active bill)';
      } else {
        el.innerHTML = '<strong>Batch Queue:</strong> ' + BATCH_QUEUE.length + ' bill' + (BATCH_QUEUE.length === 1 ? '' : 's') + ' ready to export together';
      }
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

    function showBannerError(msg) {
      LAST_EXTRACTED = null;
      const banner = document.getElementById('audit-banner');
      const actionsBox = document.getElementById('discrepancy-actions');
      const tableWrap = document.getElementById('table-container');
      if (banner) {
        banner.className = 'banner banner-err';
        banner.innerHTML = '<div>' + SVG_ALERT + ' <strong>Unable to check bill:</strong> ' + escHtml(msg) + '</div><span class="pill pill-err">Action required</span>';
      }
      if (actionsBox) actionsBox.style.display = 'none';
      if (tableWrap) tableWrap.innerHTML = '';
      showToast(msg);
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
      try {
        const qUrl = CURRENT_API_KEY ? ('/api/quota?api_key=' + encodeURIComponent(CURRENT_API_KEY)) : '/api/quota';
        const res = await fetch(qUrl);
        if (!res.ok) return null;
        const q = await res.json();
        document.getElementById('tier-name').textContent = q.tier === 'pro' ? 'Pro Plan' : 'Free Plan';
        document.getElementById('quota-used').textContent = q.used;
        document.getElementById('quota-limit').textContent = q.limit;
        if (q.tier === 'pro') {
          const hLink = document.getElementById('headerUpgradeLink');
          if (hLink) hLink.textContent = 'Pro Plan Active ($49.99 Pass)';
          const sLink = document.getElementById('sidebarUpgradeLink');
          if (sLink) sLink.textContent = 'Pro Plan Active';
        }
        return q;
      } catch (_e) {
        return null;
      }
    }

    async function applySavedProKey() {
      const inp = document.getElementById('pro-api-key-input');
      const val = inp ? inp.value.trim() : '';
      if (!val.startsWith('se_pro_')) { showToast('Enter a valid BillTally Pro key starting with se_pro_'); return; }
      CURRENT_API_KEY = val;
      const q = await refreshQuota();
      if (!q || q.tier !== 'pro') {
        CURRENT_API_KEY = null;
        showToast('Invalid or unverified Pro API key. Complete Stripe checkout to receive a signed key.');
        return;
      }
      safeSetStorage('bt_pro_api_key', val);
      showToast('Pro API key activated (5,000 bills/month).');
    }

    async function activatePaidProSession(checkoutSessionId) {
      if (!checkoutSessionId || !checkoutSessionId.startsWith('cs_')) return;
      try {
        const res = await fetch('/api/quota/upgrade', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ checkout_session_id: checkoutSessionId })
        });
        if (!res.ok) { await refreshQuota(); return; }
        const q = await res.json();
        if (q && q.api_key) {
          CURRENT_API_KEY = q.api_key;
          safeSetStorage('bt_pro_api_key', q.api_key);
          await refreshQuota();
          showToast('Pro Plan Activated: 5,000 bills/month unlocked.');
        }
      } catch (_e) { await refreshQuota(); }
    }

    function clearInput() {
      const el = document.getElementById('raw-doc-input');
      if (el) {
        el.value = '';
        el.placeholder = 'Paste your supplier bill, receipt, or statement lines here...';
        el.focus();
      }
      LAST_EXTRACTED = null;
      BATCH_QUEUE = [];
      renderBatchCounter();
      setActivePresetUi('');
      updateLineCount(true);
      const tableWrap = document.getElementById('table-container');
      if (tableWrap) tableWrap.innerHTML = '';
      const actionsBox = document.getElementById('discrepancy-actions');
      if (actionsBox) actionsBox.style.display = 'none';
      const banner = document.getElementById('audit-banner');
      if (banner) {
        banner.className = 'banner banner-warn';
        banner.innerHTML = '<div>Paste or drop a supplier bill on the left and click <strong>Check bill math to the penny</strong>.</div><span class="pill pill-neutral">Ready</span>';
      }
      showToast('Cleared bill text and batch queue. Paste or drop your own bill to check.');
    }

    function readAndCheckFile(file) {
      const reader = new FileReader();
      reader.onload = async (e) => {
        document.getElementById('raw-doc-input').value = String((e.target && e.target.result) || '');
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
      const rawText = (document.getElementById('raw-doc-input').value || '').trim();
      if (!rawText) {
        showBannerError('Please paste supplier bill text or choose a .txt/.csv file first.');
        return;
      }
      const rpcReq = {
        jsonrpc: "2.0", id: "studio-extract-1", method: "tools/call",
        params: { name: "extract_financial_documents", arguments: { raw_text: rawText, document_type: "invoice", api_key: CURRENT_API_KEY } }
      };
      try {
        const res = await fetch('/mcp', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(rpcReq) });
        const rpcRes = await res.json();
        if (!res.ok || rpcRes.error || !rpcRes.result || rpcRes.result.isError || !rpcRes.result.structuredContent) {
          const errText = (rpcRes.result && rpcRes.result.content && rpcRes.result.content[0] && rpcRes.result.content[0].text)
            || (rpcRes.error && rpcRes.error.message)
            || ('Request failed with HTTP ' + res.status);
          showBannerError(errText);
          await refreshQuota();
          return;
        }
        LAST_EXTRACTED = rpcRes.result.structuredContent;
        renderExtractedTable(LAST_EXTRACTED);
        await refreshQuota();
      } catch (err) {
        showBannerError('Network error while checking bill math: ' + (err && err.message ? err.message : String(err)));
      }
    }

    function addCurrentToBatch() {
      if (!LAST_EXTRACTED) {
        showToast('Check a supplier bill first before adding it to your batch queue.');
        return;
      }
      const dup = BATCH_QUEUE.find(d => d.invoice_number === LAST_EXTRACTED.invoice_number && d.vendor === LAST_EXTRACTED.vendor);
      if (dup) {
        showToast('Duplicate bill warning: Bill #' + LAST_EXTRACTED.invoice_number + ' is already in your batch queue.');
        return;
      }
      BATCH_QUEUE.push(LAST_EXTRACTED);
      renderBatchCounter();
      showToast('Added Bill #' + LAST_EXTRACTED.invoice_number + ' to batch queue (' + BATCH_QUEUE.length + ' total).');
    }

    function updateExportModeLabel() {
      const useCorr = document.getElementById('mode-corrected') && document.getElementById('mode-corrected').checked;
      showToast(useCorr
        ? 'Export mode set to: Verified true math total.'
        : 'Export mode set to: Hold billed total for supplier credit note.');
    }

    function copyVerifiedSummary() {
      if (!LAST_EXTRACTED) { showToast('Check a supplier bill first to copy its summary.'); return; }
      const d = LAST_EXTRACTED;
      const verdict = d.math_verified
        ? ('Balanced to the penny (' + fmtMoney(d.total) + ')')
        : ((Number(d.discrepancy_delta) >= 0 ? 'Overcharge Caught' : 'Under-Billing Caught') + ' (Billed ' + fmtMoney(d.total) + ' vs True Math ' + fmtMoney(d.computed_total) + ')');
      const summary = [
        'BillTally Verified Bill Summary',
        'Supplier: ' + d.vendor + ' (Invoice #' + d.invoice_number + ')',
        'Billed vs. True Math: ' + fmtMoney(d.total) + ' billed / ' + fmtMoney(d.computed_total) + ' verified',
        'Verdict: ' + verdict,
        'Line Items & Tax: ' + d.line_items.length + ' line items · Sales Tax ' + fmtMoney(d.tax) + ' (' + Number(d.effective_tax_rate_pct || 0).toFixed(2) + '%)'
      ].join('\\n');
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(summary)
          .then(() => showToast('Copied 5-line verified bill summary for Slack / Email.'))
          .catch(() => showToast('Clipboard unavailable. Select and copy the summary manually.'));
      } else {
        showToast('Clipboard unavailable. Select and copy the summary manually.');
      }
    }

    function copySupplierNote() {
      const box = document.getElementById('supplier-note-box');
      if (!box || !box.value) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(box.value)
          .then(() => showToast('Copied polite supplier dispute email to your clipboard.'))
          .catch(() => showToast('Clipboard unavailable. Select and copy the note manually.'));
      } else {
        showToast('Clipboard unavailable. Select and copy the note manually.');
      }
    }

    async function runBankReconciliationPreset(scrollToCard) {
      setActivePresetUi('bank_reconciliation_batch');
      const detailsEl = document.getElementById('bank-match');
      if (detailsEl) detailsEl.open = true;
      const preset = PRESETS['bank_reconciliation_batch'];
      if (!preset) return;
      const rpcReq = {
        jsonrpc: "2.0", id: "studio-recon-1", method: "tools/call",
        params: {
          name: "reconcile_invoices_with_bank_ledger",
          arguments: { invoices: preset.invoices, bank_transactions: preset.bank_transactions, date_tolerance_days: 7 }
        }
      };
      try {
        const res = await fetch('/mcp', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(rpcReq) });
        const rpcRes = await res.json();
        if (!res.ok || !rpcRes.result || rpcRes.result.isError || !rpcRes.result.structuredContent) {
          showToast('Unable to run bank statement reconciliation.');
          return;
        }
        LAST_RECON = rpcRes.result.structuredContent;
        const m = LAST_RECON.summary_metrics;

        const summaryPill = document.getElementById('bank-summary-pill');
        if (summaryPill) {
          summaryPill.className = 'pill pill-warn';
          summaryPill.textContent = m.matched_count + ' matched · ' + m.duplicate_count + ' duplicate caught';
        }

        const matchedRows = LAST_RECON.matched.map(r => `
          <tr><td><span class="pill pill-ok">Matched payment</span></td><td>${escHtml(r.vendor)} (${escHtml(r.invoice_number)})</td><td>${escHtml(r.bank_date)}</td><td class="money">${escHtml(fmtMoney(r.bank_amount))}</td><td>Cleared in checking (no action needed)</td></tr>
        `).join('');
        const unpaidRows = LAST_RECON.unmatched_invoices.map(r => `
          <tr><td><span class="pill pill-warn">Unpaid bill</span></td><td>${escHtml(r.vendor)} (${escHtml(r.invoice_number)})</td><td>${escHtml(r.date)}</td><td class="money">${escHtml(fmtMoney(r.total))}</td><td>Schedule payment or accrue at month-end</td></tr>
        `).join('');
        const alertRows = LAST_RECON.unmatched_bank_txns.map(r => {
          const isDup = String(r.status || '').includes('DUPLICATE');
          const actionText = isDup ? ('Request ' + fmtMoney(r.amount) + ' refund from supplier') : 'Ask cardholder for store receipt';
          return `<tr style="background:#fff5f5;"><td><span class="pill pill-err">${isDup ? 'Duplicate charge caught' : 'Missing receipt'}</span></td><td>${escHtml(r.description)}</td><td>${escHtml(r.date)}</td><td class="money" style="color:var(--negative);">${escHtml(fmtMoney(r.amount))}</td><td>${escHtml(actionText)}</td></tr>`;
        }).join('');

        document.getElementById('bank-recon-container').innerHTML = `
          <div class="banner banner-warn" style="margin-top:8px;">
            <span><strong>October Checking Summary:</strong> ${Number(m.matched_count)} bills matched · ${Number(m.unmatched_invoice_count)} unpaid bill · ${Number(m.duplicate_count)} duplicate withdrawal (${escHtml(fmtMoney(m.duplicate_exposure))})</span>
            <span class="pill pill-err">Action needed</span>
          </div>
          <table>
            <thead><tr><th>Status</th><th>Supplier or bank description</th><th>Date</th><th class="num">Amount</th><th>Recommended bookkeeper action</th></tr></thead>
            <tbody>${matchedRows}${unpaidRows}${alertRows}</tbody>
          </table>
        `;
        if (scrollToCard && detailsEl) detailsEl.scrollIntoView({ behavior: scrollBehaviorPref() });
      } catch (err) {
        showToast('Network error during bank statement check: ' + (err && err.message ? err.message : String(err)));
      }
    }

    async function exportBundle(fmt) {
      if (!LAST_EXTRACTED) await runExtractMcp();
      if (!LAST_EXTRACTED) return;
      const catEl = document.getElementById('category-select');
      if (catEl) LAST_EXTRACTED.suggested_category = catEl.value;
      const docsToExport = BATCH_QUEUE.length > 0 ? BATCH_QUEUE : [LAST_EXTRACTED];
      const useCorrected = document.getElementById('mode-corrected') ? document.getElementById('mode-corrected').checked : false;
      const slug = String(LAST_EXTRACTED.invoice_number || 'checked_bills').toLowerCase();
      const rpcReq = {
        jsonrpc: "2.0", id: "studio-export-1", method: "tools/call",
        params: {
          name: "export_ledger_bundle",
          arguments: { documents: docsToExport, reconciliation: LAST_RECON, format: fmt, bundle_name: slug + "_ledger", use_corrected_amounts: useCorrected }
        }
      };
      try {
        const res = await fetch('/mcp', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(rpcReq) });
        const rpcRes = await res.json();
        if (!res.ok || !rpcRes.result || rpcRes.result.isError || !rpcRes.result.structuredContent) {
          const errText = (rpcRes.result && rpcRes.result.content && rpcRes.result.content[0] && rpcRes.result.content[0].text) || 'Unable to generate spreadsheet export.';
          showToast(errText);
          return;
        }
        const out = rpcRes.result.structuredContent;
        const safeHref = safeDownloadHref(out.download_url);
        document.getElementById('download-status').innerHTML =
          'Your spreadsheet <strong>' + escHtml(out.filename) + '</strong> (' + Number(out.size_bytes) + ' bytes, SHA-256 verified) is ready: <a href="' + escHtml(safeHref) + '" style="color:var(--chart-3); text-decoration:underline;">Click here to download</a>';
        showToast('Spreadsheet ' + out.filename + ' generated and ready to download.');
      } catch (err) {
        showToast('Export failed: ' + (err && err.message ? err.message : String(err)));
      }
    }

    function bindStudioEvents() {
      document.querySelectorAll('[data-preset]').forEach(el => {
        el.addEventListener('click', (ev) => {
          if (el.tagName === 'BUTTON') ev.preventDefault();
          loadPreset(el.getAttribute('data-preset'));
        });
      });
      document.querySelectorAll('[data-recon-scroll]').forEach(el => {
        el.addEventListener('click', (ev) => {
          if (el.tagName === 'BUTTON') ev.preventDefault();
          runBankReconciliationPreset(el.getAttribute('data-recon-scroll') === 'true');
        });
      });
      document.querySelectorAll('[data-export-format]').forEach(el => {
        el.addEventListener('click', (ev) => {
          if (el.tagName === 'BUTTON') ev.preventDefault();
          exportBundle(el.getAttribute('data-export-format'));
        });
      });
      const applyBtn = document.getElementById('apply-pro-key-btn');
      if (applyBtn) applyBtn.addEventListener('click', applySavedProKey);
      const copySumBtn = document.getElementById('copy-summary-btn');
      if (copySumBtn) copySumBtn.addEventListener('click', copyVerifiedSummary);
      const dismissBtn = document.getElementById('toast-dismiss-btn');
      if (dismissBtn) dismissBtn.addEventListener('click', () => { document.getElementById('toast-bar').style.display = 'none'; });
      const clearBtn = document.getElementById('clear-input-btn');
      if (clearBtn) clearBtn.addEventListener('click', clearInput);
      const runBtn = document.getElementById('run-extract-btn');
      if (runBtn) runBtn.addEventListener('click', runExtractMcp);
      const batchBtn = document.getElementById('add-batch-btn');
      if (batchBtn) batchBtn.addEventListener('click', addCurrentToBatch);
      const disputeBtn = document.getElementById('copy-dispute-btn');
      if (disputeBtn) disputeBtn.addEventListener('click', copySupplierNote);
      const reconBtn = document.getElementById('run-recon-btn');
      if (reconBtn) reconBtn.addEventListener('click', () => runBankReconciliationPreset(false));
      const modeCorr = document.getElementById('mode-corrected');
      const modeBill = document.getElementById('mode-billed');
      if (modeCorr) modeCorr.addEventListener('change', updateExportModeLabel);
      if (modeBill) modeBill.addEventListener('change', updateExportModeLabel);

      const rawInp = document.getElementById('raw-doc-input');
      if (rawInp) {
        rawInp.addEventListener('input', () => updateLineCount(true));
        rawInp.addEventListener('keydown', (ev) => {
          if (!ev.isComposing && (ev.metaKey || ev.ctrlKey) && ev.key === 'Enter') {
            ev.preventDefault();
            runExtractMcp();
          }
        });
      }

      const fileInp = document.getElementById('file-upload');
      if (fileInp) {
        fileInp.addEventListener('change', (ev) => {
          const file = ev.target && ev.target.files && ev.target.files[0];
          if (file) readAndCheckFile(file);
        });
      }

      const dz = document.getElementById('dropzone');
      if (dz) {
        dz.addEventListener('dragover', (ev) => { ev.preventDefault(); dz.classList.add('drag-over'); });
        dz.addEventListener('dragleave', (ev) => { ev.preventDefault(); dz.classList.remove('drag-over'); });
        dz.addEventListener('drop', (ev) => {
          ev.preventDefault();
          dz.classList.remove('drag-over');
          const file = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
          if (file) readAndCheckFile(file);
        });
      }
    }

    async function initStudio() {
      setGreetingByHour();
      bindStudioEvents();
      renderBatchCounter();
      const savedKey = safeGetStorage('bt_pro_api_key');
      if (savedKey) CURRENT_API_KEY = savedKey;
      try {
        const res = await fetch('/api/presets');
        if (res.ok) {
          const data = await res.json();
          (data.presets || []).forEach(p => { PRESETS[p.id] = p; });
        }
      } catch (_e) { /* offline fallback */ }

      const params = new URLSearchParams(window.location.search || '');
      const sid = params.get('session_id') || params.get('checkout_session_id') || '';
      if (sid.startsWith('cs_')) {
        await activatePaidProSession(sid);
      } else {
        await refreshQuota();
      }
      await loadPreset('messy_saas_invoice');
    }

    initStudio();
"""

STUDIO_CLIENT_JS = STUDIO_RENDER_JS + "\n" + STUDIO_CONTROLLER_JS
