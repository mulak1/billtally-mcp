"""
Multi-Tab Excel (.xlsx) Workbook & Accounting CSV Exporter (`export_ledger_bundle`).
Generates downloadable files in ephemeral bounded memory with native Excel `=ROUND(...)` and `=SUM(...)` formulas,
plain-English bookkeeper action labels, DDE formula neutralization, and unguessable download tokens.
"""

from collections import OrderedDict
from decimal import Decimal
import base64
import csv
import hashlib
import io
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
from openpyxl.styles import Font, PatternFill

from app.extractor import _to_dec, _to_raw_dec
from app.models import ExportBundleRequest, ExportBundleResult

DEFAULT_EXPORT_DIR = Path(__file__).resolve().parent.parent / "exports"
MAX_EPHEMERAL_EXPORTS = 256
MAX_EPHEMERAL_EXPORT_BYTES = 32_000_000
MAX_EXPORT_LINE_ITEMS = 5000
MAX_EXPORT_RECON_ROWS = 5000
EPHEMERAL_EXPORT_TTL_SEC = 900
_EXPORT_LOCK = threading.Lock()
_EPHEMERAL_EXPORTS: "OrderedDict[str, Tuple[bytes, int]]" = OrderedDict()
_EPHEMERAL_EXPORT_BYTES = 0


def _prune_ephemeral_exports_locked() -> None:
    global _EPHEMERAL_EXPORT_BYTES
    now = int(time.time())
    expired = [k for k, (_, exp) in _EPHEMERAL_EXPORTS.items() if now > exp]
    for k in expired:
        removed = _EPHEMERAL_EXPORTS.pop(k, None)
        if removed:
            _EPHEMERAL_EXPORT_BYTES = max(0, _EPHEMERAL_EXPORT_BYTES - len(removed[0]))


def put_ephemeral_export(filename: str, payload: bytes) -> None:
    global _EPHEMERAL_EXPORT_BYTES
    with _EXPORT_LOCK:
        _prune_ephemeral_exports_locked()
        if filename in _EPHEMERAL_EXPORTS:
            old_bytes, _ = _EPHEMERAL_EXPORTS.pop(filename)
            _EPHEMERAL_EXPORT_BYTES = max(0, _EPHEMERAL_EXPORT_BYTES - len(old_bytes))
        _EPHEMERAL_EXPORTS[filename] = (payload, int(time.time()) + EPHEMERAL_EXPORT_TTL_SEC)
        _EPHEMERAL_EXPORT_BYTES += len(payload)
        while len(_EPHEMERAL_EXPORTS) > MAX_EPHEMERAL_EXPORTS or _EPHEMERAL_EXPORT_BYTES > MAX_EPHEMERAL_EXPORT_BYTES:
            _, (ev_bytes, _) = _EPHEMERAL_EXPORTS.popitem(last=False)
            _EPHEMERAL_EXPORT_BYTES = max(0, _EPHEMERAL_EXPORT_BYTES - len(ev_bytes))


def get_ephemeral_export(filename: str) -> Optional[bytes]:
    global _EPHEMERAL_EXPORT_BYTES
    with _EXPORT_LOCK:
        _prune_ephemeral_exports_locked()
        rec = _EPHEMERAL_EXPORTS.get(filename)
        if not rec:
            return None
        payload, exp = rec
        if int(time.time()) > exp:
            _EPHEMERAL_EXPORTS.pop(filename, None)
            _EPHEMERAL_EXPORT_BYTES = max(0, _EPHEMERAL_EXPORT_BYTES - len(payload))
            return None
        return payload


def sanitize_export_filename(raw_name: str) -> str:
    """Sanitize user-supplied bundle_name to prevent path traversal or shell characters."""
    stripped = str(raw_name or "").replace("../", "").replace("..\\", "").replace("..", "_")
    cleaned = re.sub(r"[^A-Za-z0-9_\-]+", "_", stripped).strip("_")
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned[:80] if cleaned else "schemaextract_ledger"


def _safe_cell_text(val: Any) -> str:
    """Neutralize CSV/Excel formula injection (DDE) by prefixing leading formula characters on user strings."""
    s = str(val if val is not None else "")
    return f"'{s}" if s.lstrip(" ").startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else s


def _safe_int(val: Any, default: int = 1) -> int:
    try:
        return int(_to_raw_dec(val))
    except Exception:
        return default


def _build_audit_memo(doc: Dict[str, Any], use_corrected_amounts: bool) -> str:
    """Return a deterministic audit trail memo distinguishing overcharges vs under-billed bills."""
    if doc.get("math_verified", True):
        return "Verified: Line items and tax match billed total"
    billed = _to_dec(doc.get("total", 0))
    computed = _to_dec(doc.get("computed_total", billed))
    diff = abs(billed - computed)
    if billed >= computed:
        prefix = "Short-Pay Adjusted" if use_corrected_amounts else "Discrepancy Flagged"
        return f"{prefix}: Billed ${billed:.2f} vs True Math ${computed:.2f} (Saved ${diff:.2f} on disputed line items)"
    prefix = "True-Math Adjusted" if use_corrected_amounts else "Under-Billing Flagged"
    return f"{prefix}: Billed ${billed:.2f} vs True Math ${computed:.2f} (Under-billed by ${diff:.2f} vs line items)"


def _doc_status_label(doc: Dict[str, Any]) -> str:
    if doc.get("math_verified", False):
        return "Balanced"
    billed = _to_dec(doc.get("total", 0))
    computed = _to_dec(doc.get("computed_total", billed))
    return "Overcharge Flagged" if billed >= computed else "Under-Billed Flagged"


def _build_xlsx_bytes(
    documents: List[Dict[str, Any]],
    reconciliation: Optional[Dict[str, Any]],
    use_corrected_amounts: bool = False,
    audit_url: str = "",
    audit_sha256: str = "",
) -> Tuple[bytes, List[str], int]:
    """Create a styled multi-tab Excel workbook with native Excel `=SUM()` and `=ROUND()` formulas."""
    wb = openpyxl.Workbook()
    header_fill = PatternFill(start_color="141414", end_color="141414", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    total_font = Font(name="Calibri", size=11, bold=True, color="04250E")

    ws_summary = wb.active
    ws_summary.title = "Executive_Summary"
    summary_headers = [
        "Document ID", "Supplier / Payee", "Bill / Invoice #", "Bill Date", "Due Date",
        "Expense Category", "Subtotal", "Tax", "Billed Total", "Checked Math Total",
        "Math Difference", "Math Check Status", "Audit_Memo",
    ]
    ws_summary.append(summary_headers)
    for col_idx in range(1, len(summary_headers) + 1):
        cell = ws_summary.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font

    doc_rows = 0
    for idx, doc in enumerate(documents, start=2):
        doc_rows += 1
        sub_val = float(_to_dec(doc.get("computed_subtotal" if use_corrected_amounts else "subtotal", 0)))
        tot_val = float(_to_dec(doc.get("computed_total" if use_corrected_amounts else "total", 0)))
        ws_summary.append(
            [
                _safe_cell_text(doc.get("document_id", f"doc_{idx}")),
                _safe_cell_text(doc.get("vendor", "Unknown Supplier")),
                _safe_cell_text(doc.get("invoice_number", "INV-UNKNOWN")),
                _safe_cell_text(doc.get("issue_date", "2026-10-01")),
                _safe_cell_text(doc.get("due_date") or "Due on Receipt"),
                _safe_cell_text(doc.get("suggested_category", "General Operating Expense")),
                sub_val,
                float(_to_dec(doc.get("tax", 0))),
                tot_val,
                f"=ROUND(G{idx}+H{idx},2)",
                f"=ROUND(I{idx}-J{idx},2)",
                _doc_status_label(doc),
                _build_audit_memo(doc, use_corrected_amounts),
            ]
        )

    if doc_rows > 0:
        sum_row = doc_rows + 2
        ws_summary.cell(row=sum_row, column=6, value="TOTAL ALL BILLS").font = total_font
        for col_idx, col_let in ((7, "G"), (8, "H"), (9, "I"), (10, "J"), (11, "K")):
            ws_summary.cell(row=sum_row, column=col_idx, value=f"=SUM({col_let}2:{col_let}{doc_rows+1})").font = total_font

        # Big-4 style Audit Verification Seal block (placed below TOTAL ALL BILLS to preserve row 2..N+2 formula indices)
        seal_row = sum_row + 2
        seal_fill = PatternFill(start_color="F3F3F3", end_color="F3F3F3", fill_type="solid")
        seal_title_font = Font(name="Calibri", size=10, bold=True, color="141414")
        seal_meta_font = Font(name="Calibri", size=10, color="595959")
        all_balanced = all(bool(d.get("math_verified", False)) for d in documents)
        seal_rows = [
            ("VERIFIED BY BILLTALLY", "Fixed-Decimal Arithmetic Audit Cover Sheet"),
            ("Audit Verdict", "Balanced to the penny" if all_balanced else "Discrepancy flagged — review Audit_Memo"),
            ("Verification URL", _safe_cell_text(audit_url or "https://billtally.app")),
            ("Audit SHA-256", _safe_cell_text(audit_sha256 or "Computed on export")),
        ]
        for offset, (k_lbl, v_lbl) in enumerate(seal_rows):
            r_idx = seal_row + offset
            c1 = ws_summary.cell(row=r_idx, column=1, value=k_lbl)
            c2 = ws_summary.cell(row=r_idx, column=2, value=v_lbl)
            c1.font = seal_title_font
            c2.font = seal_title_font if offset == 0 else seal_meta_font
            if offset == 0:
                c1.fill = seal_fill
                c2.fill = seal_fill

    ws_items = wb.create_sheet(title="Normalized_Line_Items")
    item_headers = [
        "Bill / Invoice #", "Supplier", "Bill Date", "Expense Category", "Line #",
        "Item Description", "Quantity", "Unit Price", "Billed Line Amount",
        "Checked Math (Qty * Price)", "Difference", "Line Status",
    ]
    ws_items.append(item_headers)
    for col_idx in range(1, len(item_headers) + 1):
        cell = ws_items.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font

    line_row_idx = 2
    for doc in documents:
        inv_no = _safe_cell_text(doc.get("invoice_number", "INV-UNKNOWN"))
        vendor = _safe_cell_text(doc.get("vendor", "Unknown Supplier"))
        dt = _safe_cell_text(doc.get("issue_date", "2026-10-01"))
        cat = _safe_cell_text(doc.get("suggested_category", "General Operating Expense"))
        for item in (doc.get("line_items") or []):
            amt_raw = item.get("expected_amount", item.get("amount", 0)) if use_corrected_amounts else item.get("amount", 0)
            ws_items.append(
                [
                    inv_no,
                    vendor,
                    dt,
                    cat,
                    _safe_int(item.get("line_number", line_row_idx - 1), line_row_idx - 1),
                    _safe_cell_text(item.get("description", "")),
                    float(_to_raw_dec(item.get("quantity", 1))),
                    float(_to_raw_dec(item.get("unit_price", 0))),
                    float(_to_dec(amt_raw)),
                    f"=ROUND(G{line_row_idx}*H{line_row_idx},2)",
                    f"=ROUND(I{line_row_idx}-J{line_row_idx},2)",
                    "Matches" if item.get("line_math_valid", True) else "Check Line Math",
                ]
            )
            line_row_idx += 1

    if line_row_idx > 2:
        last_item_row = line_row_idx - 1
        ws_items.cell(row=line_row_idx, column=6, value="LINE ITEMS TOTAL").font = total_font
        ws_items.cell(row=line_row_idx, column=9, value=f"=SUM(I2:I{last_item_row})").font = total_font
        ws_items.cell(row=line_row_idx, column=10, value=f"=SUM(J2:J{last_item_row})").font = total_font
        ws_items.cell(row=line_row_idx, column=11, value=f"=SUM(K2:K{last_item_row})").font = total_font

    ws_recon = wb.create_sheet(title="Bank_Reconciliation")
    recon_headers = [
        "Match Status", "Bill / Reference #", "Supplier / Bank Description", "Date",
        "Bill Amount", "Bank Withdrawal", "Difference", "Bookkeeper Action Needed",
    ]
    ws_recon.append(recon_headers)
    for col_idx in range(1, len(recon_headers) + 1):
        cell = ws_recon.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font

    r_idx = 2
    if reconciliation:
        for m in (reconciliation.get("matched") or []):
            ws_recon.append(
                [
                    "Matched",
                    _safe_cell_text(m.get("invoice_number", "")),
                    _safe_cell_text(m.get("vendor", "")),
                    _safe_cell_text(m.get("bank_date", "")),
                    float(_to_dec(m.get("invoice_amount", 0))),
                    float(_to_dec(m.get("bank_amount", 0))),
                    f"=ROUND(E{r_idx}-F{r_idx},2)",
                    "Cleared (No Action Needed)",
                ]
            )
            r_idx += 1
        for u_inv in (reconciliation.get("unmatched_invoices") or []):
            ws_recon.append(
                [
                    "Unpaid Bill",
                    _safe_cell_text(u_inv.get("invoice_number", "")),
                    _safe_cell_text(u_inv.get("vendor", "")),
                    _safe_cell_text(u_inv.get("date", "")),
                    float(_to_dec(u_inv.get("total", 0))),
                    0.0,
                    f"=ROUND(E{r_idx}-F{r_idx},2)",
                    "Schedule Payment or Accrue at Month-End",
                ]
            )
            r_idx += 1
        for u_bnk in (reconciliation.get("unmatched_bank_txns") or []):
            raw_status = str(u_bnk.get("status", ""))
            action_text = "Duplicate Withdrawal: Request Refund" if "DUPLICATE" in raw_status else "Missing Receipt: Attach Supplier Bill"
            ws_recon.append(
                [
                    "Duplicate Charge" if "DUPLICATE" in raw_status else "Missing Receipt",
                    _safe_cell_text(u_bnk.get("txn_id", "")),
                    _safe_cell_text(u_bnk.get("description", "")),
                    _safe_cell_text(u_bnk.get("date", "")),
                    0.0,
                    float(_to_dec(u_bnk.get("amount", 0))),
                    f"=ROUND(E{r_idx}-F{r_idx},2)",
                    action_text,
                ]
            )
            r_idx += 1

    if r_idx > 2:
        last_r = r_idx - 1
        ws_recon.cell(row=r_idx, column=3, value="RECONCILIATION TOTALS").font = total_font
        ws_recon.cell(row=r_idx, column=5, value=f"=SUM(E2:E{last_r})").font = total_font
        ws_recon.cell(row=r_idx, column=6, value=f"=SUM(F2:F{last_r})").font = total_font
        ws_recon.cell(row=r_idx, column=7, value=f"=SUM(G2:G{last_r})").font = total_font

    buf = io.BytesIO()
    wb.save(buf)
    raw_bytes = buf.getvalue()
    total_rows = doc_rows + max(0, line_row_idx - 2) + max(0, r_idx - 2)
    return raw_bytes, wb.sheetnames, total_rows


def _build_csv_bytes(
    documents: List[Dict[str, Any]],
    quickbooks_mode: bool,
    use_corrected_amounts: bool = False,
) -> Tuple[bytes, int]:
    """Generate either standard normalized CSV or accounting-software import CSV with strict DDE protection."""
    s_buf = io.StringIO()
    writer = csv.writer(s_buf)
    row_count = 0

    if quickbooks_mode:
        writer.writerow(["Date", "Description", "Amount", "Account", "Vendor", "RefNumber", "Memo", "MathVerified", "Audit_Memo"])
        for doc in documents:
            vendor = _safe_cell_text(doc.get("vendor", "Unknown Supplier"))
            inv_no = _safe_cell_text(doc.get("invoice_number", "INV-UNKNOWN"))
            dt = _safe_cell_text(doc.get("issue_date", "2026-10-01"))
            category = _safe_cell_text(doc.get("suggested_category", "General Operating Expense"))
            verified = "TRUE" if doc.get("math_verified", False) else "FALSE"
            audit_memo = _safe_cell_text(_build_audit_memo(doc, use_corrected_amounts))
            for item in (doc.get("line_items") or []):
                amt = _to_dec(item.get("expected_amount", item.get("amount", 0)) if use_corrected_amounts else item.get("amount", 0))
                qty_dec = _to_raw_dec(item.get("quantity", 1))
                unit_dec = _to_dec(item.get("unit_price", 0))
                writer.writerow(
                    [
                        dt,
                        _safe_cell_text(item.get("description", "Line Item")),
                        f"{amt:.2f}",
                        category,
                        vendor,
                        inv_no,
                        _safe_cell_text(f"Qty {qty_dec} @ ${unit_dec:.2f}"),
                        verified,
                        audit_memo,
                    ]
                )
                row_count += 1
            tax_amt = _to_dec(doc.get("tax", 0))
            if abs(tax_amt) >= Decimal("0.01"):
                writer.writerow(
                    [dt, "Sales Tax", f"{tax_amt:.2f}", category, vendor, inv_no, "Bill Sales Tax", verified, audit_memo]
                )
                row_count += 1
    else:
        writer.writerow(
            [
                "InvoiceNumber", "Vendor", "IssueDate", "DueDate", "Currency", "Category",
                "LineNumber", "Description", "Quantity", "UnitPrice", "ReportedAmount",
                "ExpectedAmount", "MathVerified", "Audit_Memo",
            ]
        )
        for doc in documents:
            audit_memo = _safe_cell_text(_build_audit_memo(doc, use_corrected_amounts))
            for item in (doc.get("line_items") or []):
                qty_dec = _to_raw_dec(item.get("quantity", 1))
                unit_dec = _to_dec(item.get("unit_price", 0))
                rep_dec = _to_dec(item.get("amount", 0))
                exp_dec = _to_dec(item.get("expected_amount", rep_dec))
                writer.writerow(
                    [
                        _safe_cell_text(doc.get("invoice_number", "INV-UNKNOWN")),
                        _safe_cell_text(doc.get("vendor", "Unknown Supplier")),
                        _safe_cell_text(doc.get("issue_date", "2026-10-01")),
                        _safe_cell_text(doc.get("due_date") or ""),
                        _safe_cell_text(doc.get("currency", "USD")),
                        _safe_cell_text(doc.get("suggested_category", "General Operating Expense")),
                        _safe_int(item.get("line_number", 1), 1),
                        _safe_cell_text(item.get("description", "")),
                        f"{qty_dec}",
                        f"{unit_dec:.2f}",
                        f"{rep_dec:.2f}",
                        f"{exp_dec:.2f}",
                        bool(doc.get("math_verified", False)),
                        audit_memo,
                    ]
                )
                row_count += 1

    return s_buf.getvalue().encode("utf-8"), row_count


def export_ledger_bundle(
    req: ExportBundleRequest,
    export_dir: Optional[Path] = None,
    *,
    audit_url: str = "",
    audit_sha256: str = "",
) -> ExportBundleResult:
    """Generate a downloadable .xlsx or .csv ledger bundle held in short-TTL ephemeral memory."""
    total_items = sum(
        len(d["line_items"]) for d in req.documents if isinstance(d, dict) and isinstance(d.get("line_items"), list)
    )
    if total_items > MAX_EXPORT_LINE_ITEMS:
        raise ValueError(f"Export exceeds maximum {MAX_EXPORT_LINE_ITEMS} total line items.")
    if isinstance(req.reconciliation, dict):
        recon_rows = sum(
            len(req.reconciliation[k])
            for k in ("matched", "unmatched_invoices", "unmatched_bank_txns")
            if isinstance(req.reconciliation.get(k), list)
        )
        if recon_rows > MAX_EXPORT_RECON_ROWS:
            raise ValueError(f"Export exceeds maximum {MAX_EXPORT_RECON_ROWS} reconciliation rows.")
    safe_base = sanitize_export_filename(req.bundle_name)
    if req.format == "xlsx":
        raw_bytes, sheets, row_count = _build_xlsx_bytes(
            req.documents,
            req.reconciliation,
            use_corrected_amounts=req.use_corrected_amounts,
            audit_url=audit_url,
            audit_sha256=audit_sha256,
        )
        ext = "xlsx"
        formulas = True
    else:
        raw_bytes, row_count = _build_csv_bytes(
            req.documents,
            quickbooks_mode=(req.format == "quickbooks_csv"),
            use_corrected_amounts=req.use_corrected_amounts,
        )
        sheets = ["Accounting_Import_CSV" if req.format == "quickbooks_csv" else "Normalized_CSV"]
        ext = "csv"
        formulas = False

    digest = hashlib.sha256(raw_bytes).hexdigest()
    token = secrets.token_hex(12)
    filename = f"{safe_base}_{token}.{ext}"

    # Always store in bounded ephemeral RAM; only write to disk when an explicit test export_dir is passed.
    put_ephemeral_export(filename, raw_bytes)
    if export_dir is not None:
        export_dir.mkdir(parents=True, exist_ok=True)
        file_path = (export_dir / filename).resolve()
        if not file_path.is_relative_to(export_dir.resolve()):
            raise ValueError("Resolved export path escapes allowed export directory.")
        file_path.write_bytes(raw_bytes)

    b64_payload = base64.b64encode(raw_bytes).decode("ascii")
    return ExportBundleResult(
        filename=filename,
        format=req.format,
        download_url=f"/downloads/{filename}",
        size_bytes=len(raw_bytes),
        sha256_checksum=digest,
        base64_content=b64_payload,
        sheets_included=sheets,
        row_count=row_count,
        formulas_embedded=formulas,
    )
