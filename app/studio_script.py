"""
Client-side controller script for the SchemaExtract Accounting Workbench (`GET /`).
Combines `STUDIO_RENDER_JS` with event/network/quota controllers (< 400 lines per module).
"""

from app.studio_events import STUDIO_EVENTS_JS
from app.studio_export_js import STUDIO_EXPORT_JS
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
      bar.classList.add('is-visible');
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

    function resetKpiStrip(vendorMsg) {
      const kpiDefaults = {
        'kpi-billed': '$0.00',
        'kpi-computed': '$0.00',
        'kpi-delta': '$0.00',
        'kpi-vendor': vendorMsg || 'Ready for your bill or bank CSV',
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
    }

    function wipeSessionNow() {
      RECON_REQ_SEQ += 1;
      clearInput({ focusRaw: true, silent: true });
      LAST_RECON = null;
      resetKpiStrip('Session wiped — ready for next bill');
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
        const headers = CURRENT_API_KEY ? { 'X-API-Key': CURRENT_API_KEY } : {};
        const res = await fetch('/api/quota', { headers });
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
          if (typeof window.gtag === 'function') {
            window.gtag('event', 'conversion', {
              send_to: window.__BT_GADS_ID || 'AW-18526471751',
              value: 49.99,
              currency: 'USD',
              transaction_id: checkoutSessionId
            });
          }
          showToast('Pro Plan Activated: 5,000 bills/month unlocked.');
        }
      } catch (_e) { await refreshQuota(); }
    }

    function clearInput(opts) {
      const cfg = (opts && typeof opts === 'object') ? opts : {};
      const focusRaw = cfg.focusRaw !== false;
      const silent = Boolean(cfg.silent);
      const el = document.getElementById('raw-doc-input');
      if (el) {
        el.value = '';
        el.placeholder = 'Paste your supplier bill, receipt, or statement lines here...';
        if (focusRaw) el.focus();
      }
      LAST_EXTRACTED = null;
      BATCH_QUEUE = [];
      renderBatchCounter();
      setActivePresetUi('');
      updateLineCount(true);
      resetKpiStrip();
      const tableWrap = document.getElementById('table-container');
      if (tableWrap) tableWrap.innerHTML = '';
      const actionsBox = document.getElementById('discrepancy-actions');
      if (actionsBox) actionsBox.style.display = 'none';
      const banner = document.getElementById('audit-banner');
      if (banner) {
        banner.className = 'banner banner-warn';
        banner.innerHTML = '<div>Paste or drop a supplier bill on the left and click <strong>Check bill math to the penny</strong>.</div><span class="pill pill-neutral">Ready</span>';
      }
      if (!silent) showToast('Cleared bill text and batch queue. Paste or drop your own bill to check.');
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
      const deltaNum = Number(d.discrepancy_delta || 0);
      const isManual = !d.math_verified && (Math.abs(deltaNum) < 0.005 || !Array.isArray(d.line_items) || d.line_items.length === 0);
      const verdict = d.math_verified
        ? ('Balanced to the penny (' + fmtMoney(d.total) + ')')
        : (isManual
          ? ('Manual Review Required (Billed ' + fmtMoney(d.total) + '; review line items)')
          : ((deltaNum >= 0 ? 'Overcharge Caught' : 'Under-Billing Caught') + ' (Billed ' + fmtMoney(d.total) + ' vs True Math ' + fmtMoney(d.computed_total) + ')'));
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
"""

STUDIO_CLIENT_JS = STUDIO_RENDER_JS + "\n" + STUDIO_CONTROLLER_JS + "\n" + STUDIO_EXPORT_JS + "\n" + STUDIO_EVENTS_JS
