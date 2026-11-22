"""
Client-side controller script for the SchemaExtract Accounting Workbench (`GET /`).
Combines `STUDIO_RENDER_JS` with event/network/quota controllers (< 400 lines per module).
"""

from app.studio_events import STUDIO_EVENTS_JS
from app.studio_render import STUDIO_RENDER_JS

STUDIO_CONTROLLER_JS = """
    let PRESETS = {};
    let LAST_EXTRACTED = null;
    let BATCH_QUEUE = [];
    let LAST_RECON = null;
    let CURRENT_API_KEY = null;
    let RECON_REQ_SEQ = 0;

    const SAMPLE_LABELS = {
      messy_saas_invoice: "Sample: Bakery supply bill (Balanced)",
      discrepant_contractor_invoice: "Sample: Plumbing bill ($200 overcharge)",
      cam_reconciliation_statement: "Sample: CAM lease statement ($350 overcharge)",
      bank_reconciliation_batch: "Sample: October bank statement"
    };

    const VERTICAL_ROUTES = {
      "bank-statement-to-qbo-csv": { preset: "bank_reconciliation_batch", openRecon: true },
      "supplier-invoice": { preset: "messy_saas_invoice", openRecon: false },
      "contractor-invoice": { preset: "discrepant_contractor_invoice", openRecon: false },
      "cam-reconciliation": { preset: "cam_reconciliation_statement", openRecon: false }
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
      ['messy_saas_invoice', 'discrepant_contractor_invoice', 'cam_reconciliation_statement', 'bank_reconciliation_batch'].forEach(k => {
        const b = document.getElementById('btn-' + k);
        const s = document.getElementById('side-' + k);
        if (b) b.classList.toggle('active-preset', k === id);
        if (s) s.classList.toggle('active', k === id);
      });
      const pill = document.getElementById('active-sample-pill');
      if (pill && SAMPLE_LABELS[id]) pill.textContent = SAMPLE_LABELS[id];
    }

    function setPrivacyBadge(mode) {
      const el = document.getElementById('privacy-mode-badge');
      if (!el) return;
      if (mode === 'ocr') {
        el.innerHTML = '<strong>Zero-Retention OCR:</strong> File parsed in memory and purged immediately.';
      } else {
        el.innerHTML = '<strong>Zero-Retention Privacy:</strong> Text checked in ephemeral memory only.';
      }
    }

    function wipeSessionNow() {
      RECON_REQ_SEQ += 1;
      clearInput();
      LAST_RECON = null;
      const kpiDefaults = {
        'kpi-billed': '$0.00',
        'kpi-computed': '$0.00',
        'kpi-delta': '$0.00',
        'kpi-vendor': 'Session wiped — ready for next bill',
        'kpi-invoice-no': 'No active bill',
        'kpi-status-caption': 'Paste or drop a bill to check',
        'label-corrected-amt': '$0.00',
        'label-billed-amt': '$0.00',
        'compliance-caption': 'Included in your Excel & CSV exports'
      };
      Object.entries(kpiDefaults).forEach(([id, val]) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
      });
      const deltaEl = document.getElementById('kpi-delta');
      if (deltaEl) deltaEl.style.color = 'var(--text)';
      const noteEl = document.getElementById('supplier-note-box');
      if (noteEl) noteEl.value = '';
      const mailEl = document.getElementById('mailto-link');
      if (mailEl) mailEl.href = 'mailto:';
      const bankCsvEl = document.getElementById('bank-csv-input');
      if (bankCsvEl) bankCsvEl.value = '';
      const reconBox = document.getElementById('bank-recon-container');
      if (reconBox) reconBox.textContent = 'Upload or paste your bank statement CSV above to match against your checked bill(s), or click "Try October sample (demo data)".';
      const reconPill = document.getElementById('bank-summary-pill');
      if (reconPill) { reconPill.className = 'pill pill-neutral'; reconPill.textContent = 'Click to expand'; }
      const dlStatus = document.getElementById('download-status');
      if (dlStatus) dlStatus.textContent = '';
      try {
        if (window.localStorage) {
          ['bt_pref_category', 'bt_pref_export_mode'].forEach(k => window.localStorage.removeItem(k));
        }
      } catch (_e) { /* ignore storage errors */ }
      setPrivacyBadge('local');
      showToast('Session wiped: cleared bill text, KPIs, dispute draft, batch queue, bank match, and saved preferences.');
    }

    let AUDIT_LINK_IN_FLIGHT = false;
    async function copyVerifiedAuditLink() {
      const docRef = LAST_EXTRACTED;
      if (!docRef) { showToast('Check a supplier bill first to create a Verified Dispute Link.'); return; }
      if (AUDIT_LINK_IN_FLIGHT) return;
      const hasRecon = Boolean(LAST_RECON);
      const cached = docRef.verified_audit_link;
      if (cached && cached.audit_url && Boolean(cached._has_recon) === hasRecon) {
        copyTextSafe(cached.audit_url, 'Copied Verified Dispute Link: ' + cached.audit_url);
        return;
      }
      AUDIT_LINK_IN_FLIGHT = true;
      try {
        const res = await fetch('/api/audit-link', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ document: docRef, reconciliation: LAST_RECON }),
          signal: (typeof AbortSignal !== 'undefined' && AbortSignal.timeout) ? AbortSignal.timeout(15000) : undefined
        });
        const meta = await res.json().catch(() => ({}));
        if (LAST_EXTRACTED !== docRef) return;
        if (!res.ok || !meta.audit_url) { showToast('Unable to create Verified Dispute Link.'); return; }
        meta._has_recon = hasRecon;
        docRef.verified_audit_link = meta;
        copyTextSafe(meta.audit_url, 'Copied Verified Dispute Link: ' + meta.audit_url);
      } catch (_e) {
        if (LAST_EXTRACTED === docRef) showToast('Network error while creating Verified Dispute Link.');
      } finally {
        AUDIT_LINK_IN_FLIGHT = false;
      }
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

    async function readAndCheckFile(file) {
      if (!file) return;
      if (file.size > 5000000) {
        showBannerError('File exceeds the 5 MB limit. Please upload a PDF, image, Excel, or CSV under 5 MB.');
        return;
      }
      const prog = document.getElementById('upload-progress');
      const pill = document.getElementById('active-sample-pill');
      if (prog) { prog.removeAttribute('value'); prog.hidden = false; }
      if (pill) pill.textContent = 'Extracting ' + file.name + '...';
      setActivePresetUi('');
      const fd = new FormData();
      fd.append('file', file);
      fd.append('document_type', 'invoice');
      if (CURRENT_API_KEY) fd.append('api_key', CURRENT_API_KEY);
      try {
        const res = await fetch('/api/extract-file', { method: 'POST', body: fd, signal: (typeof AbortSignal !== 'undefined' && AbortSignal.timeout) ? AbortSignal.timeout(25000) : undefined });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          showBannerError(data.detail || data.error || ('Unable to extract file (HTTP ' + res.status + ').'));
          await refreshQuota();
          return;
        }
        document.getElementById('raw-doc-input').value = String(data.extracted_text || '');
        if (pill) pill.textContent = 'File: ' + file.name;
        updateLineCount(false);
        LAST_EXTRACTED = data;
        setPrivacyBadge('ocr');
        renderExtractedTable(LAST_EXTRACTED);
        await refreshQuota();
        showToast('Extracted & checked ' + file.name + ' to the penny.');
      } catch (err) {
        showBannerError('Network error while uploading file: ' + (err && err.message ? err.message : String(err)));
      } finally {
        if (prog) prog.hidden = true;
      }
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
        showBannerError('Please drop a PDF/Excel/CSV/image file or paste supplier bill text first.');
        return;
      }
      if (rawText.startsWith('%PDF-')) {
        showBannerError('Raw PDF bytes detected in text box. Drop or select your .pdf file in the file dropzone above.');
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
      if (!LAST_EXTRACTED) { showToast('Check a supplier bill first before adding it to your batch queue.'); return; }
      const dup = BATCH_QUEUE.find(d => d.invoice_number === LAST_EXTRACTED.invoice_number && d.vendor === LAST_EXTRACTED.vendor);
      if (dup) { showToast('Duplicate bill warning: Bill #' + LAST_EXTRACTED.invoice_number + ' is already in your batch queue.'); return; }
      BATCH_QUEUE.push(LAST_EXTRACTED);
      renderBatchCounter();
      showToast('Added Bill #' + LAST_EXTRACTED.invoice_number + ' to batch queue (' + BATCH_QUEUE.length + ' total).');
    }

    function updateExportModeLabel() {
      const useCorr = document.getElementById('mode-corrected') && document.getElementById('mode-corrected').checked;
      safeSetStorage('bt_pref_export_mode', useCorr ? 'corrected' : 'billed');
      showToast(useCorr ? 'Export mode set to: Verified true math total.' : 'Export mode set to: Hold billed total for supplier credit note.');
    }

    function copyTextSafe(text, okMsg) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => showToast(okMsg)).catch(() => showToast('Clipboard unavailable. Select and copy manually.'));
      } else {
        showToast('Clipboard unavailable. Select and copy manually.');
      }
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
      copyTextSafe(summary, 'Copied 5-line verified bill summary for Slack / Email.');
    }

    function copySupplierNote() {
      const box = document.getElementById('supplier-note-box');
      if (box && box.value) copyTextSafe(box.value, 'Copied polite supplier dispute email to your clipboard.');
    }

    async function callReconcileMcp(reqId, argsObj) {
      const rpcReq = {
        jsonrpc: "2.0", id: reqId, method: "tools/call",
        params: { name: "reconcile_invoices_with_bank_ledger", arguments: argsObj }
      };
      const res = await fetch('/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(rpcReq),
        signal: (typeof AbortSignal !== 'undefined' && AbortSignal.timeout) ? AbortSignal.timeout(15000) : undefined
      });
      const rpcRes = await res.json().catch(() => ({}));
      return { ok: res.ok, rpcRes };
    }

    async function runCustomBankReconciliation() {
      const bankCsv = (document.getElementById('bank-csv-input') && document.getElementById('bank-csv-input').value || '').trim().slice(0, 250000);
      if (!bankCsv) {
        showToast('Upload or paste your bank statement CSV first — or click "Try October sample (demo data)".');
        return;
      }
      if (!LAST_EXTRACTED) await runExtractMcp();
      const docs = BATCH_QUEUE.length > 0 ? BATCH_QUEUE : (LAST_EXTRACTED ? [LAST_EXTRACTED] : []);
      if (docs.length === 0) {
        showToast('Check at least one supplier bill in Step 1 first.');
        return;
      }
      const useCorr = document.getElementById('mode-corrected') ? document.getElementById('mode-corrected').checked : false;
      const invoices = docs.map(d => ({
        invoice_number: d.invoice_number || 'INV-UNKNOWN',
        vendor: d.vendor || 'Unknown Supplier',
        date: d.issue_date || '2026-10-01',
        total: Number(useCorr ? (d.computed_total != null ? d.computed_total : d.total) : d.total) || 0,
        currency: d.currency || 'USD'
      }));
      const mySeq = ++RECON_REQ_SEQ;
      try {
        const { ok, rpcRes } = await callReconcileMcp('studio-recon-custom', { invoices, bank_csv_text: bankCsv, date_tolerance_days: 7 });
        if (mySeq !== RECON_REQ_SEQ) return;
        if (!ok || rpcRes.error || !rpcRes.result || rpcRes.result.isError || !rpcRes.result.structuredContent) {
          const rawMsg = (rpcRes.result && rpcRes.result.content && rpcRes.result.content[0] && rpcRes.result.content[0].text) || '';
          const friendly = (!rawMsg || /validation error|Tool execution error:|bank_transactions/i.test(rawMsg))
            ? 'Could not read any withdrawals from that bank CSV. Include Date, Description, and Amount columns.'
            : rawMsg;
          showToast(friendly);
          return;
        }
        LAST_RECON = rpcRes.result.structuredContent;
        renderReconResult(LAST_RECON, 'Your Bank Statement Summary', false);
        showToast('Matched ' + docs.length + ' checked bill(s) against your bank statement CSV.');
      } catch (err) {
        if (mySeq === RECON_REQ_SEQ) showToast('Network error during bank statement check: ' + (err && err.message ? err.message : String(err)));
      }
    }

    async function runBankReconciliationPreset(scrollToCard) {
      setActivePresetUi('bank_reconciliation_batch');
      const detailsEl = document.getElementById('bank-match');
      if (detailsEl) detailsEl.open = true;
      const preset = PRESETS['bank_reconciliation_batch'];
      if (!preset) return;
      const mySeq = ++RECON_REQ_SEQ;
      try {
        const { ok, rpcRes } = await callReconcileMcp('studio-recon-1', {
          invoices: preset.invoices, bank_transactions: preset.bank_transactions, date_tolerance_days: 7
        });
        if (mySeq !== RECON_REQ_SEQ) return;
        if (!ok || rpcRes.error || !rpcRes.result || rpcRes.result.isError || !rpcRes.result.structuredContent) {
          showToast('Unable to run October sample bank check.');
          return;
        }
        LAST_RECON = rpcRes.result.structuredContent;
        renderReconResult(LAST_RECON, 'October Sample Demo Summary', true);
        showToast('Loaded October sample bank statement (demo data).');
        if (scrollToCard && detailsEl) detailsEl.scrollIntoView({ behavior: scrollBehaviorPref() });
      } catch (err) {
        if (mySeq === RECON_REQ_SEQ) showToast('Network error during bank statement check: ' + (err && err.message ? err.message : String(err)));
      }
    }

    async function exportBundle(fmt) {
      /* Uses /api/export (server-gated equivalent of MCP export_ledger_bundle) */
      if (!LAST_EXTRACTED) await runExtractMcp();
      if (!LAST_EXTRACTED) return;
      const catEl = document.getElementById('category-select');
      if (catEl) LAST_EXTRACTED.suggested_category = catEl.value;
      const docsToExport = BATCH_QUEUE.length > 0 ? BATCH_QUEUE : [LAST_EXTRACTED];
      const freeExportsUsed = Number(safeGetStorage('bt_free_exports_used') || '0');
      const upgradeHtml = 'Free tier includes 3 spreadsheet exports (up to 3 bills). <a href="https://buy.stripe.com/bJedR9cK12BN90903MfAc01" target="_blank" rel="noopener noreferrer" style="color:var(--positive); font-weight:600; text-decoration:underline;">Unlock $49.99 One-Time Pro Pass →</a>';
      if (!CURRENT_API_KEY && (docsToExport.length > 3 || freeExportsUsed >= 3)) {
        document.getElementById('download-status').innerHTML = upgradeHtml;
        showToast('Unlock the $49.99 One-Time Pro Pass for unlimited multi-bill Excel & QuickBooks exports.');
        return;
      }
      const useCorrected = document.getElementById('mode-corrected') ? document.getElementById('mode-corrected').checked : false;
      const slug = String(LAST_EXTRACTED.invoice_number || 'checked_bills').toLowerCase();
      const payload = { documents: docsToExport, reconciliation: LAST_RECON, format: fmt, bundle_name: slug + "_ledger", use_corrected_amounts: useCorrected, api_key: CURRENT_API_KEY };
      try {
        const res = await fetch('/api/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: (typeof AbortSignal !== 'undefined' && AbortSignal.timeout) ? AbortSignal.timeout(25000) : undefined });
        const out = await res.json().catch(() => ({}));
        if (res.status === 402) {
          document.getElementById('download-status').innerHTML = upgradeHtml;
          showToast(out.detail || 'Free export limit reached. Unlock the $49.99 One-Time Pro Pass.');
          return;
        }
        if (!res.ok || !out || !out.download_url) {
          showToast(out.detail || 'Unable to generate spreadsheet export.');
          return;
        }
        if (!CURRENT_API_KEY) safeSetStorage('bt_free_exports_used', String(freeExportsUsed + 1));
        const safeHref = safeDownloadHref(out.download_url);
        document.getElementById('download-status').innerHTML =
          'Your spreadsheet <strong>' + escHtml(out.filename) + '</strong> (' + Number(out.size_bytes) + ' bytes, SHA-256 verified) is ready: <a href="' + escHtml(safeHref) + '" style="color:var(--chart-3); text-decoration:underline;">Click here to download</a>';
        showToast('Spreadsheet ' + out.filename + ' generated and ready to download.');
      } catch (err) {
        showToast('Export failed: ' + (err && err.message ? err.message : String(err)));
      }
    }
"""

STUDIO_CLIENT_JS = STUDIO_RENDER_JS + "\n" + STUDIO_CONTROLLER_JS + "\n" + STUDIO_EVENTS_JS
