"""
MCP Prompt/Resource Handlers (`prompts/get`, `resources/read`), Raw Bank CSV Parser,
and 1-Call Compound Orchestrator (`audit_and_export_pack`) for BillTally.
"""

import csv
from decimal import Decimal
import io
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from app.audit_links import create_audit_link
from app.exporter import export_ledger_bundle
from app.extractor import _to_dec, extract_financial_document
from app.models import ExportBundleRequest, ExtractDocumentRequest, ReconcileLedgerRequest
from app.oauth_quota import QuotaManager
from app.presets import get_all_presets, get_preset_by_id
from app.reconciler import reconcile_invoices_with_bank_ledger

MAX_BANK_CSV_CHARS = 250_000
MAX_BANK_CSV_ROWS = 5000
_AMOUNT_RE = re.compile(r"\(?[-+]?\$?\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})\)?-?|\(?[-+]?\$?\s*\d+(?:\.\d{2})\)?-?")
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b")


def _parse_abs_dec_amount(raw: str) -> Decimal:
    s = str(raw or "").strip()
    if not s:
        return Decimal("0.00")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    if s.endswith("-"):
        s = "-" + s[:-1]
    s = re.sub(r"[^0-9.\-]", "", s)
    if not s or s.count(".") > 1 or s.count("-") > 1:
        return Decimal("0.00")
    return abs(_to_dec(s))


def parse_raw_bank_csv_text(raw_text: str) -> List[Dict[str, Any]]:
    """Deterministically parse pasted bank CSV or line-delimited statement text into bank_transactions."""
    text = str(raw_text or "").strip()[:MAX_BANK_CSV_CHARS]
    if not text:
        return []

    rows_out: List[Dict[str, Any]] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    first_no_thousands = re.sub(r"(?<=\d),(?=\d{3}\b)", "", lines[0]) if lines else ""
    if lines and ("," in first_no_thousands or "\t" in first_no_thousands):
        delim = "\t" if ("\t" in first_no_thousands and "," not in first_no_thousands) else ","
        reader = csv.reader(io.StringIO(text), delimiter=delim)
        parsed_rows = [r for r in reader if any(c.strip() for c in r)]
        if parsed_rows:
            first_lower = [c.strip().lower() for c in parsed_rows[0]]
            has_header = any(
                k in col
                for col in first_lower
                for k in ("date", "desc", "merchant", "vendor", "amount", "debit", "withdrawal", "payee")
            )
            data_rows = parsed_rows[1:] if has_header else parsed_rows
            date_idx = next((i for i, c in enumerate(first_lower) if "date" in c), 0) if has_header else 0
            desc_idx = (
                next((i for i, c in enumerate(first_lower) if any(k in c for k in ("desc", "payee", "merchant", "vendor", "memo"))), 1)
                if has_header
                else 1
            )
            amt_idx = (
                next((i for i, c in enumerate(first_lower) if any(k in c for k in ("amount", "debit", "withdrawal", "total"))), -1)
                if has_header
                else -1
            )
            for idx, r in enumerate(data_rows, start=1):
                if len(rows_out) >= MAX_BANK_CSV_ROWS:
                    break
                if len(r) < 2:
                    continue
                raw_date = r[date_idx].strip() if date_idx < len(r) else "2026-10-01"
                raw_desc = r[desc_idx].strip() if desc_idx < len(r) else f"Bank Withdrawal {idx}"
                raw_amt_cell = r[amt_idx].strip() if (amt_idx >= 0 and amt_idx < len(r)) else r[-1].strip()
                amt_val = _parse_abs_dec_amount(raw_amt_cell)
                if amt_val <= Decimal("0.00"):
                    continue
                rows_out.append(
                    {
                        "txn_id": f"CSV-{idx:03d}",
                        "date": raw_date or "2026-10-01",
                        "description": raw_desc or f"Bank Withdrawal {idx}",
                        "amount": float(amt_val),
                        "currency": "USD",
                    }
                )
            if rows_out:
                return rows_out

    for idx, line in enumerate(lines, start=1):
        if len(rows_out) >= MAX_BANK_CSV_ROWS:
            break
        amt_matches = _AMOUNT_RE.findall(line)
        if not amt_matches:
            continue
        amt_val = _parse_abs_dec_amount(amt_matches[-1])
        if amt_val <= Decimal("0.00"):
            continue
        dt_match = _DATE_RE.search(line)
        dt_val = dt_match.group(1) if dt_match else "2026-10-01"
        desc = _AMOUNT_RE.sub("", line)
        if dt_match:
            desc = desc.replace(dt_match.group(0), "")
        desc = re.sub(r"[|\t]+", " ", desc).strip(" -,:;")
        rows_out.append(
            {
                "txn_id": f"TXN-{idx:03d}",
                "date": dt_val,
                "description": desc or f"Bank Withdrawal {idx}",
                "amount": float(amt_val),
                "currency": "USD",
            }
        )
    return rows_out


def get_mcp_prompt_response(name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Resolve MCP `prompts/get` requests into ready-to-run user prompt messages."""
    args = arguments if isinstance(arguments, dict) else {}
    if name == "run_demo_overcharge_audit":
        demo = get_preset_by_id("discrepant_contractor_invoice")
        return {
            "description": "Instant 0-input demo showing BillTally catch a +$200.00 plumbing overcharge and generate a Verified Dispute Link + Excel pack.",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            "Run `audit_and_export_pack` on this sample plumbing repair bill, catch any line-item "
                            "math overcharge, generate a Verified Dispute Link, and export a 3-tab Excel workbook:\n\n"
                            f"{demo['raw_text']}"
                        ),
                    },
                }
            ],
        }
    if name == "check_supplier_bill":
        bill_text = str(args.get("bill_text") or "").strip()
        if not bill_text:
            bill_text = get_preset_by_id("messy_saas_invoice")["raw_text"]
        return {
            "description": "Check every line item (Qty x Unit Price) and sales tax on a supplier bill.",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": f"Check this supplier bill to the penny using `extract_financial_documents`:\n\n{bill_text}",
                    },
                }
            ],
        }
    if name == "match_monthly_bank_statement":
        batch = get_preset_by_id("bank_reconciliation_batch")
        return {
            "description": "Match supplier bills against monthly checking withdrawals to spot duplicates and missing receipts.",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            "Reconcile these supplier bills against our bank withdrawals using "
                            "`reconcile_invoices_with_bank_ledger`:\n"
                            f"Invoices: {batch['invoices']}\n"
                            f"Bank Transactions: {batch['bank_transactions']}"
                        ),
                    },
                }
            ],
        }
    if name == "export_clean_spreadsheet":
        demo = get_preset_by_id("discrepant_contractor_invoice")
        return {
            "description": "Check a bill and export a 3-tab Excel (.xlsx) workbook with live =SUM() formulas.",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            "Run `audit_and_export_pack` with format='xlsx' and use_corrected_amounts=true on this bill:\n\n"
                            f"{demo['raw_text']}"
                        ),
                    },
                }
            ],
        }
    raise KeyError(f"Unknown MCP prompt: {name}")


def read_mcp_resource_response(uri: str) -> Dict[str, Any]:
    """Resolve MCP `resources/read` requests for `schemaextract://presets/<id>` or `billtally://presets/<id>`."""
    u = str(uri or "").strip()
    prefix_match = re.match(r"^(?:schemaextract|billtally)://presets/([A-Za-z0-9_\-]+)$", u)
    if not prefix_match:
        raise KeyError(f"Unknown MCP resource URI: {u}")
    preset_id = prefix_match.group(1)
    preset = get_preset_by_id(preset_id)
    return {
        "contents": [
            {
                "uri": u,
                "mimeType": "text/plain",
                "text": str(preset.get("raw_text", "")),
            }
        ]
    }


def list_mcp_resources() -> List[Dict[str, Any]]:
    return [
        {
            "uri": f"schemaextract://presets/{p['id']}",
            "name": p["title"],
            "description": p["description"],
            "mimeType": "text/plain",
        }
        for p in get_all_presets()
    ]


def run_audit_and_export_pack(
    arguments: Dict[str, Any],
    quota_manager: QuotaManager,
    export_dir: Optional[Path] = None,
    *,
    is_prod: bool = False,
    caller_ip: str = "",
    public_base_url: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """
    1-call compound MCP orchestrator:
    1. Extracts and penny-verifies the bill (`raw_text`).
    2. Optionally reconciles against `bank_transactions` or `bank_csv_text`.
    3. Mints a 14-day read-only Verified Audit / Dispute Link (`/v/{audit_id}`) and appends it to the dispute note.
    4. Generates the 3-tab `.xlsx` (with Audit Cover Seal) or `quickbooks_csv` download link + Web Desk handoff link.
    """
    raw_text = str(arguments.get("raw_text") or "").strip()
    if not raw_text:
        raise ValueError("raw_text is required for audit_and_export_pack.")

    ws_id = str(arguments.get("workspace_id") or "default-workspace")
    api_key = arguments.get("api_key") or None
    doc_type = arguments.get("document_type") or "auto"
    strict_val = True if arguments.get("strict_reconciliation") is None else bool(arguments.get("strict_reconciliation"))
    doc_req = ExtractDocumentRequest(
        raw_text=raw_text,
        document_type=doc_type,
        currency_hint=arguments.get("currency_hint") or None,
        strict_reconciliation=strict_val,
        workspace_id=ws_id,
        api_key=api_key,
    )
    quota_manager.check_available(doc_req.workspace_id, api_key=api_key, is_prod=is_prod, caller_ip=caller_ip)
    quota_manager.check_export_available(doc_req.workspace_id, api_key=api_key, doc_count=1, is_prod=is_prod, caller_ip=caller_ip)
    parsed_obj = extract_financial_document(doc_req)
    quota_state = quota_manager.consume_document(
        doc_req.workspace_id, api_key=api_key, is_prod=is_prod, caller_ip=caller_ip
    )
    doc_dict = parsed_obj.model_copy(update={"quota_state": quota_state}).model_dump()

    raw_use_corr = arguments.get("use_corrected_amounts")
    use_corr = (not bool(doc_dict.get("math_verified", True))) if raw_use_corr is None else bool(raw_use_corr)

    recon_dict: Optional[Dict[str, Any]] = None
    bank_txns = arguments.get("bank_transactions")
    if (not bank_txns) and arguments.get("bank_csv_text"):
        bank_txns = parse_raw_bank_csv_text(str(arguments["bank_csv_text"]))
    if isinstance(bank_txns, list) and len(bank_txns) > 0:
        inv_list = arguments.get("invoices") or [
            {
                "invoice_number": doc_dict.get("invoice_number", "INV-UNKNOWN"),
                "vendor": doc_dict.get("vendor", "Unknown Supplier"),
                "date": doc_dict.get("issue_date", "2026-10-01"),
                "total": float(_to_dec(doc_dict.get("computed_total" if use_corr else "total", 0))),
                "currency": doc_dict.get("currency", "USD"),
            }
        ]
        dt_tol = 7 if arguments.get("date_tolerance_days") is None else int(arguments["date_tolerance_days"])
        amt_tol = Decimal("0.05") if arguments.get("amount_tolerance") is None else _to_dec(arguments["amount_tolerance"])
        recon_req = ReconcileLedgerRequest(
            invoices=inv_list,
            bank_transactions=bank_txns,
            date_tolerance_days=dt_tol,
            amount_tolerance=float(amt_tol),
        )
        recon_dict = reconcile_invoices_with_bank_ledger(recon_req).model_dump()

    base_pub = (public_base_url or os.environ.get("PUBLIC_BASE_URL", "")).rstrip("/")
    audit_meta = create_audit_link(doc_dict, reconciliation=recon_dict, public_base_url=base_pub)
    if doc_dict.get("vendor_dispute_note") and not doc_dict.get("math_verified", True):
        doc_dict["vendor_dispute_note"] = (
            f"{doc_dict['vendor_dispute_note']}\n\n"
            f"Independent line-by-line math breakdown: {audit_meta['audit_url']}"
        )

    fmt = str(arguments.get("format") or "xlsx")
    if fmt not in ("xlsx", "csv", "quickbooks_csv"):
        fmt = "xlsx"
    slug = str(doc_dict.get("invoice_number") or "billtally_audit").lower()[:80]
    raw_bundle_name = str(arguments.get("bundle_name") or f"{slug}_audit_pack")[:120]
    exp_req = ExportBundleRequest(
        documents=[doc_dict],
        reconciliation=recon_dict,
        format=fmt,
        bundle_name=raw_bundle_name,
        use_corrected_amounts=use_corr,
        api_key=api_key,
    )
    exp_obj = export_ledger_bundle(
        exp_req,
        export_dir=export_dir,
        audit_url=audit_meta["audit_url"],
        audit_sha256=audit_meta["sha256"],
    )
    quota_manager.consume_export(doc_req.workspace_id, api_key=api_key, doc_count=1, is_prod=is_prod, caller_ip=caller_ip)
    dl_link = f"{base_pub}{exp_obj.download_url}" if base_pub else exp_obj.download_url
    web_desk_url = f"{base_pub}/" if base_pub else "/"

    structured = {
        "document": doc_dict,
        "reconciliation": recon_dict,
        "verified_audit_link": audit_meta,
        "export": {
            "filename": exp_obj.filename,
            "format": exp_obj.format,
            "download_url": dl_link,
            "size_bytes": exp_obj.size_bytes,
            "sha256_checksum": exp_obj.sha256_checksum,
            "sheets_included": exp_obj.sheets_included,
            "formulas_embedded": exp_obj.formulas_embedded,
        },
        "web_desk_url": web_desk_url,
    }
    summary_line = (
        f"BillTally Audit Pack Ready for {doc_dict.get('vendor')} (Invoice #{doc_dict.get('invoice_number')}): "
        f"{doc_dict.get('plain_english_summary')} "
        f"Verified Audit Link: {audit_meta['audit_url']} | "
        f"Download {exp_obj.format.upper()}: {dl_link} | "
        f"Full interactive desk: {web_desk_url}"
    )
    return summary_line, structured
