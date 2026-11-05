"""
Streamable HTTP MCP Protocol Handler (`POST /mcp` and `GET /mcp`).
Implements JSON-RPC 2.0 (`initialize`, `notifications/initialized`, `ping`,
`tools/list`, `tools/call`, `resources/list`, `prompts/list`) with full
Claude Connectors Directory and ChatGPT MCP Store tool annotations.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.exporter import export_ledger_bundle
from app.extractor import extract_financial_document
from app.models import (
    ExportBundleRequest,
    ExtractDocumentRequest,
    ReconcileLedgerRequest,
)
from app.oauth_quota import QuotaManager
from app.presets import get_all_presets
from app.reconciler import reconcile_invoices_with_bank_ledger

MCP_PROTOCOL_VERSION = "2025-03-26"

MCP_TOOLS_CATALOG: List[Dict[str, Any]] = [
    {
        "name": "extract_financial_documents",
        "title": "Check Supplier Bill or Receipt Math",
        "description": (
            "Extracts supplier name, bill number, dates, payment terms, currency, line items, "
            "subtotal, sales tax, and total from supplier bills, bank statements, receipts, and agreements. "
            "Performs cent-level fixed-decimal math checking (verifying that the sum of line items plus tax "
            "equals the billed total) and returns exact differences, a plain-English summary, a 1099-NEC "
            "review flag, and a polite supplier correction note when an overcharge is found."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "raw_text": {
                    "type": "string",
                    "description": "Raw supplier bill, receipt, or statement text, table, or structured document content to verify.",
                },
                "document_type": {
                    "type": "string",
                    "enum": ["invoice", "bank_statement", "receipt", "contract", "auto"],
                    "default": "auto",
                    "description": "Type of financial document being checked (invoice, bank_statement, receipt, contract, or auto).",
                },
                "currency_hint": {
                    "type": "string",
                    "description": "Optional 3-letter ISO currency code hint such as USD, EUR, or GBP.",
                },
                "strict_reconciliation": {
                    "type": "boolean",
                    "default": True,
                    "description": "When true, enforces cent-exact verification across every line item (Quantity multiplied by Unit Price) and sales tax total.",
                },
            },
            "required": ["raw_text"],
        },
        "annotations": {
            "title": "Check Supplier Bill & Line-Item Math",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "reconcile_invoices_with_bank_ledger",
        "title": "Match Supplier Bills Against Bank Statement",
        "description": (
            "Cross-matches extracted supplier bills or receipts against bank statement withdrawals "
            "using amount tolerance, settlement date window, and supplier name matching. "
            "Flags matched payments, unpaid bills, missing-receipt bank debits, and duplicate charges."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "invoices": {
                    "type": "array",
                    "description": "List of extracted bills or receipts containing invoice_number, vendor, date, and total.",
                    "items": {
                        "type": "object",
                        "description": "Individual supplier bill or receipt record with invoice_number, vendor, date, and total amount.",
                    },
                },
                "bank_transactions": {
                    "type": "array",
                    "description": "List of bank statement withdrawal rows containing txn_id, date, description, and amount.",
                    "items": {
                        "type": "object",
                        "description": "Individual bank statement withdrawal entry with txn_id, date, description, and withdrawal amount.",
                    },
                },
                "date_tolerance_days": {
                    "type": "integer",
                    "default": 7,
                    "minimum": 0,
                    "maximum": 90,
                    "description": "Maximum number of calendar days allowed between the bill date and bank clearing date when matching.",
                },
                "amount_tolerance": {
                    "type": "number",
                    "default": 0.05,
                    "minimum": 0.0,
                    "maximum": 100.0,
                    "description": "Maximum dollar rounding difference allowed when matching a bill total to a bank withdrawal.",
                },
            },
            "required": ["invoices", "bank_transactions"],
        },
        "annotations": {
            "title": "Match Bills to Bank Statement",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "export_ledger_bundle",
        "title": "Format Multi-Tab Excel or Accounting CSV Spreadsheet",
        "description": (
            "Statelessly formats checked supplier bills in memory into a multi-tab Microsoft Excel (.xlsx) "
            "workbook with SUM and ROUND accounting formulas, or a clean CSV spreadsheet preview."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "documents": {
                    "type": "array",
                    "description": "List of checked supplier bill objects returned by extract_financial_documents.",
                    "items": {
                        "type": "object",
                        "description": "Checked financial document object including vendor, invoice_number, line_items, subtotal, tax, and total.",
                    },
                },
                "reconciliation": {
                    "type": "object",
                    "description": "Optional bank statement matching report returned by reconcile_invoices_with_bank_ledger.",
                },
                "format": {
                    "type": "string",
                    "enum": ["xlsx", "csv", "quickbooks_csv"],
                    "default": "xlsx",
                    "description": "Spreadsheet output format: xlsx (3-tab Excel workbook with live formulas), csv, or quickbooks_csv.",
                },
                "bundle_name": {
                    "type": "string",
                    "default": "billtally_ledger",
                    "description": "Label for the formatted Excel or CSV spreadsheet output.",
                },
                "use_corrected_amounts": {
                    "type": "boolean",
                    "default": False,
                    "description": "When true, formats the spreadsheet using verified true math totals instead of overcharged billed figures.",
                },
            },
            "required": ["documents"],
        },
        "annotations": {
            "title": "Format Excel or Accounting CSV Spreadsheet",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
]

MCP_PROMPTS_CATALOG: List[Dict[str, Any]] = [
    {
        "name": "check_supplier_bill",
        "title": "Check a supplier bill for math errors",
        "description": "Checks every line item (Quantity x Unit Price) and sales tax on a supplier bill before payment.",
    },
    {
        "name": "match_monthly_bank_statement",
        "title": "Match monthly bills against a bank statement",
        "description": "Finds matched payments, unpaid bills, missing receipts, and duplicate bank withdrawals.",
    },
    {
        "name": "export_clean_spreadsheet",
        "title": "Export checked bills to Excel (.xlsx) with =SUM() formulas",
        "description": "Generates a 3-tab Excel workbook or accounting CSV from checked bills.",
    },
]


def handle_mcp_jsonrpc(
    payload: Dict[str, Any],
    quota_manager: QuotaManager,
    export_dir: Optional[Path] = None,
) -> Tuple[Optional[Dict[str, Any]], int]:
    """Process a single JSON-RPC 2.0 message and return `(response_dict, http_status)`."""
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        return (
            {
                "jsonrpc": "2.0",
                "id": payload.get("id") if isinstance(payload, dict) else None,
                "error": {"code": -32600, "message": "Invalid Request: expected JSON-RPC 2.0 envelope."},
            },
            400,
        )

    method = payload.get("method", "")
    req_id = payload.get("id")
    params = payload.get("params") or {}

    if method.startswith("notifications/") or req_id is None:
        return (None, 202)

    if method == "initialize":
        return (
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                        "prompts": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": "billtally-mcp",
                        "title": "BillTally: Bill Math Checker & Bank Statement Matcher",
                        "version": "1.0.0",
                    },
                    "instructions": (
                        "Hello! Welcome to BillTally. Use `extract_financial_documents` to check supplier bills "
                        "to the penny, `reconcile_invoices_with_bank_ledger` to match bills against bank withdrawals, "
                        "and `export_ledger_bundle` to generate Excel (.xlsx) or accounting CSV files."
                    ),
                },
            },
            200,
        )

    if method == "ping":
        return ({"jsonrpc": "2.0", "id": req_id, "result": {}}, 200)

    if method == "tools/list":
        return ({"jsonrpc": "2.0", "id": req_id, "result": {"tools": MCP_TOOLS_CATALOG}}, 200)

    if method == "resources/list":
        resources = [
            {
                "uri": f"schemaextract://presets/{p['id']}",
                "name": p["title"],
                "description": p["description"],
                "mimeType": "text/plain",
            }
            for p in get_all_presets()
        ]
        return ({"jsonrpc": "2.0", "id": req_id, "result": {"resources": resources}}, 200)

    if method == "prompts/list":
        return ({"jsonrpc": "2.0", "id": req_id, "result": {"prompts": MCP_PROMPTS_CATALOG}}, 200)

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        return _dispatch_tool_call(req_id, tool_name, arguments, quota_manager, export_dir)

    return (
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        },
        200,
    )


def _coerce_tool_arguments(tool_name: Optional[str], arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize common LLM argument aliases so cold store-review tool calls never fail validation."""
    args = dict(arguments or {})
    if tool_name == "extract_financial_documents":
        if not args.get("raw_text"):
            for alias in ("text", "invoice_text", "bill_text", "document_text", "content", "input"):
                if args.get(alias):
                    args["raw_text"] = str(args[alias])
                    break
    elif tool_name == "reconcile_invoices_with_bank_ledger":
        if "invoices" not in args:
            for alias in ("bills", "documents", "extracted_invoices"):
                if alias in args:
                    args["invoices"] = args[alias]
                    break
        if "bank_transactions" not in args:
            for alias in ("transactions", "withdrawals", "bank_ledger", "statement_rows"):
                if alias in args:
                    args["bank_transactions"] = args[alias]
                    break
    elif tool_name == "export_ledger_bundle":
        if "documents" not in args:
            for alias in ("bills", "invoices", "extracted_documents"):
                if alias in args:
                    args["documents"] = args[alias]
                    break
            for single in ("document", "bill", "invoice"):
                if single in args and isinstance(args[single], dict):
                    args["documents"] = [args[single]]
                    break
    return args


def _dispatch_tool_call(
    req_id: Any,
    tool_name: Optional[str],
    arguments: Dict[str, Any],
    quota_manager: QuotaManager,
    export_dir: Optional[Path],
) -> Tuple[Dict[str, Any], int]:
    """Execute one of the 3 registered MCP tools and format the MCP `content` + `structuredContent` response."""
    try:
        arguments = _coerce_tool_arguments(tool_name, arguments)
        if tool_name == "extract_financial_documents":
            req = ExtractDocumentRequest(**arguments)
            quota_state = quota_manager.consume_document(req.workspace_id, api_key=req.api_key)
            result_obj = extract_financial_document(req, quota_state=quota_state)
            structured = result_obj.model_dump()
            summary_line = (
                f"Hello! Here is your bill check for {result_obj.vendor} (Invoice #{result_obj.invoice_number}): "
                f"{result_obj.plain_english_summary}"
            )
        elif tool_name == "reconcile_invoices_with_bank_ledger":
            req_recon = ReconcileLedgerRequest(**arguments)
            report_obj = reconcile_invoices_with_bank_ledger(req_recon)
            structured = report_obj.model_dump()
            m = report_obj.summary_metrics
            summary_line = (
                f"Hello! Your bank statement comparison is ready: {m['matched_count']} bills matched cleanly, "
                f"{m['unmatched_invoice_count']} bill(s) are still unpaid, "
                f"{m['unmatched_bank_txn_count']} bank withdrawal(s) need a receipt, and "
                f"{m['duplicate_count']} duplicate charge(s) were caught."
            )
        elif tool_name == "export_ledger_bundle":
            req_exp = ExportBundleRequest(**arguments)
            exp_obj = export_ledger_bundle(req_exp, export_dir=export_dir)
            structured = exp_obj.model_dump()
            base_pub = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
            dl_link = f"{base_pub}{exp_obj.download_url}" if base_pub else exp_obj.download_url
            summary_line = (
                f"Your {exp_obj.format.upper()} spreadsheet '{exp_obj.filename}' is ready to download "
                f"({exp_obj.size_bytes} bytes) at {dl_link}"
            )
        else:
            return (
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": f"Unknown MCP tool '{tool_name}'. Available tools: extract_financial_documents, reconcile_invoices_with_bank_ledger, export_ledger_bundle.",
                    },
                },
                200,
            )

        return (
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {"type": "text", "text": summary_line},
                        {"type": "text", "text": json.dumps(structured, indent=2)},
                    ],
                    "structuredContent": structured,
                    "isError": False,
                },
            },
            200,
        )
    except Exception as exc:
        return (
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Tool execution error: {exc}"}],
                    "isError": True,
                },
            },
            200,
        )
