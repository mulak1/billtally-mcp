"""
DOM event wiring and startup initialization for the BillTally Workbench (`GET /`).
Extracted from `studio_script.py` to keep every client module cleanly under the 500-line soft cap.
"""

STUDIO_EVENTS_JS = """
    async function handleBankCsvUpload(ev) {
      const f = ev.target && ev.target.files && ev.target.files[0];
      if (ev.target) ev.target.value = '';
      if (!f) return;
      if (f.size > 250000) {
        showToast('Bank CSV exceeds 250 KB (~2,500 rows). Please upload a single monthly statement CSV.');
        return;
      }
      try {
        const txt = await f.text();
        const ta = document.getElementById('bank-csv-input');
        if (ta) ta.value = txt;
        LAST_RECON = null;
        const reconBox = document.getElementById('bank-recon-container');
        if (reconBox) reconBox.textContent = 'Loaded ' + f.name + '. Click "Download QuickBooks 3-Column CSV (.csv)" or "Match Against Checked Bill(s)".';
        const pill = document.getElementById('bank-summary-pill');
        if (pill) { pill.className = 'pill pill-ok'; pill.textContent = 'CSV loaded · Ready'; }
        showToast('Loaded ' + f.name + ' locally. Click "Download QuickBooks 3-Column CSV (.csv)" to convert.');
      } catch (_e) {
        showToast('Unable to read bank CSV file.');
      }
    }

    function bindStudioEvents() {
      document.querySelectorAll('[data-scroll-target]').forEach(el => {
        el.addEventListener('click', (ev) => {
          ev.preventDefault();
          const targetId = el.getAttribute('data-scroll-target');
          const target = targetId ? document.getElementById(targetId) : null;
          if (!target) return;
          if (target.tagName === 'DETAILS') target.open = true;
          target.scrollIntoView({ behavior: scrollBehaviorPref(), block: 'start' });
        });
      });
      document.querySelectorAll('[data-preset]').forEach(el => {
        el.addEventListener('click', (ev) => {
          ev.preventDefault();
          loadPreset(el.getAttribute('data-preset'));
        });
      });
      document.querySelectorAll('[data-recon-scroll]').forEach(el => {
        el.addEventListener('click', (ev) => {
          ev.preventDefault();
          runBankReconciliationPreset(el.getAttribute('data-recon-scroll') === 'true');
        });
      });
      document.querySelectorAll('[data-export-format]').forEach(el => {
        el.addEventListener('click', (ev) => {
          ev.preventDefault();
          exportBundle(el.getAttribute('data-export-format'));
        });
      });
      const applyBtn = document.getElementById('apply-pro-key-btn');
      if (applyBtn) applyBtn.addEventListener('click', applySavedProKey);
      const copySumBtn = document.getElementById('copy-summary-btn');
      if (copySumBtn) copySumBtn.addEventListener('click', copyVerifiedSummary);
      const dismissBtn = document.getElementById('toast-dismiss-btn');
      if (dismissBtn) dismissBtn.addEventListener('click', () => { document.getElementById('toast-bar').classList.remove('is-visible'); });
      const clearBtn = document.getElementById('clear-input-btn');
      if (clearBtn) clearBtn.addEventListener('click', () => clearInput());
      const wipeBtn = document.getElementById('wipe-session-btn');
      if (wipeBtn) wipeBtn.addEventListener('click', wipeSessionNow);
      const runBtn = document.getElementById('run-extract-btn');
      if (runBtn) runBtn.addEventListener('click', runExtractMcp);
      const batchBtn = document.getElementById('add-batch-btn');
      if (batchBtn) batchBtn.addEventListener('click', addCurrentToBatch);
      const disputeBtn = document.getElementById('copy-dispute-btn');
      if (disputeBtn) disputeBtn.addEventListener('click', copySupplierNote);
      const auditLinkBtn = document.getElementById('copy-audit-link-btn');
      if (auditLinkBtn) auditLinkBtn.addEventListener('click', copyVerifiedAuditLink);
      const catSel = document.getElementById('category-select');
      if (catSel) catSel.addEventListener('change', () => safeSetStorage('bt_pref_category', catSel.value));
      const reconBtn = document.getElementById('run-recon-btn');
      if (reconBtn) reconBtn.addEventListener('click', () => runBankReconciliationPreset(false));
      const bankQboBtn = document.getElementById('export-bank-qbo-btn');
      if (bankQboBtn) bankQboBtn.addEventListener('click', exportBankCsvToQbo);
      const customReconBtn = document.getElementById('run-custom-recon-btn');
      if (customReconBtn) customReconBtn.addEventListener('click', runCustomBankReconciliation);
      const bankCsvFile = document.getElementById('bank-csv-file');
      if (bankCsvFile) bankCsvFile.addEventListener('change', handleBankCsvUpload);
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
          if (ev.target) ev.target.value = '';
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
      const params = new URLSearchParams(window.location.search || '');
      const verticalKey = (params.get('vertical') || '').trim().toLowerCase();
      const modeParam = (params.get('mode') || '').trim().toLowerCase();
      if (modeParam === 'upload') {
        clearInput({ focusRaw: verticalKey !== 'bank-statement-to-qbo-csv', silent: true });
        if (verticalKey === 'bank-statement-to-qbo-csv') {
          const detailsEl = document.getElementById('bank-match');
          if (detailsEl) detailsEl.open = true;
        }
      }
      const savedKey = safeGetStorage('bt_pro_api_key');
      if (savedKey) CURRENT_API_KEY = savedKey;
      try {
        const res = await fetch('/api/presets');
        if (res.ok) {
          const data = await res.json();
          (data.presets || []).forEach(p => { PRESETS[p.id] = p; });
        }
      } catch (_e) { /* offline fallback */ }

      const sid = params.get('session_id') || params.get('checkout_session_id') || '';
      if (sid.startsWith('cs_')) {
        await activatePaidProSession(sid);
      } else {
        await refreshQuota();
      }
      const savedMode = safeGetStorage('bt_pref_export_mode');
      if (savedMode === 'billed') {
        const mb = document.getElementById('mode-billed');
        if (mb) mb.checked = true;
      }

      const vCfg = VERTICAL_ROUTES[verticalKey];
      if (modeParam === 'upload' && verticalKey === 'bank-statement-to-qbo-csv') {
        const detailsEl = document.getElementById('bank-match');
        if (detailsEl) {
          detailsEl.open = true;
          detailsEl.scrollIntoView({ behavior: scrollBehaviorPref(), block: 'start' });
        }
        const bankInp = document.getElementById('bank-csv-input');
        if (bankInp) bankInp.focus();
      } else if (modeParam === 'upload') {
        /* already cleared synchronously above */
      } else if (vCfg) {
        await loadPreset(vCfg.preset);
        if (vCfg.openRecon) await runBankReconciliationPreset(true);
      } else {
        await loadPreset('messy_saas_invoice');
      }
      const savedCat = safeGetStorage('bt_pref_category');
      const catEl = document.getElementById('category-select');
      if (savedCat && catEl) catEl.value = savedCat;
    }

    initStudio();
"""
