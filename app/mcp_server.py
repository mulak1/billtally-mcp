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

from app.audit_links import create_audit_link
from app.exporter import export_ledger_bundle
from app.extractor import extract_financial_document
from app.mcp_catalog import MCP_PROMPTS_CATALOG, MCP_PROTOCOL_VERSION, MCP_TOOLS_CATALOG
from app.mcp_compound import (
    get_mcp_prompt_response,
    list_mcp_resources,
    parse_raw_bank_csv_text,
    read_mcp_resource_response,
    run_audit_and_export_pack,
)
from app.models import (
    ExportBundleRequest,
    ExtractDocumentRequest,
    ReconcileLedgerRequest,
)
from app.oauth_quota import QuotaManager
from app.reconciler import reconcile_invoices_with_bank_ledger


def handle_mcp_jsonrpc(
    payload: Dict[str, Any],
    quota_manager: QuotaManager,
    export_dir: Optional[Path] = None,
    default_workspace_id: str = "default-workspace",
    is_prod: bool = False,
    caller_ip: str = "",
    public_base_url: str = "",
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
    if not isinstance(method, str) or not method:
        return (
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32600, "message": "Invalid Request: method must be a non-empty string."},
            },
            400,
        )
    raw_params = payload.get("params")
    if raw_params is not None and not isinstance(raw_params, dict):
        return (
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": "Invalid params: expected JSON object."},
            },
            200,
        )
    params = raw_params or {}

    if method.startswith("notifications/") or "id" not in payload:
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
                        "version": "1.1.0",
                    },
                    "instructions": (
                        "Hello! Welcome to BillTally. Use `audit_and_export_pack` for a 1-call bill check, bank CSV match, "
                        "Verified Dispute Link, and Excel (.xlsx) export — or use `extract_financial_documents`, "
                        "`reconcile_invoices_with_bank_ledger`, and `export_ledger_bundle` individually."
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
        return ({"jsonrpc": "2.0", "id": req_id, "result": {"resources": list_mcp_resources()}}, 200)

    if method == "resources/read":
        uri = str(params.get("uri", "")).strip() if isinstance(params, dict) else ""
        try:
            return ({"jsonrpc": "2.0", "id": req_id, "result": read_mcp_resource_response(uri)}, 200)
        except KeyError as exc:
            return ({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": str(exc)}}, 200)

    if method == "prompts/list":
        return ({"jsonrpc": "2.0", "id": req_id, "result": {"prompts": MCP_PROMPTS_CATALOG}}, 200)

    if method == "prompts/get":
        p_name = str(params.get("name", "")).strip() if isinstance(params, dict) else ""
        p_args = params.get("arguments") if isinstance(params, dict) else None
        try:
            return ({"jsonrpc": "2.0", "id": req_id, "result": get_mcp_prompt_response(p_name, p_args)}, 200)
        except KeyError as exc:
            return ({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": str(exc)}}, 200)

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if tool_name in ("extract_financial_documents", "audit_and_export_pack", "export_ledger_bundle") and isinstance(arguments, dict):
            has_pro = quota_manager.is_valid_pro_key(arguments.get("api_key"), is_prod=is_prod)
            if (is_prod and not has_pro) or not arguments.get("workspace_id") or arguments.get("workspace_id") == "default-workspace":
                arguments = {**arguments, "workspace_id": default_workspace_id}
        return _dispatch_tool_call(
            req_id,
            tool_name,
            arguments,
            quota_manager,
            export_dir,
            is_prod=is_prod,
            caller_ip=caller_ip,
            public_base_url=public_base_url,
        )

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
    if tool_name in ("extract_financial_documents", "audit_and_export_pack"):
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
        if (not args.get("bank_transactions")) and args.get("bank_csv_text"):
            args["bank_transactions"] = parse_raw_bank_csv_text(str(args["bank_csv_text"]))
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
    *,
    is_prod: bool = False,
    caller_ip: str = "",
    public_base_url: str = "",
) -> Tuple[Dict[str, Any], int]:
    """Execute one of the registered MCP tools and format the MCP `content` + `structuredContent` response."""
    try:
        arguments = _coerce_tool_arguments(tool_name, arguments)
        base_pub = (public_base_url or os.environ.get("PUBLIC_BASE_URL", "")).rstrip("/")
        if tool_name == "extract_financial_documents":
            req = ExtractDocumentRequest(**arguments)
            quota_manager.check_available(req.workspace_id, api_key=req.api_key, is_prod=is_prod, caller_ip=caller_ip)
            parsed_obj = extract_financial_document(req)
            quota_state = quota_manager.consume_document(
                req.workspace_id, api_key=req.api_key, is_prod=is_prod, caller_ip=caller_ip
            )
            result_obj = parsed_obj.model_copy(update={"quota_state": quota_state})
            structured = result_obj.model_dump()
            audit_meta = create_audit_link(structured, public_base_url=base_pub)
            structured["verified_audit_link"] = audit_meta
            structured["web_desk_url"] = f"{base_pub}/" if base_pub else "/"
            if structured.get("vendor_dispute_note") and not structured.get("math_verified", True):
                structured["vendor_dispute_note"] = (
                    f"{structured['vendor_dispute_note']}\n\n"
                    f"Independent line-by-line math breakdown: {audit_meta['audit_url']}"
                )
            summary_line = (
                f"Hello! Here is your bill check for {result_obj.vendor} (Invoice #{result_obj.invoice_number}): "
                f"{result_obj.plain_english_summary} "
                f"Verified Audit Link: {audit_meta['audit_url']}"
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
            quota_manager.check_export_available(
                req_exp.workspace_id, api_key=req_exp.api_key, doc_count=len(req_exp.documents), is_prod=is_prod, caller_ip=caller_ip
            )
            exp_obj = export_ledger_bundle(req_exp, export_dir=export_dir)
            quota_manager.consume_export(
                req_exp.workspace_id, api_key=req_exp.api_key, doc_count=len(req_exp.documents), is_prod=is_prod, caller_ip=caller_ip
            )
            structured = exp_obj.model_dump()
            dl_link = f"{base_pub}{exp_obj.download_url}" if base_pub else exp_obj.download_url
            summary_line = (
                f"Your {exp_obj.format.upper()} spreadsheet '{exp_obj.filename}' is ready to download "
                f"({exp_obj.size_bytes} bytes) at {dl_link}"
            )
        elif tool_name == "audit_and_export_pack":
            summary_line, structured = run_audit_and_export_pack(
                arguments,
                quota_manager=quota_manager,
                export_dir=export_dir,
                is_prod=is_prod,
                caller_ip=caller_ip,
                public_base_url=base_pub,
            )
        else:
            return (
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": f"Unknown MCP tool '{tool_name}'. Available tools: extract_financial_documents, reconcile_invoices_with_bank_ledger, export_ledger_bundle, audit_and_export_pack.",
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
