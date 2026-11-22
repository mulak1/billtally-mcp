"""
Static MCP Tool and Prompt Schema Catalog for BillTally (`MCP_TOOLS_CATALOG`, `MCP_PROMPTS_CATALOG`).
Extracted from `app/mcp_server.py` so every module stays cleanly under the 500-line soft cap.
"""

from typing import Any, Dict, List

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
                "workspace_id": {
                    "type": "string",
                    "description": "Optional workspace identifier for monthly bill-check quota tracking.",
                },
                "api_key": {
                    "type": "string",
                    "description": "Optional BillTally Pro API key for high-volume monthly bill checks (5,000 docs/mo).",
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
                "bank_csv_text": {
                    "type": "string",
                    "description": "Optional raw CSV or line-delimited bank statement text (auto-parsed into bank_transactions when provided).",
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
                "api_key": {
                    "type": "string",
                    "description": "Optional BillTally Pro API key.",
                },
            },
            "required": ["invoices"],
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
                "api_key": {
                    "type": "string",
                    "description": "Optional BillTally Pro API key.",
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
    {
        "name": "audit_and_export_pack",
        "title": "Audit Bill, Match Bank CSV & Export Verified Pack (1-Call)",
        "description": (
            "All-in-one compound audit tool: penny-verifies a supplier bill, optionally matches it against pasted "
            "bank statement CSV text or transactions, mints a 14-day shareable Verified Dispute Link (/v/<id>) with "
            "SHA-256 checksum, and generates a downloadable 3-tab Excel (.xlsx) workbook with live =SUM() formulas "
            "or QuickBooks CSV in a single round-trip."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "raw_text": {
                    "type": "string",
                    "description": "Raw supplier bill, receipt, or CAM reconciliation text to verify.",
                },
                "bank_csv_text": {
                    "type": "string",
                    "description": "Optional pasted bank statement CSV or line text to cross-match against the bill.",
                },
                "bank_transactions": {
                    "type": "array",
                    "description": "Optional structured bank withdrawal rows to cross-match against the bill.",
                    "items": {"type": "object"},
                },
                "format": {
                    "type": "string",
                    "enum": ["xlsx", "csv", "quickbooks_csv"],
                    "default": "xlsx",
                    "description": "Spreadsheet output format (xlsx, csv, or quickbooks_csv).",
                },
                "use_corrected_amounts": {
                    "type": "boolean",
                    "description": "When true, exports verified true math totals instead of overcharged billed totals.",
                },
                "bundle_name": {
                    "type": "string",
                    "description": "Optional label for the exported spreadsheet filename.",
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional workspace identifier for quota tracking.",
                },
                "api_key": {
                    "type": "string",
                    "description": "Optional BillTally Pro API key.",
                },
            },
            "required": ["raw_text"],
        },
        "annotations": {
            "title": "1-Call Bill Audit, Dispute Link & Excel Pack",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
]

MCP_PROMPTS_CATALOG: List[Dict[str, Any]] = [
    {
        "name": "run_demo_overcharge_audit",
        "title": "Try 1-click demo: Catch a +$200 plumbing overcharge & export Excel",
        "description": "Zero-input demo that audits a sample contractor bill, catches a +$200.00 error, mints a Verified Dispute Link, and builds a 3-tab Excel pack.",
    },
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
