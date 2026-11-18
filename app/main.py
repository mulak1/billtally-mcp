"""BillTally (SchemaExtract MCP) — FastAPI Server Entrypoint (Port 8791)."""

import hmac
import json
import os
from pathlib import Path
import secrets
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs

import anyio
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
import uvicorn

from app.analytics import build_chatgpt_openapi, detect_source, get_analytics_snapshot, record_event, render_analytics_html
from app.exporter import DEFAULT_EXPORT_DIR, export_ledger_bundle, get_ephemeral_export, sanitize_export_filename
from app.extractor import extract_financial_document
from app.mcp_server import MCP_PROTOCOL_VERSION, MCP_TOOLS_CATALOG, handle_mcp_jsonrpc
from app.models import ExportBundleRequest, ExtractDocumentRequest, ReconcileLedgerRequest
from app.oauth_quota import OAuth21Server, QuotaManager, STRIPE_UPGRADE_URL, _is_production_runtime, extract_caller_ip, resolve_request_workspace
from app.pdf_vision_helper import extract_invoice_text_from_upload, parse_upload_from_request
from app.presets import get_all_presets
from app.reconciler import reconcile_invoices_with_bank_ledger
from app.stripe_verify import verify_paid_stripe_checkout_session as _verify_paid_stripe_checkout_session, verify_stripe_webhook_signature as _verify_stripe_webhook_signature
from app.studio_pages import BILLTALLY_FAVICON_SVG, render_about_html, render_docs_html, render_privacy_html, render_terms_html
from app.studio_ui import render_studio_html

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAX_BODY_BYTES = 5_000_000

app = FastAPI(
    title="BillTally",
    description="Plain-English Bill & Invoice Math Checker, Bank Statement Matcher & Spreadsheet Exporter",
    version="1.0.0",
    docs_url="/openapi-docs",
)

oauth_server = OAuth21Server(base_url="http://localhost:8791")
quota_manager = QuotaManager()
_OPENAI_CHALLENGE_STATE: Dict[str, str] = {"token": "YFsHN-fut-TBj-AukzfY5eO_uhEp47qd-ApSrLkjdPg"}


@app.middleware("http")
async def security_headers_and_body_cap(request: Request, call_next: Callable) -> Response:
    """Enforce a streaming 5 MB payload cap (including chunked requests) and attach strict CSP + OWASP headers."""
    cl_header = request.headers.get("content-length")
    if cl_header:
        try:
            if int(cl_header) > MAX_BODY_BYTES:
                return JSONResponse(status_code=413, content={"error": "Payload too large"})
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "Invalid Content-Length header"})

    if request.method in ("POST", "PUT", "PATCH"):
        buf = bytearray()
        async for chunk in request.stream():
            buf.extend(chunk)
            if len(buf) > MAX_BODY_BYTES:
                return JSONResponse(status_code=413, content={"error": "Payload too large"})
        request._body = bytes(buf)

    csp_nonce = secrets.token_urlsafe(18)
    request.state.csp_nonce = csp_nonce
    resp = await call_next(request)
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    resp.headers["Content-Security-Policy"] = (
        f"default-src 'self'; script-src 'self' 'nonce-{csp_nonce}'; "
        "worker-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob:; "
        "connect-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    return resp


@app.get("/.well-known/openai-apps-challenge", response_class=PlainTextResponse)
def get_openai_challenge() -> PlainTextResponse:
    token = _OPENAI_CHALLENGE_STATE.get("token") or os.environ.get("OPENAI_APPS_CHALLENGE", "").strip()
    return PlainTextResponse(content=token)


@app.post("/api/admin/openai-challenge")
async def set_openai_challenge(request: Request) -> JSONResponse:
    admin_secret = os.environ.get("ADMIN_API_SECRET", "").strip()
    provided = request.headers.get("x-admin-secret", "").strip()
    if not admin_secret or not hmac.compare_digest(provided, admin_secret):
        return JSONResponse(status_code=403, content={"error": "Forbidden: valid x-admin-secret required."})
    raw = await request.json()
    token = str(raw.get("token", "")).strip()
    _OPENAI_CHALLENGE_STATE["token"] = token
    return JSONResponse(status_code=200, content={"success": True, "token": token})


@app.get("/openai-plugin.zip")
def download_openai_plugin_zip() -> FileResponse:
    zip_path = PROJECT_ROOT / "billtally-openai-plugin.zip"
    return FileResponse(path=str(zip_path), filename="billtally-openai-plugin.zip", media_type="application/zip")


@app.get("/", response_class=HTMLResponse)
def studio_home(request: Request) -> HTMLResponse:
    src = detect_source(request.headers.get("user-agent", ""), path="/")
    record_event(event_type="page_view", source=src, detail="GET /")
    csp_nonce = getattr(request.state, "csp_nonce", "")
    return HTMLResponse(content=render_studio_html(csp_nonce=csp_nonce))


@app.get("/analytics", response_class=HTMLResponse)
def analytics_page() -> HTMLResponse:
    return HTMLResponse(content=render_analytics_html())


@app.get("/api/analytics")
def api_analytics() -> Dict[str, Any]:
    return get_analytics_snapshot()


@app.get("/chatgpt-openapi.json")
def chatgpt_openapi_spec(request: Request) -> Dict[str, Any]:
    return build_chatgpt_openapi(base_url=_resolve_public_origin(request))


@app.get("/about", response_class=HTMLResponse)
def about_page() -> HTMLResponse:
    return HTMLResponse(content=render_about_html())


@app.get("/docs", response_class=HTMLResponse)
@app.get("/documentation", response_class=HTMLResponse)
def public_docs_page() -> HTMLResponse:
    return HTMLResponse(content=render_docs_html())


@app.get("/health")
def health_check() -> Dict[str, Any]:
    return {"status": "ok", "service": "billtally-mcp", "port": 8791, "protocolVersion": MCP_PROTOCOL_VERSION, "tools_count": len(MCP_TOOLS_CATALOG)}


@app.get("/privacy", response_class=HTMLResponse)
def privacy_policy() -> HTMLResponse:
    return HTMLResponse(content=render_privacy_html())


@app.get("/terms", response_class=HTMLResponse)
def terms_of_service() -> HTMLResponse:
    return HTMLResponse(content=render_terms_html())


@app.get("/favicon.svg")
def get_favicon_svg() -> Response:
    return Response(content=BILLTALLY_FAVICON_SVG, media_type="image/svg+xml")


@app.get("/favicon.ico")
def get_favicon_ico() -> Response:
    ico = PROJECT_ROOT / "openai_plugin_package" / "assets" / "favicon.ico"
    return Response(content=ico.read_bytes(), media_type="image/x-icon") if ico.exists() else get_favicon_svg()


@app.get("/icon.png")
@app.get("/apple-touch-icon.png")
def get_icon_png() -> Response:
    return Response(content=(PROJECT_ROOT / "openai_plugin_package" / "assets" / "icon.png").read_bytes(), media_type="image/png")


@app.get("/mcp")
def mcp_discovery() -> Dict[str, Any]:
    return {
        "name": "billtally-mcp",
        "version": "1.0.0",
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "transport": "streamable-http",
        "endpoint": "/mcp",
        "oauth_discovery": "/.well-known/oauth-authorization-server",
        "tools": [t["name"] for t in MCP_TOOLS_CATALOG],
    }


@app.post("/mcp")
async def mcp_jsonrpc_endpoint(request: Request) -> Response:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error: invalid JSON payload."}})
    ua = request.headers.get("user-agent", "")
    is_prod, caller_ip = _is_production_runtime(request), extract_caller_ip(request)
    caller_ws = resolve_request_workspace(request, oauth_server=oauth_server, quota_manager=quota_manager)
    if isinstance(payload, list):
        if len(payload) == 0:
            return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request: empty JSON-RPC batch."}})
        responses = [
            resp for item in payload
            if (resp := handle_mcp_jsonrpc(item, quota_manager=quota_manager, default_workspace_id=caller_ws, is_prod=is_prod, caller_ip=caller_ip)[0]) is not None
        ]
        return Response(status_code=202) if not responses else JSONResponse(status_code=200, content=responses)
    if isinstance(payload, dict):
        method, params, req_id = payload.get("method", ""), payload.get("params") or {}, str(payload.get("id", ""))
        client_name = (params.get("clientInfo") or {}).get("name", "") if isinstance(params, dict) else ""
        src = "Web Desk" if req_id.startswith("studio-") else detect_source(ua, path="/mcp", client_name=client_name)
        if method == "initialize":
            record_event(event_type="mcp_connect", source=src, detail=client_name or "MCP initialize")
        elif method == "tools/call":
            record_event(event_type="tool_call", source=src, tool_name=str(params.get("name", "-")), detail="MCP tools/call")
    resp_dict, status_code = handle_mcp_jsonrpc(payload, quota_manager=quota_manager, default_workspace_id=caller_ws, is_prod=is_prod, caller_ip=caller_ip)
    return Response(status_code=202) if (status_code == 202 or resp_dict is None) else JSONResponse(status_code=status_code, content=resp_dict)


@app.get("/.well-known/oauth-authorization-server")
def oauth_metadata(request: Request) -> Response:
    if _is_production_runtime(request) and request.query_params.get("oauth") != "1":
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    return JSONResponse(status_code=200, content=oauth_server.metadata(base_url=_resolve_public_origin(request)))


@app.post("/oauth/register")
async def oauth_register(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        registered = oauth_server.register_client(client_name=str(body.get("client_name", "MCP Assistant Client")), redirect_uris=body.get("redirect_uris"), caller_ip=extract_caller_ip(request))
        return JSONResponse(status_code=201, content=registered)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/oauth/authorize")
def oauth_authorize(
    response_type: str = Query(...), client_id: str = Query(...), redirect_uri: str = Query(...),
    code_challenge: str = Query(...), code_challenge_method: str = Query("S256"),
    state: Optional[str] = Query(None), scope: str = Query("mcp:tools mcp:export"),
) -> JSONResponse:
    try:
        issued = oauth_server.issue_authorization_code(
            response_type=response_type, client_id=client_id, redirect_uri=redirect_uri,
            code_challenge=code_challenge, code_challenge_method=code_challenge_method, state=state, scope=scope,
        )
        return JSONResponse(status_code=200, content=issued)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/oauth/token")
async def oauth_token(request: Request) -> JSONResponse:
    raw_body = (await request.body()).decode("utf-8", errors="ignore").strip()
    body: Dict[str, Any] = {}
    if raw_body.startswith("{"):
        try:
            body = json.loads(raw_body)
        except Exception:
            body = {}
    else:
        parsed_qs = parse_qs(raw_body, keep_blank_values=True)
        body = {k: (v[0] if v else "") for k, v in parsed_qs.items()}
    try:
        token_data = oauth_server.exchange_code_for_token(
            grant_type=str(body.get("grant_type", "")), code=str(body.get("code", "")),
            client_id=str(body.get("client_id", "")), redirect_uri=str(body.get("redirect_uri", "")),
            code_verifier=str(body.get("code_verifier", "")), refresh_token=str(body.get("refresh_token", "")),
        )
        return JSONResponse(status_code=200, content=token_data)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": str(exc)})


@app.get("/api/presets")
def api_presets() -> Dict[str, Any]:
    return {"presets": get_all_presets()}


@app.get("/api/quota")
def api_quota_status(request: Request, workspace_id: str = "default-workspace", api_key: Optional[str] = None) -> Dict[str, Any]:
    is_prod = _is_production_runtime(request)
    ws = resolve_request_workspace(request, workspace_id, oauth_server=oauth_server, quota_manager=quota_manager, api_key=api_key)
    return quota_manager.get_status(workspace_id=ws, api_key=api_key, is_prod=is_prod)


@app.post("/api/quota/upgrade")
async def api_quota_upgrade(
    request: Request,
    workspace_id: str = "default-workspace",
    checkout_session_id: Optional[str] = None,
) -> Response:
    is_prod_https = _is_production_runtime(request)
    admin_secret = os.environ.get("ADMIN_API_SECRET", "").strip()
    provided_admin = request.headers.get("x-admin-secret", "").strip()
    admin_ok = bool(admin_secret and hmac.compare_digest(provided_admin, admin_secret))

    body_sid = ""
    if not checkout_session_id:
        try:
            body_json = await request.json()
            if isinstance(body_json, dict):
                body_sid = str(body_json.get("checkout_session_id", "")).strip()
        except Exception:
            body_sid = ""
    sid = (checkout_session_id or body_sid or "").strip()

    ws = resolve_request_workspace(request, workspace_id, oauth_server=oauth_server, quota_manager=quota_manager)
    src = detect_source(request.headers.get("user-agent", ""), path="/api/quota/upgrade")

    if is_prod_https and not admin_ok and (not sid or not _verify_paid_stripe_checkout_session(sid)):
        return JSONResponse(status_code=403, content={"error": "Stripe checkout required to unlock Pro.", "checkout_url": STRIPE_UPGRADE_URL})
    if sid:
        upgraded, should_log = quota_manager.claim_stripe_browser_session(sid, ws)
        if upgraded is None:
            return JSONResponse(status_code=403, content={"error": "Stripe checkout session has already been claimed.", "checkout_url": STRIPE_UPGRADE_URL})
    else:
        upgraded, should_log = quota_manager.upgrade_to_pro(workspace_id=ws), True

    if should_log:
        record_event(event_type="pro_unlock", source=src, detail="pro_tier_unlocked")
    return JSONResponse(status_code=200, content=upgraded)


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request) -> JSONResponse:
    wh_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    raw_body = await request.body()
    sig_hdr = request.headers.get("stripe-signature", "")
    if not _verify_stripe_webhook_signature(raw_body, sig_hdr, wh_secret):
        return JSONResponse(status_code=400, content={"error": "Invalid Stripe webhook signature."})
    try:
        event = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse(status_code=400, content={"error": "Malformed JSON webhook body."})
    if not isinstance(event, dict):
        return JSONResponse(status_code=400, content={"error": "Expected JSON object webhook payload."})
    if event.get("type") == "checkout.session.completed":
        obj = (event.get("data") or {}).get("object") or {}
        sid = str(obj.get("id", "")).strip()
        if obj.get("payment_status") == "paid" and sid:
            ws = str(obj.get("client_reference_id") or f"stripe-{sid[-12:]}")
            upgraded, should_log = quota_manager.redeem_stripe_webhook(sid, ws)
            if upgraded is not None:
                if should_log:
                    record_event(event_type="pro_unlock", source="Stripe Webhook", detail="pro_tier_unlocked")
                return JSONResponse(status_code=200, content={"received": True, "workspace_id": ws, "tier": upgraded["tier"]})
    return JSONResponse(status_code=200, content={"received": True})


@app.post("/api/extract")
def api_extract_document(req: ExtractDocumentRequest, request: Request) -> Dict[str, Any]:
    is_prod = _is_production_runtime(request)
    caller_ip = extract_caller_ip(request)
    ws = resolve_request_workspace(request, req.workspace_id, oauth_server=oauth_server, quota_manager=quota_manager, api_key=req.api_key)
    try:
        quota_manager.check_available(ws, api_key=req.api_key, is_prod=is_prod, caller_ip=caller_ip)
    except PermissionError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    try:
        parsed = extract_financial_document(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    quota_state = quota_manager.consume_document(ws, api_key=req.api_key, is_prod=is_prod, caller_ip=caller_ip)
    result = parsed.model_copy(update={"quota_state": quota_state})
    src = detect_source(request.headers.get("user-agent", ""), path="/api/extract")
    record_event(event_type="tool_call", source=src, tool_name="extract_financial_documents", detail="invoice_checked")
    return result.model_dump()


def _process_uploaded_file_sync(raw_body: bytes, content_type: str, query_params: Dict[str, str], request: Request) -> Dict[str, Any]:
    upload = parse_upload_from_request(raw_body, content_type, query_params)
    is_prod, caller_ip, api_key = _is_production_runtime(request), extract_caller_ip(request), upload["api_key"]
    ws = resolve_request_workspace(request, upload["workspace_id"], oauth_server=oauth_server, quota_manager=quota_manager, api_key=api_key)
    quota_manager.check_available(ws, api_key=api_key, is_prod=is_prod, caller_ip=caller_ip)
    reserved: Dict[str, Any] = {}
    extracted_text, method = extract_invoice_text_from_upload(
        upload["filename"], upload["file_bytes"],
        before_vision_ocr=lambda: reserved.setdefault("state", quota_manager.consume_document(ws, api_key=api_key, is_prod=is_prod, caller_ip=caller_ip)),
    )
    doc_type = upload["document_type"] if upload["document_type"] in ("invoice", "receipt", "bank_statement", "auto") else "invoice"
    parsed = extract_financial_document(ExtractDocumentRequest(raw_text=extracted_text, document_type=doc_type, currency_hint=upload["currency_hint"], strict_reconciliation=upload["strict_reconciliation"], workspace_id=ws, api_key=api_key))
    quota_state = reserved.get("state") or quota_manager.consume_document(ws, api_key=api_key, is_prod=is_prod, caller_ip=caller_ip)
    result = parsed.model_copy(update={"quota_state": quota_state}).model_dump()
    result.update({"extracted_text": extracted_text, "extraction_method": method, "filename": Path(upload["filename"]).name[:120]})
    return result


@app.post("/api/extract-file")
async def api_extract_uploaded_file(request: Request) -> Dict[str, Any]:
    raw_body = await request.body()
    try:
        result = await anyio.to_thread.run_sync(_process_uploaded_file_sync, raw_body, request.headers.get("content-type", ""), dict(request.query_params), request)
    except PermissionError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_event(event_type="tool_call", source=detect_source(request.headers.get("user-agent", ""), path="/api/extract-file"), tool_name="extract_financial_documents", detail=f"file_{result['extraction_method']}")
    return result


@app.post("/api/reconcile")
def api_reconcile_ledger(req: ReconcileLedgerRequest, request: Request) -> Dict[str, Any]:
    report = reconcile_invoices_with_bank_ledger(req)
    src = detect_source(request.headers.get("user-agent", ""), path="/api/reconcile")
    record_event(event_type="tool_call", source=src, tool_name="reconcile_invoices_with_bank_ledger", detail=f"{len(req.invoices)} bills")
    return report.model_dump()


@app.post("/api/export")
def api_export_bundle(req: ExportBundleRequest, request: Request) -> Dict[str, Any]:
    is_prod = _is_production_runtime(request)
    api_key = req.api_key or request.query_params.get("api_key") or None
    ws_hint = request.query_params.get("workspace_id") or req.workspace_id
    ws = resolve_request_workspace(request, ws_hint, oauth_server=oauth_server, quota_manager=quota_manager, api_key=api_key)
    try:
        quota_manager.consume_export(ws, api_key=api_key, doc_count=len(req.documents), is_prod=is_prod)
    except PermissionError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    result = export_ledger_bundle(req)
    src = detect_source(request.headers.get("user-agent", ""), path="/api/export")
    record_event(event_type="tool_call", source=src, tool_name="export_ledger_bundle", detail=req.format)
    return result.model_dump()


@app.get("/downloads/{filename}")
def download_exported_bundle(filename: str, request: Request) -> Response:
    safe_base = sanitize_export_filename(Path(filename).stem)
    ext = Path(filename).suffix.lower()
    if ext not in (".xlsx", ".csv"):
        raise HTTPException(status_code=400, detail="Unsupported file extension.")
    safe_name = f"{safe_base}{ext}"
    media_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if ext == ".xlsx"
        else "text/csv; charset=utf-8"
    )
    mem_bytes = get_ephemeral_export(safe_name)
    if mem_bytes is not None:
        src = detect_source(request.headers.get("user-agent", ""), path="/downloads")
        record_event(event_type="spreadsheet_download", source=src, tool_name="export_ledger_bundle", detail=ext.lstrip("."))
        return Response(
            content=mem_bytes,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
        )
    resolved = (DEFAULT_EXPORT_DIR / safe_name).resolve()
    if not str(resolved).startswith(str(DEFAULT_EXPORT_DIR.resolve())) or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Export file not found or expired.")
    src = detect_source(request.headers.get("user-agent", ""), path="/downloads")
    record_event(event_type="spreadsheet_download", source=src, tool_name="export_ledger_bundle", detail=ext.lstrip("."))
    return FileResponse(path=str(resolved), filename=resolved.name, media_type=media_type)


def _resolve_public_origin(request: Request) -> str:
    env_url = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if env_url:
        return env_url
    base = str(request.base_url).rstrip("/")
    if "testserver" in base:
        return "http://localhost:8791"
    if (request.headers.get("x-forwarded-proto") == "https" or "railway.app" in base) and base.startswith("http://"):
        base = "https://" + base[len("http://") :]
    return base


@app.get("/manifests/claude")
def get_claude_manifest(request: Request) -> Dict[str, Any]:
    manifest_path = PROJECT_ROOT / "claude-connector-manifest.json"
    origin = _resolve_public_origin(request)
    raw = manifest_path.read_text(encoding="utf-8").replace("http://localhost:8791", origin)
    return json.loads(raw)


@app.get("/manifests/openai")
def get_openai_manifest(request: Request) -> Dict[str, Any]:
    manifest_path = PROJECT_ROOT / "openai-mcp-app.json"
    origin = _resolve_public_origin(request)
    raw = manifest_path.read_text(encoding="utf-8").replace("http://localhost:8791", origin)
    return json.loads(raw)


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8791"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
