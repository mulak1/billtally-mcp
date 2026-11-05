"""
Multi-Tab Excel (.xlsx) Workbook & Accounting CSV Exporter (`export_ledger_bundle`).
Generates real downloadable files with native Excel `=ROUND(...)` and `=SUM(...)` formulas,
plain-English bookkeeper action labels, and strict path-traversal sanitization.
"""

import base64
import csv
import hashlib
import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
from openpyxl.styles import Font, PatternFill

from app.models import ExportBundleRequest, ExportBundleResult

DEFAULT_EXPORT_DIR = Path(__file__).resolve().parent.parent / "exports"


def sanitize_export_filename(raw_name: str) -> str:
    """Sanitize user-supplied bundle_name to prevent path traversal or shell characters."""
    stripped = raw_name.replace("../", "").replace("..\\", "").replace("..", "_")
    cleaned = re.sub(r"[^A-Za-z0-9_\-]+", "_", stripped).strip("_")
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned[:80] if cleaned else "schemaextract_ledger"


def _safe_cell_text(val: Any) -> str:
    """Neutralize CSV/Excel formula injection (DDE) by prefixing leading formula characters on user strings."""
    s = str(val if val is not None else "")
    return f"'{s}" if s.startswith(("=", "+", "-", "@", "\t", "\r")) else s


def _build_audit_memo(doc: Dict[str, Any], use_corrected_amounts: bool) -> str:
    """Return a deterministic audit trail memo for QuickBooks CSV and Excel exports."""
    if doc.get("math_verified", True):
        return "Verified: Line items and tax match billed total"
    billed = float(doc.get("total", 0.0))
    computed = float(doc.get("computed_total", billed))
    saved = abs(billed - computed)
    prefix = "Short-Pay Adjusted" if use_corrected_amounts else "Discrepancy Flagged"
    return f"{prefix}: Billed ${billed:.2f} vs True Math ${computed:.2f} (Saved ${saved:.2f} on disputed line items)"


def _build_xlsx_bytes(
    documents: List[Dict[str, Any]],
    reconciliation: Optional[Dict[str, Any]],
    use_corrected_amounts: bool = False,
) -> Tuple[bytes, List[str], int]:
    """Create a styled multi-tab Excel workbook with native Excel `=SUM()` and `=ROUND()` formulas."""
    wb = openpyxl.Workbook()
    header_fill = PatternFill(start_color="141414", end_color="141414", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    total_font = Font(name="Calibri", size=11, bold=True, color="04250E")

    # Tab 1: Executive_Summary
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
        sub_val = float(doc.get("computed_subtotal" if use_corrected_amounts else "subtotal", 0.0))
        tot_val = float(doc.get("computed_total" if use_corrected_amounts else "total", 0.0))
        ws_summary.append(
            [
                _safe_cell_text(doc.get("document_id", f"doc_{idx}")),
                _safe_cell_text(doc.get("vendor", "Unknown Supplier")),
                _safe_cell_text(doc.get("invoice_number", "INV-UNKNOWN")),
                _safe_cell_text(doc.get("issue_date", "2026-10-01")),
                _safe_cell_text(doc.get("due_date") or "Due on Receipt"),
                _safe_cell_text(doc.get("suggested_category", "General Operating Expense")),
                sub_val,
                float(doc.get("tax", 0.0)),
                tot_val,
                f"=ROUND(G{idx}+H{idx},2)",
                f"=ROUND(I{idx}-J{idx},2)",
                "Balanced" if doc.get("math_verified", False) else "Overcharge Flagged",
                _build_audit_memo(doc, use_corrected_amounts),
            ]
        )

    if doc_rows > 0:
        sum_row = doc_rows + 2
        ws_summary.cell(row=sum_row, column=6, value="TOTAL ALL BILLS").font = total_font
        ws_summary.cell(row=sum_row, column=7, value=f"=SUM(G2:G{doc_rows+1})").font = total_font
        ws_summary.cell(row=sum_row, column=8, value=f"=SUM(H2:H{doc_rows+1})").font = total_font
        ws_summary.cell(row=sum_row, column=9, value=f"=SUM(I2:I{doc_rows+1})").font = total_font
        ws_summary.cell(row=sum_row, column=10, value=f"=SUM(J2:J{doc_rows+1})").font = total_font
        ws_summary.cell(row=sum_row, column=11, value=f"=SUM(K2:K{doc_rows+1})").font = total_font

    # Tab 2: Normalized_Line_Items
    ws_items = wb.create_sheet(title="Normalized_Line_Items")
    item_headers = [
        "Bill / Invoice #",
        "Supplier",
        "Bill Date",
        "Expense Category",
        "Line #",
        "Item Description",
        "Quantity",
        "Unit Price",
        "Billed Line Amount",
        "Checked Math (Qty * Price)",
        "Difference",
        "Line Status",
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
        for item in doc.get("line_items", []):
            amt_col = float(
                item.get("expected_amount", item.get("amount", 0.0))
                if use_corrected_amounts
                else item.get("amount", 0.0)
            )
            ws_items.append(
                [
                    inv_no,
                    vendor,
                    dt,
                    cat,
                    int(item.get("line_number", line_row_idx - 1)),
                    _safe_cell_text(item.get("description", "")),
                    float(item.get("quantity", 1.0)),
                    float(item.get("unit_price", 0.0)),
                    amt_col,
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

    # Tab 3: Bank_Reconciliation
    ws_recon = wb.create_sheet(title="Bank_Reconciliation")
    recon_headers = [
        "Match Status",
        "Bill / Reference #",
        "Supplier / Bank Description",
        "Date",
        "Bill Amount",
        "Bank Withdrawal",
        "Difference",
        "Bookkeeper Action Needed",
    ]
    ws_recon.append(recon_headers)
    for col_idx in range(1, len(recon_headers) + 1):
        cell = ws_recon.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font

    r_idx = 2
    if reconciliation:
        for m in reconciliation.get("matched", []):
            ws_recon.append(
                [
                    "Matched",
                    _safe_cell_text(m.get("invoice_number", "")),
                    _safe_cell_text(m.get("vendor", "")),
                    _safe_cell_text(m.get("bank_date", "")),
                    float(m.get("invoice_amount", 0.0)),
                    float(m.get("bank_amount", 0.0)),
                    f"=ROUND(E{r_idx}-F{r_idx},2)",
                    "Cleared (No Action Needed)",
                ]
            )
            r_idx += 1
        for u_inv in reconciliation.get("unmatched_invoices", []):
            ws_recon.append(
                [
                    "Unpaid Bill",
                    _safe_cell_text(u_inv.get("invoice_number", "")),
                    _safe_cell_text(u_inv.get("vendor", "")),
                    _safe_cell_text(u_inv.get("date", "")),
                    float(u_inv.get("total", 0.0)),
                    0.0,
                    f"=ROUND(E{r_idx}-F{r_idx},2)",
                    "Schedule Payment or Accrue at Month-End",
                ]
            )
            r_idx += 1
        for u_bnk in reconciliation.get("unmatched_bank_txns", []):
            raw_status = str(u_bnk.get("status", ""))
            action_text = (
                "Duplicate Withdrawal: Request Refund"
                if "DUPLICATE" in raw_status
                else "Missing Receipt: Attach Supplier Bill"
            )
            ws_recon.append(
                [
                    "Duplicate Charge" if "DUPLICATE" in raw_status else "Missing Receipt",
                    _safe_cell_text(u_bnk.get("txn_id", "")),
                    _safe_cell_text(u_bnk.get("description", "")),
                    _safe_cell_text(u_bnk.get("date", "")),
                    0.0,
                    float(u_bnk.get("amount", 0.0)),
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
    """Generate either standard normalized CSV or accounting-software import CSV (including Sales Tax rows)."""
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
            audit_memo = _build_audit_memo(doc, use_corrected_amounts)
            for item in doc.get("line_items", []):
                amt = item.get("expected_amount", item.get("amount", 0.0)) if use_corrected_amounts else item.get("amount", 0.0)
                writer.writerow(
                    [
                        dt,
                        _safe_cell_text(item.get("description", "Line Item")),
                        f"{float(amt):.2f}",
                        category,
                        vendor,
                        inv_no,
                        f"Qty {item.get('quantity', 1)} @ ${float(item.get('unit_price', 0.0)):.2f}",
                        verified,
                        audit_memo,
                    ]
                )
                row_count += 1
            tax_amt = float(doc.get("tax", 0.0))
            if abs(tax_amt) > 0.001:
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
            audit_memo = _build_audit_memo(doc, use_corrected_amounts)
            for item in doc.get("line_items", []):
                writer.writerow(
                    [
                        _safe_cell_text(doc.get("invoice_number", "INV-UNKNOWN")),
                        _safe_cell_text(doc.get("vendor", "Unknown Supplier")),
                        _safe_cell_text(doc.get("issue_date", "2026-10-01")),
                        _safe_cell_text(doc.get("due_date") or ""),
                        _safe_cell_text(doc.get("currency", "USD")),
                        _safe_cell_text(doc.get("suggested_category", "General Operating Expense")),
                        item.get("line_number", 1),
                        _safe_cell_text(item.get("description", "")),
                        item.get("quantity", 1),
                        item.get("unit_price", 0.0),
                        item.get("amount", 0.0),
                        item.get("expected_amount", item.get("amount", 0.0)),
                        doc.get("math_verified", False),
                        audit_memo,
                    ]
                )
                row_count += 1

    return s_buf.getvalue().encode("utf-8"), row_count


def export_ledger_bundle(
    req: ExportBundleRequest,
    export_dir: Optional[Path] = None,
) -> ExportBundleResult:
    """Generate a downloadable .xlsx or .csv ledger bundle and persist it securely."""
    target_dir = export_dir or DEFAULT_EXPORT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_base = sanitize_export_filename(req.bundle_name)
    if req.format == "xlsx":
        raw_bytes, sheets, row_count = _build_xlsx_bytes(
            req.documents, req.reconciliation, use_corrected_amounts=req.use_corrected_amounts
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
    filename = f"{safe_base}.{ext}"
    file_path = (target_dir / filename).resolve()
    if not str(file_path).startswith(str(target_dir.resolve())):
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
