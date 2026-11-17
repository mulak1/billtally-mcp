"""
DOM rendering & formatting functions for the BillTally Accounting Workbench (`GET /`).
Extracted from `studio_script.py` so every module stays well below the 500-line soft cap.
"""

STUDIO_RENDER_JS = """
    const SVG_CHECK = '<svg class="icon-inline" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.2 8.4L6.4 11.6L12.8 4.8"/></svg>';
    const SVG_ALERT = '<svg class="icon-inline" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.2L14.2 13.2H1.8L8 2.2Z"/><path d="M8 6.4V9.4"/><circle cx="8" cy="11.4" r="0.6" fill="currentColor"/></svg>';

    function escHtml(val) {
      return String(val ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function safeDownloadHref(rawUrl) {
      const s = String(rawUrl || '').trim();
      if (!s.startsWith('/downloads/')) return '#';
      return encodeURI(s);
    }

    function fmtMoney(n) {
      const val = Number(n || 0);
      const sign = val < 0 ? '-' : '';
      return sign + '$' + Math.abs(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function scrollBehaviorPref() {
      return (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) ? 'auto' : 'smooth';
    }

    function jumpToDisputedRow() {
      const el = document.getElementById('disputed-row');
      if (el) {
        el.scrollIntoView({ behavior: scrollBehaviorPref(), block: 'center' });
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
      if (doc.suggested_category && catSelect) catSelect.value = doc.suggested_category;

      const compCap = document.getElementById('compliance-caption');
      const badges = [];
      if (doc.requires_1099_review) badges.push('<span class="pill pill-warn">1099-NEC Trackable: Verify W-9</span>');
      if (doc.duplicate_line_items_warning) {
        badges.push('<span class="pill pill-err" title="' + escHtml(doc.duplicate_line_items_warning) + '">' + SVG_ALERT + ' Duplicate Line Item</span>');
      }
      if (doc.high_tax_rate_warning) {
        badges.push('<span class="pill pill-warn" title="' + escHtml(doc.high_tax_rate_warning) + '">' + SVG_ALERT + ' High Tax Rate (&gt;12%)</span>');
      }
      compCap.innerHTML = badges.length > 0 ? badges.join(' ') : 'Included in your Excel &amp; CSV exports';

      const banner = document.getElementById('audit-banner');
      const actionsBox = document.getElementById('discrepancy-actions');
      const deltaEl = document.getElementById('kpi-delta');
      const statusCap = document.getElementById('kpi-status-caption');
      const taxPct = Number(doc.effective_tax_rate_pct || 0).toFixed(2) + '%';

      if (doc.math_verified) {
        banner.className = 'banner banner-ok';
        banner.innerHTML =
          '<div>' + SVG_CHECK + ' <strong>Math Checks Out:</strong> Every line item (' + Number(doc.line_items.length) + ' rows) and tax line adds up to <strong>' + escHtml(fmtMoney(doc.total)) + '</strong>.</div>' +
          '<span class="pill pill-ok">Balanced to the penny</span>';
        deltaEl.textContent = '$0.00';
        deltaEl.style.color = 'var(--text)';
        statusCap.textContent = 'Balanced to the penny · Tax ' + taxPct;
        actionsBox.style.display = 'none';
      } else {
        const isOvercharge = Number(doc.discrepancy_delta) > 0;
        const absDiff = fmtMoney(Math.abs(doc.discrepancy_delta));
        const headLabel = isOvercharge ? 'Overcharge Caught:' : 'Under-Billing Caught:';
        const tailNote = isOvercharge ? ('You save <strong>' + escHtml(absDiff) + '</strong>') : ('Under-billed by <strong>' + escHtml(absDiff) + '</strong>');
        banner.className = 'banner banner-err';
        banner.innerHTML =
          '<div>' + SVG_ALERT + ' <strong>' + headLabel + '</strong> Supplier billed <strong>' + escHtml(fmtMoney(doc.total)) + '</strong>, but the true math is <strong>' + escHtml(fmtMoney(doc.computed_total)) + '</strong> (' + tailNote + ').</div>' +
          '<button type="button" class="btn btn-sm" id="jump-disputed-btn" style="background:#ffffff;">Jump to Disputed Line ↓</button>';
        const jumpBtn = document.getElementById('jump-disputed-btn');
        if (jumpBtn) jumpBtn.addEventListener('click', jumpToDisputedRow);

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

      let disputedAssigned = false;
      const rowsHtml = doc.line_items.map(li => {
        const rowId = (!li.line_math_valid && !disputedAssigned) ? (disputedAssigned = true, 'id="disputed-row"') : '';
        const billedCell = li.line_math_valid
          ? escHtml(fmtMoney(li.amount))
          : ('<del class="billed-strike">' + escHtml(fmtMoney(li.amount)) + '</del><span style="color:var(--negative);">' + escHtml(fmtMoney(li.expected_amount)) + '</span>');
        const diffLabel = Number(li.delta) >= 0 ? 'overcharge' : 'under-billed';
        const badgeText = li.line_math_valid
          ? 'Matches'
          : ((li.delta > 0 ? '+' : '') + fmtMoney(li.delta) + ' ' + diffLabel);
        return `
          <tr ${rowId} style="${li.line_math_valid ? '' : 'background:#fff5f5;'}">
            <td>${Number(li.line_number)}</td><td>${escHtml(li.description)}</td><td class="num">${escHtml(li.quantity)}</td>
            <td class="num">${escHtml(fmtMoney(li.unit_price))}</td><td class="money">${billedCell}</td>
            <td class="money">${escHtml(fmtMoney(li.expected_amount))}</td>
            <td class="num"><span class="pill ${li.line_math_valid ? 'pill-ok' : 'pill-err'}">${escHtml(badgeText)}</span></td>
          </tr>`;
      }).join('');

      const subMismatch = doc.subtotal !== doc.computed_subtotal;
      const totMismatch = !doc.math_verified;
      const totRowId = (totMismatch && !disputedAssigned) ? 'id="disputed-row"' : '';
      const totDiffWord = Number(doc.discrepancy_delta) >= 0 ? 'overcharge' : 'under-billed';
      const totBadge = doc.math_verified
        ? 'Balanced'
        : ((doc.discrepancy_delta > 0 ? '+' : '') + fmtMoney(doc.discrepancy_delta) + ' ' + totDiffWord);

      document.getElementById('table-container').innerHTML = `
        <table>
          <thead>
            <tr><th>#</th><th>Item description</th><th class="num">Qty</th><th class="num">Unit price</th><th class="num">Billed vs. True</th><th class="num">True math (Qty×Price)</th><th class="num">Check</th></tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
          <tfoot>
            <tr style="${subMismatch ? 'background:#fff5f5;' : ''}">
              <td colspan="4" style="color:var(--muted);">Line items subtotal</td>
              <td class="money">${subMismatch ? ('<del class="billed-strike">' + escHtml(fmtMoney(doc.subtotal)) + '</del><span style="color:var(--negative);">' + escHtml(fmtMoney(doc.computed_subtotal)) + '</span>') : escHtml(fmtMoney(doc.subtotal))}</td>
              <td class="money">${escHtml(fmtMoney(doc.computed_subtotal))}</td>
              <td class="num"><span class="pill ${subMismatch ? 'pill-err' : 'pill-ok'}">${subMismatch ? 'Subtotal off' : 'Subtotal OK'}</span></td>
            </tr>
            <tr>
              <td colspan="4" style="color:var(--muted);">Sales tax (${escHtml(taxPct)})</td>
              <td class="money">${escHtml(fmtMoney(doc.tax))}</td><td class="money">${escHtml(fmtMoney(doc.tax))}</td>
              <td class="num"><span class="pill pill-ok">Tax checked</span></td>
            </tr>
            <tr ${totRowId} style="${totMismatch ? 'background:#fff5f5;' : ''}">
              <td colspan="4" style="font-weight:500;">Total due</td>
              <td class="money">${totMismatch ? ('<del class="billed-strike">' + escHtml(fmtMoney(doc.total)) + '</del><span style="color:var(--negative);">' + escHtml(fmtMoney(doc.computed_total)) + '</span>') : escHtml(fmtMoney(doc.total))}</td>
              <td class="money">${escHtml(fmtMoney(doc.computed_total))}</td>
              <td class="num"><span class="pill ${doc.math_verified ? 'pill-ok' : 'pill-err'}">${escHtml(totBadge)}</span></td>
            </tr>
          </tfoot>
        </table>`;
    }
"""
