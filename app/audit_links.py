"""
Shareable 14-Day Verified Audit & Dispute Link Store + HTML Renderer (`GET /v/{audit_id}`).
Mints tamper-evident, read-only, print-ready proof pages with SHA-256 checksums so buyers can
attach an objective line-item tie-out to vendor dispute emails and CPA workpapers.
"""

from collections import OrderedDict
import copy
import datetime
from decimal import Decimal
import hashlib
import html
import json
import re
import secrets
import threading
import time
from typing import Any, Dict, List, Optional

from app.extractor import _to_dec, _to_raw_dec

MAX_AUDIT_LINKS = 512
MAX_AUDIT_RECORD_BYTES = 65_536
MAX_AUDIT_STORE_BYTES = 16_000_000
MAX_AUDIT_LINE_ITEMS = 200
MAX_AUDIT_LINKS_PER_IP_HOURLY = 30
AUDIT_LINK_TTL_SEC = 14 * 24 * 3600  # 14 days
_AUDIT_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_LOCAL_IPS = ("", "local", "testclient", "127.0.0.1", "localhost", "::1")

_AUDIT_LOCK = threading.Lock()
_AUDIT_STORE: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_AUDIT_STORE_BYTES = 0
_AUDIT_IP_WINDOWS: "OrderedDict[str, List[int]]" = OrderedDict()


def check_audit_link_rate_limit(caller_ip: str = "") -> None:
    """Enforce a per-IP sliding 1-hour window on non-loopback callers to prevent eviction/OOM abuse."""
    ip = (caller_ip or "").strip()
    if ip in _LOCAL_IPS:
        return
    now = int(time.time())
    cutoff = now - 3600
    with _AUDIT_LOCK:
        hits = [t for t in _AUDIT_IP_WINDOWS.get(ip, []) if t > cutoff]
        if len(hits) >= MAX_AUDIT_LINKS_PER_IP_HOURLY:
            _AUDIT_IP_WINDOWS[ip] = hits
            raise PermissionError("Rate limit exceeded for Verified Audit Links. Please try again later.")
        hits.append(now)
        _AUDIT_IP_WINDOWS[ip] = hits
        _AUDIT_IP_WINDOWS.move_to_end(ip)
        while len(_AUDIT_IP_WINDOWS) > 2048:
            _AUDIT_IP_WINDOWS.popitem(last=False)


def _prune_expired_locked() -> None:
    global _AUDIT_STORE_BYTES
    now = int(time.time())
    expired = [k for k, rec in _AUDIT_STORE.items() if now > int(rec.get("expires_at", 0))]
    for k in expired:
        removed = _AUDIT_STORE.pop(k, None)
        if removed:
            _AUDIT_STORE_BYTES = max(0, _AUDIT_STORE_BYTES - int(removed.get("_size_bytes", 0)))


def _sanitize_and_verify_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Strip unknown bloat and deterministically recompute math verification server-side so callers cannot spoof verdicts."""
    raw_items = doc.get("line_items")
    clean_items: List[Dict[str, Any]] = []
    if isinstance(raw_items, list):
        if len(raw_items) > MAX_AUDIT_LINE_ITEMS:
            raise ValueError(f"Audit link supports at most {MAX_AUDIT_LINE_ITEMS} line items.")
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            qty = _to_raw_dec(item.get("quantity", 1))
            unit_p = _to_raw_dec(item.get("unit_price", 0))
            amt = _to_dec(item.get("amount"))
            clean_items.append(
                {
                    "description": str(item.get("description") or "")[:300],
                    "quantity": float(qty),
                    "unit_price": float(unit_p),
                    "amount": float(amt),
                }
            )

    tax = _to_dec(doc.get("tax"))
    billed_total = _to_dec(doc.get("total"))
    if clean_items:
        computed_sub = sum((_to_dec(_to_raw_dec(it["quantity"]) * _to_raw_dec(it["unit_price"])) for it in clean_items), Decimal("0.00"))
        computed_total = _to_dec(computed_sub + tax)
        delta = _to_dec(billed_total - computed_total)
        subtotal = _to_dec(doc.get("subtotal")) if doc.get("subtotal") is not None else computed_sub
        lines_ok = all(
            abs(_to_dec(it["amount"]) - _to_dec(_to_raw_dec(it["quantity"]) * _to_raw_dec(it["unit_price"]))) < Decimal("0.01")
            for it in clean_items
        )
        sub_ok = abs(subtotal - computed_sub) < Decimal("0.01")
        math_ok = lines_ok and sub_ok and abs(delta) < Decimal("0.01")
    else:
        subtotal = _to_dec(doc.get("subtotal"))
        computed_total = _to_dec(subtotal + tax)
        delta = _to_dec(billed_total - computed_total)
        math_ok = abs(delta) < Decimal("0.01")

    return {
        "vendor": str(doc.get("vendor") or "Unknown Supplier")[:200],
        "invoice_number": str(doc.get("invoice_number") or "N/A")[:120],
        "issue_date": str(doc.get("issue_date") or "Not stated")[:40],
        "due_date": str(doc.get("due_date") or "Due on Receipt")[:40],
        "currency": str(doc.get("currency") or "USD")[:10],
        "subtotal": float(subtotal),
        "tax": float(tax),
        "total": float(billed_total),
        "computed_total": float(computed_total),
        "discrepancy_delta": float(delta),
        "math_verified": bool(math_ok),
        "line_items": clean_items,
        "vendor_dispute_note": str(doc.get("vendor_dispute_note") or "")[:3000],
    }


def _safe_nonneg_int(val: Any) -> int:
    if isinstance(val, bool):
        return 0
    try:
        return max(0, int(val))
    except (TypeError, ValueError):
        return 0


def _sanitize_recon(reconciliation: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(reconciliation, dict) or not isinstance(reconciliation.get("summary_metrics"), dict):
        return None
    m = reconciliation["summary_metrics"]
    return {
        "summary_metrics": {
            "matched_count": _safe_nonneg_int(m.get("matched_count", 0)),
            "unmatched_invoice_count": _safe_nonneg_int(m.get("unmatched_invoice_count", 0)),
            "unmatched_bank_txn_count": _safe_nonneg_int(m.get("unmatched_bank_txn_count", 0)),
            "duplicate_count": _safe_nonneg_int(m.get("duplicate_count", 0)),
        }
    }


def _compute_audit_sha256(doc: Dict[str, Any], reconciliation: Optional[Dict[str, Any]]) -> str:
    canonical = json.dumps(
        {
            "vendor": doc.get("vendor", ""),
            "invoice_number": doc.get("invoice_number", ""),
            "issue_date": doc.get("issue_date", ""),
            "currency": doc.get("currency", "USD"),
            "subtotal": doc.get("subtotal", 0),
            "tax": doc.get("tax", 0),
            "total": doc.get("total", 0),
            "computed_total": doc.get("computed_total", 0),
            "discrepancy_delta": doc.get("discrepancy_delta", 0),
            "math_verified": bool(doc.get("math_verified", False)),
            "line_items": doc.get("line_items") or [],
            "reconciliation_summary": (reconciliation or {}).get("summary_metrics"),
        },
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def create_audit_link(
    doc: Dict[str, Any],
    reconciliation: Optional[Dict[str, Any]] = None,
    public_base_url: str = "",
) -> Dict[str, Any]:
    """Store a bounded 14-day read-only audit snapshot and return its public verification URL."""
    global _AUDIT_STORE_BYTES
    safe_doc = _sanitize_and_verify_doc(doc)
    safe_recon = _sanitize_recon(reconciliation)
    est_bytes = len(json.dumps({"document": safe_doc, "reconciliation": safe_recon}, default=str).encode("utf-8"))
    if est_bytes > MAX_AUDIT_RECORD_BYTES:
        raise ValueError("Audit record exceeds maximum allowed size.")

    now = int(time.time())
    expires_at = now + AUDIT_LINK_TTL_SEC
    sha256 = _compute_audit_sha256(safe_doc, safe_recon)

    with _AUDIT_LOCK:
        _prune_expired_locked()
        audit_id = secrets.token_hex(16)
        while audit_id in _AUDIT_STORE:
            audit_id = secrets.token_hex(16)
        record = {
            "audit_id": audit_id,
            "sha256": sha256,
            "created_at": now,
            "expires_at": expires_at,
            "document": safe_doc,
            "reconciliation": safe_recon,
            "_size_bytes": est_bytes,
        }
        _AUDIT_STORE[audit_id] = record
        _AUDIT_STORE_BYTES += est_bytes
        while len(_AUDIT_STORE) > MAX_AUDIT_LINKS or _AUDIT_STORE_BYTES > MAX_AUDIT_STORE_BYTES:
            _, evicted = _AUDIT_STORE.popitem(last=False)
            _AUDIT_STORE_BYTES = max(0, _AUDIT_STORE_BYTES - int(evicted.get("_size_bytes", 0)))

    base = (public_base_url or "").rstrip("/")
    path = f"/v/{audit_id}"
    return {
        "audit_id": audit_id,
        "audit_path": path,
        "audit_url": f"{base}{path}" if base else path,
        "sha256": sha256,
        "expires_at": expires_at,
    }


def get_audit_record(audit_id: str) -> Optional[Dict[str, Any]]:
    """Return a deep copy of an unexpired audit record, or None if invalid/missing/expired."""
    global _AUDIT_STORE_BYTES
    aid = str(audit_id or "").strip().lower()
    if not _AUDIT_ID_RE.match(aid):
        return None
    with _AUDIT_LOCK:
        _prune_expired_locked()
        rec = _AUDIT_STORE.get(aid)
        if not rec:
            return None
        if int(time.time()) > int(rec.get("expires_at", 0)):
            removed = _AUDIT_STORE.pop(aid, None)
            if removed:
                _AUDIT_STORE_BYTES = max(0, _AUDIT_STORE_BYTES - int(removed.get("_size_bytes", 0)))
            return None
        return copy.deepcopy(rec)


def _fmt_money(val: Any, currency: str = "USD") -> str:
    num = _to_dec(val)
    sym = "$" if str(currency or "USD").upper() == "USD" else f"{str(currency).upper()} "
    sign = "-" if num < Decimal("0") else ""
    return f"{sign}{sym}{abs(num):,.2f}"


def _esc(val: Any) -> str:
    return html.escape(str(val if val is not None else ""), quote=True)


def render_verified_audit_html(record: Dict[str, Any], public_base_url: str = "") -> str:
    """Render a clean, print-ready, accessible read-only BillTally Verified Audit & Dispute page."""
    doc = record.get("document") if isinstance(record.get("document"), dict) else {}
    recon = record.get("reconciliation") if isinstance(record.get("reconciliation"), dict) else None
    audit_id = str(record.get("audit_id", ""))
    sha256 = str(record.get("sha256", ""))
    currency = str(doc.get("currency") or "USD")
    vendor = str(doc.get("vendor") or "Unknown Supplier")
    inv_no = str(doc.get("invoice_number") or "N/A")
    issue_date = str(doc.get("issue_date") or "Not stated")
    due_date = str(doc.get("due_date") or "Due on Receipt")
    math_ok = bool(doc.get("math_verified", False))
    billed_total = _to_dec(doc.get("total"))
    computed_total = _to_dec(doc.get("computed_total")) if doc.get("computed_total") is not None else billed_total
    delta = (
        _to_dec(doc.get("discrepancy_delta"))
        if doc.get("discrepancy_delta") is not None
        else (billed_total - computed_total)
    )
    dispute_note = str(doc.get("vendor_dispute_note") or "").strip()

    created_dt = datetime.datetime.fromtimestamp(
        int(record.get("created_at", time.time())), tz=datetime.timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")
    expires_dt = datetime.datetime.fromtimestamp(
        int(record.get("expires_at", time.time())), tz=datetime.timezone.utc
    ).strftime("%Y-%m-%d")

    if math_ok:
        status_cls = "banner-ok"
        pill_cls = "pill-ok"
        status_label = "Balanced to the penny"
        verdict_headline = f"Verified: All line items and sales tax match the billed total ({_fmt_money(billed_total, currency)})."
    elif delta > Decimal("0"):
        status_cls = "banner-err"
        pill_cls = "pill-err"
        status_label = f"Overcharge flagged (+{_fmt_money(delta, currency)})"
        verdict_headline = (
            f"Math discrepancy caught: Billed {_fmt_money(billed_total, currency)} vs. "
            f"verified true math {_fmt_money(computed_total, currency)} (+{_fmt_money(delta, currency)} overcharge)."
        )
    elif delta == Decimal("0"):
        status_cls = "banner-warn"
        pill_cls = "pill-warn"
        status_label = "Line-item discrepancy ($0.00 net)"
        verdict_headline = (
            f"Line-item discrepancy flagged: Individual row math does not tie out even though the net total is {_fmt_money(billed_total, currency)}."
        )
    else:
        status_cls = "banner-warn"
        pill_cls = "pill-warn"
        status_label = f"Under-billed ({_fmt_money(abs(delta), currency)})"
        verdict_headline = (
            f"Under-billing flagged: Billed {_fmt_money(billed_total, currency)} vs. "
            f"verified true math {_fmt_money(computed_total, currency)}."
        )

    raw_items = doc.get("line_items")
    line_items: List[Dict[str, Any]] = [x for x in raw_items if isinstance(x, dict)] if isinstance(raw_items, list) else []
    rows_html_parts: List[str] = []
    for idx, item in enumerate(line_items, start=1):
        desc = _esc(item.get("description") or f"Line {idx}")
        qty = _to_raw_dec(item.get("quantity", 1))
        unit_p = _to_raw_dec(item.get("unit_price", 0))
        billed_amt = _to_dec(item.get("amount"))
        calc_amt = _to_dec(qty * unit_p)
        line_diff = billed_amt - calc_amt
        row_cls = ' class="row-err"' if abs(line_diff) >= Decimal("0.01") else ""
        diff_badge = (
            f'<span class="pill pill-err">{_esc(_fmt_money(line_diff, currency))}</span>'
            if abs(line_diff) >= Decimal("0.01")
            else '<span class="pill pill-ok">OK</span>'
        )
        rows_html_parts.append(
            f"<tr{row_cls}>"
            f"<th scope=\"row\">{idx}. {desc}</th>"
            f"<td class=\"num\">{_esc(qty)}</td>"
            f"<td class=\"num\">{_esc(_fmt_money(unit_p, currency))}</td>"
            f"<td class=\"num\">{_esc(_fmt_money(billed_amt, currency))}</td>"
            f"<td class=\"num\">{_esc(_fmt_money(calc_amt, currency))}</td>"
            f"<td class=\"num\">{diff_badge}</td>"
            f"</tr>"
        )
    if not rows_html_parts:
        rows_html_parts.append(
            '<tr><td colspan="6" style="color:var(--muted);">Summary-only bill check (no individual line items provided).</td></tr>'
        )

    dispute_section = ""
    if dispute_note and not math_ok:
        dispute_section = f"""
        <section class="card" aria-labelledby="dispute-heading">
          <h2 id="dispute-heading">Supplier Correction Note</h2>
          <pre class="note-box">{_esc(dispute_note)}</pre>
        </section>"""

    recon_section = ""
    if isinstance(recon, dict) and isinstance(recon.get("summary_metrics"), dict):
        m = recon["summary_metrics"]
        recon_section = f"""
        <section class="card" aria-labelledby="recon-heading">
          <h2 id="recon-heading">Bank Statement Match Summary</h2>
          <div class="meta-grid">
            <div><span class="lbl">Matched Payments</span><strong>{_esc(m.get('matched_count', 0))}</strong></div>
            <div><span class="lbl">Unpaid Bills</span><strong>{_esc(m.get('unmatched_invoice_count', 0))}</strong></div>
            <div><span class="lbl">Missing Receipts</span><strong>{_esc(m.get('unmatched_bank_txn_count', 0))}</strong></div>
            <div><span class="lbl">Duplicate Charges</span><strong>{_esc(m.get('duplicate_count', 0))}</strong></div>
          </div>
        </section>"""

    base_href = _esc((public_base_url or "").rstrip("/") or "/")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="robots" content="noindex, nofollow" />
  <title>Verified Bill Math Audit · {_esc(vendor)} ({_esc(inv_no)}) — BillTally</title>
  <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
  <style>
    :root {{
      --ground:#f8f8f8; --surface:#ffffff; --border:#e6e6e6; --text:#0a0a0a; --muted:#595959; --accent:#141414;
      --pill-ok-bg:#dcfae5; --pill-ok-ink:#04250e; --pill-err-bg:#ffedea; --pill-err-ink:#831c1e;
      --pill-warn-bg:#fffbeb; --pill-warn-ink:#92400e;
      --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      --mono:ui-monospace,SFMono-Regular,Menlo,monospace;
    }}
    * {{ box-sizing:border-box; margin:0; padding:0; }}
    body {{ background:var(--ground); color:var(--text); font-family:var(--sans); font-size:14px; line-height:1.55; padding:28px 16px 56px; font-variant-numeric:tabular-nums; }}
    .wrap {{ max-width:920px; margin:0 auto; }}
    .top {{ display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:12px; margin-bottom:18px; }}
    .brand {{ font-weight:600; font-size:15px; color:var(--text); text-decoration:none; }}
    .btn {{ display:inline-flex; align-items:center; gap:6px; min-height:36px; padding:6px 14px; border-radius:6px; border:1px solid #949494; background:#eeeeee; color:var(--text); font-size:13px; font-weight:500; text-decoration:none; cursor:pointer; }}
    .btn-primary {{ background:var(--accent); color:#ffffff; border-color:var(--accent); }}
    .banner {{ padding:14px 16px; border-radius:8px; margin-bottom:16px; display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:10px; }}
    .banner-ok {{ background:var(--pill-ok-bg); color:var(--pill-ok-ink); border:1px solid #b7ebc6; }}
    .banner-err {{ background:var(--pill-err-bg); color:var(--pill-err-ink); border:1px solid #f5c2c7; }}
    .banner-warn {{ background:var(--pill-warn-bg); color:var(--pill-warn-ink); border:1px solid #fde68a; }}
    .pill {{ display:inline-flex; align-items:center; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:600; white-space:nowrap; }}
    .pill-ok {{ background:var(--pill-ok-bg); color:var(--pill-ok-ink); }}
    .pill-err {{ background:var(--pill-err-bg); color:var(--pill-err-ink); }}
    .pill-warn {{ background:var(--pill-warn-bg); color:var(--pill-warn-ink); }}
    .card {{ background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:20px; margin-bottom:16px; }}
    h1 {{ font-size:21px; font-weight:600; letter-spacing:-0.015em; margin-bottom:4px; }}
    h2 {{ font-size:15px; font-weight:600; margin-bottom:10px; }}
    .meta-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(170px, 1fr)); gap:12px; margin-top:12px; }}
    .lbl {{ display:block; font-size:11.5px; color:var(--muted); margin-bottom:2px; }}
    .table-wrapper {{ overflow-x:auto; max-inline-size:100%; border:1px solid var(--border); border-radius:6px; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th, td {{ padding:9px 10px; border-bottom:1px solid var(--border); text-align:left; vertical-align:top; }}
    thead th {{ background:#f3f3f3; font-size:12px; color:var(--muted); font-weight:600; }}
    tbody th {{ font-weight:500; }}
    .num {{ text-align:right; font-family:var(--mono); white-space:nowrap; }}
    .row-err {{ background:#fff7f6; }}
    .totals {{ display:flex; flex-wrap:wrap; gap:18px; justify-content:flex-end; margin-top:12px; font-family:var(--mono); font-size:13px; }}
    .note-box {{ background:#fcfcfc; border:1px solid var(--border); border-radius:6px; padding:12px; white-space:pre-wrap; font-family:var(--sans); font-size:13px; line-height:1.55; }}
    .seal {{ font-family:var(--mono); font-size:11.5px; color:var(--muted); word-break:break-all; }}
    .cta-foot {{ display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:12px; padding-top:14px; border-top:1px solid var(--border); margin-top:14px; font-size:13px; color:var(--muted); }}
    a:focus-visible, button:focus-visible, .table-wrapper:focus-visible {{ outline:2px solid #0b57d0; outline-offset:2px; }}
    @media (max-width: 768px), (pointer: coarse) {{
      .btn, .brand, .cta-foot a {{ min-height:44px; display:inline-flex; align-items:center; padding:8px 12px; }}
    }}
    @media print {{
      body {{ background:#ffffff; padding:0; }}
      .no-print {{ display:none !important; }}
      .card {{ border:1px solid #cccccc; break-inside:avoid; }}
      .table-wrapper {{ overflow:visible; }}
      .banner, .pill {{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <div class="top">
      <a class="brand" href="{base_href}">BillTally · Independent Bill Math Verification</a>
      <div class="no-print" style="display:flex; gap:8px; flex-wrap:wrap;">
        <a class="btn btn-primary" href="{base_href}">Check another bill free →</a>
      </div>
    </div>

    <div class="banner {status_cls}" role="status">
      <div><strong>{_esc(verdict_headline)}</strong></div>
      <span class="pill {pill_cls}">{_esc(status_label)}</span>
    </div>

    <section class="card" aria-labelledby="doc-heading">
      <h1 id="doc-heading">{_esc(vendor)}</h1>
      <div style="color:var(--muted); font-size:13px;">Bill / Invoice #{_esc(inv_no)} · Audited {_esc(created_dt)} (Expires {_esc(expires_dt)})</div>
      <div class="meta-grid">
        <div><span class="lbl">Issue Date</span><strong>{_esc(issue_date)}</strong></div>
        <div><span class="lbl">Due Date</span><strong>{_esc(due_date)}</strong></div>
        <div><span class="lbl">Billed Total</span><strong>{_esc(_fmt_money(billed_total, currency))}</strong></div>
        <div><span class="lbl">Verified Math Total</span><strong>{_esc(_fmt_money(computed_total, currency))}</strong></div>
      </div>
    </section>

    <section class="card" aria-labelledby="lines-heading">
      <h2 id="lines-heading">Line-Item Arithmetic Tie-Out (Quantity × Unit Price)</h2>
      <div tabindex="0" role="region" aria-labelledby="lines-heading" class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th scope="col">Line Item</th>
              <th scope="col" class="num">Qty</th>
              <th scope="col" class="num">Unit Price</th>
              <th scope="col" class="num">Billed</th>
              <th scope="col" class="num">Verified</th>
              <th scope="col" class="num">Status</th>
            </tr>
          </thead>
          <tbody>
            {"".join(rows_html_parts)}
          </tbody>
        </table>
      </div>
      <div class="totals">
        <span>Subtotal: <strong>{_esc(_fmt_money(doc.get('subtotal', 0), currency))}</strong></span>
        <span>Sales Tax: <strong>{_esc(_fmt_money(doc.get('tax', 0), currency))}</strong></span>
        <span>Billed Total: <strong>{_esc(_fmt_money(billed_total, currency))}</strong></span>
        <span>Verified Total: <strong>{_esc(_fmt_money(computed_total, currency))}</strong></span>
      </div>
    </section>

    {dispute_section}
    {recon_section}

    <section class="card">
      <div class="seal">
        <strong>Audit ID:</strong> {_esc(audit_id)} &nbsp;·&nbsp; <strong>SHA-256:</strong> {_esc(sha256)}
      </div>
      <div class="cta-foot">
        <span>Audited with fixed-decimal arithmetic by BillTally. Read-only verification snapshot.</span>
        <a class="no-print" href="{base_href}" style="color:var(--text); font-weight:600; text-decoration:underline;">Check any supplier bill or bank statement free →</a>
      </div>
    </section>
  </main>
</body>
</html>"""
