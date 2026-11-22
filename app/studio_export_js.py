"""
Bank reconciliation and gated spreadsheet/QuickBooks CSV export controllers for the BillTally Workbench (`GET /`).
Extracted from `app/studio_script.py` so every client module stays cleanly under the 500-line soft cap.
"""

STUDIO_EXPORT_JS = """
    let EXPORT_IN_FLIGHT = false;
    const STRIPE_UPGRADE_HREF = 'https://buy.stripe.com/bJedR9cK12BN90903MfAc01';

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

    function triggerFileDownload(safeHref, filename) {
      if (!safeHref || safeHref === '#') return;
      try {
        const a = document.createElement('a');
        a.href = safeHref;
        a.download = String(filename || 'billtally_export');
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        a.remove();
      } catch (_e) { /* fallback link remains visible in #download-status */ }
    }

    async function postGatedExport(url, payload, opts) {
      if (EXPORT_IN_FLIGHT) return;
      const freeExportsUsed = Number(safeGetStorage('bt_free_exports_used') || '0');
      const upgradeHtml = 'Free tier includes 3 spreadsheet exports. <a href="' + STRIPE_UPGRADE_HREF + '" target="_blank" rel="noopener noreferrer" style="color:var(--positive); font-weight:600; text-decoration:underline;">Unlock $49.99 One-Time Pro Pass →</a>';
      const docCount = Number(opts && opts.docCount || 1);
      if (!CURRENT_API_KEY && (docCount > 3 || freeExportsUsed >= 3)) {
        document.getElementById('download-status').innerHTML = upgradeHtml;
        showToast(opts.limitToast || 'Unlock the $49.99 One-Time Pro Pass for unlimited exports.');
        return;
      }
      EXPORT_IN_FLIGHT = true;
      try {
        const res = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          signal: (typeof AbortSignal !== 'undefined' && AbortSignal.timeout) ? AbortSignal.timeout(25000) : undefined
        });
        const out = await res.json().catch(() => ({}));
        if (res.status === 402) {
          document.getElementById('download-status').innerHTML = upgradeHtml;
          showToast(out.detail || 'Free export limit reached. Unlock the $49.99 One-Time Pro Pass.');
          return;
        }
        if (!res.ok || !out || !out.download_url) {
          showToast(out.detail || opts.failToast || 'Unable to generate spreadsheet export.');
          return;
        }
        if (!CURRENT_API_KEY) safeSetStorage('bt_free_exports_used', String(freeExportsUsed + 1));
        const safeHref = safeDownloadHref(out.download_url);
        document.getElementById('download-status').innerHTML = opts.buildStatusHtml(out, safeHref);
        triggerFileDownload(safeHref, out.filename);
        showToast(opts.buildToast(out));
      } catch (err) {
        showToast((opts.errPrefix || 'Export failed: ') + (err && err.message ? err.message : String(err)));
      } finally {
        EXPORT_IN_FLIGHT = false;
      }
    }

    async function exportBankCsvToQbo() {
      const bankCsv = (document.getElementById('bank-csv-input') && document.getElementById('bank-csv-input').value || '').trim().slice(0, 250000);
      if (!bankCsv) {
        showToast('Upload or paste your bank statement CSV above first.');
        return;
      }
      await postGatedExport('/api/bank-csv-export', { bank_csv_text: bankCsv, bundle_name: 'bank_statement_qbo', api_key: CURRENT_API_KEY }, {
        docCount: 1,
        limitToast: 'Unlock the $49.99 One-Time Pro Pass for unlimited QuickBooks CSV exports.',
        failToast: 'Could not convert bank CSV. Include Date, Description, and Amount columns.',
        errPrefix: 'Bank CSV export failed: ',
        buildStatusHtml: (out, safeHref) =>
          'Your QuickBooks 3-column CSV <strong>' + escHtml(out.filename) + '</strong> (' + Number(out.row_count) + ' transactions) is ready: <a href="' + escHtml(safeHref) + '" style="color:var(--chart-3); text-decoration:underline;">Download again</a>',
        buildToast: (out) => 'Downloaded QuickBooks CSV (' + Number(out.row_count) + ' bank transactions).'
      });
    }

    async function exportBundle(fmt) {
      /* Uses /api/export (server-gated equivalent of MCP export_ledger_bundle) */
      if (!LAST_EXTRACTED) await runExtractMcp();
      if (!LAST_EXTRACTED) return;
      const catEl = document.getElementById('category-select');
      if (catEl) LAST_EXTRACTED.suggested_category = catEl.value;
      const docsToExport = BATCH_QUEUE.length > 0 ? BATCH_QUEUE : [LAST_EXTRACTED];
      const useCorrected = document.getElementById('mode-corrected') ? document.getElementById('mode-corrected').checked : false;
      const slug = String(LAST_EXTRACTED.invoice_number || 'checked_bills').toLowerCase();
      const payload = { documents: docsToExport, reconciliation: LAST_RECON, format: fmt, bundle_name: slug + "_ledger", use_corrected_amounts: useCorrected, api_key: CURRENT_API_KEY };
      await postGatedExport('/api/export', payload, {
        docCount: docsToExport.length,
        limitToast: 'Unlock the $49.99 One-Time Pro Pass for unlimited multi-bill Excel & QuickBooks exports.',
        failToast: 'Unable to generate spreadsheet export.',
        errPrefix: 'Export failed: ',
        buildStatusHtml: (out, safeHref) =>
          'Your spreadsheet <strong>' + escHtml(out.filename) + '</strong> (' + Number(out.size_bytes) + ' bytes, SHA-256 verified) is ready: <a href="' + escHtml(safeHref) + '" style="color:var(--chart-3); text-decoration:underline;">Download again</a>',
        buildToast: (out) => 'Spreadsheet ' + out.filename + ' generated and download started.'
      });
    }
"""
