"""BillTally (SchemaExtract MCP) — FastAPI Server Entrypoint (Port 8791)."""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
import uvicorn

from app.analytics import build_chatgpt_openapi, detect_source, get_analytics_snapshot, record_event, render_analytics_html
from app.exporter import DEFAULT_EXPORT_DIR, export_ledger_bundle, sanitize_export_filename
from app.extractor import extract_financial_document
from app.mcp_server import MCP_PROTOCOL_VERSION, MCP_TOOLS_CATALOG, handle_mcp_jsonrpc
from app.models import ExportBundleRequest, ExtractDocumentRequest, ReconcileLedgerRequest
from app.oauth_quota import OAuth21Server, QuotaManager
from app.presets import get_all_presets
from app.reconciler import reconcile_invoices_with_bank_ledger
from app.studio_pages import BILLTALLY_FAVICON_SVG, render_about_html, render_docs_html, render_privacy_html, render_terms_html
from app.studio_ui import render_studio_html

PROJECT_ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(
    title="BillTally",
    description="Plain-English Bill & Invoice Math Checker, Bank Statement Matcher & Spreadsheet Exporter",
    version="1.0.0",
    docs_url="/openapi-docs",
)

oauth_server = OAuth21Server(base_url="http://localhost:8791")
quota_manager = QuotaManager()
_OPENAI_CHALLENGE_STATE: Dict[str, str] = {"token": "YFsHN-fut-TBj-AukzfY5eO_uhEp47qd-ApSrLkjdPg"}


@app.get("/.well-known/openai-apps-challenge", response_class=PlainTextResponse)
def get_openai_challenge() -> PlainTextResponse:
    """Serve OpenAI's domain verification challenge token."""
    token = _OPENAI_CHALLENGE_STATE.get("token") or os.environ.get("OPENAI_APPS_CHALLENGE", "").strip()
    return PlainTextResponse(content=token)


@app.post("/api/admin/openai-challenge")
async def set_openai_challenge(request: Request) -> JSONResponse:
    """Dynamically set the OpenAI domain verification token without redeploying."""
    raw = await request.json()
    token = str(raw.get("token", "")).strip()
    _OPENAI_CHALLENGE_STATE["token"] = token
    return JSONResponse(status_code=200, content={"success": True, "token": token})


@app.get("/openai-plugin.zip")
def download_openai_plugin_zip() -> FileResponse:
    """Download the ready-to-upload Portable Agent Plugins .zip package for platform.openai.com/plugins."""
    zip_path = PROJECT_ROOT / "billtally-openai-plugin.zip"
    return FileResponse(path=str(zip_path), filename="billtally-openai-plugin.zip", media_type="application/zip")


@app.get("/", response_class=HTMLResponse)
def studio_home(request: Request) -> HTMLResponse:
    """Serve the Interactive Financial Accounting Web Studio & Store Listing Preview."""
    src = detect_source(request.headers.get("user-agent", ""), path="/")
    if "pro_activated=1" in str(request.url.query):
        quota_manager.upgrade_to_pro()
        record_event(event_type="pro_unlock", source=src, detail="Stripe Redirect")
    else:
        record_event(event_type="page_view", source=src, detail="GET /")
    return HTMLResponse(content=render_studio_html())


@app.get("/analytics", response_class=HTMLResponse)
def analytics_page() -> HTMLResponse:
    """Serve the live HTML Analytics Dashboard across Claude, ChatGPT, and Web."""
    return HTMLResponse(content=render_analytics_html())


@app.get("/api/analytics")
def api_analytics() -> Dict[str, Any]:
    """Return the live privacy-safe telemetry snapshot in JSON format."""
    return get_analytics_snapshot()


@app.get("/chatgpt-openapi.json")
def chatgpt_openapi_spec(request: Request) -> Dict[str, Any]:
    """Return the OpenAPI 3.1.0 specification for ChatGPT custom plugin / Actions."""
    origin = _resolve_public_origin(request)
    return build_chatgpt_openapi(base_url=origin)


@app.get("/about", response_class=HTMLResponse)
def about_page() -> HTMLResponse:
    """Serve the public About & Company Information HTML page."""
    return HTMLResponse(content=render_about_html())


@app.get("/docs", response_class=HTMLResponse)
@app.get("/documentation", response_class=HTMLResponse)
def public_docs_page() -> HTMLResponse:
    """Serve the public User & IT Administrator Documentation HTML page."""
    return HTMLResponse(content=render_docs_html())


@app.get("/health")
def health_check() -> Dict[str, Any]:
    """Health check endpoint for Claude & ChatGPT MCP directory probes."""
    return {
        "status": "ok",
        "service": "billtally-mcp",
        "port": 8791,
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "tools_count": len(MCP_TOOLS_CATALOG),
    }


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
    """Streamable HTTP MCP server discovery & capability probe."""
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
async def mcp_jsonrpc_endpoint(request: Request) -> JSONResponse:
    """Handle JSON-RPC 2.0 requests and notifications over Streamable HTTP."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error: invalid JSON payload."},
            },
        )

    ua = request.headers.get("user-agent", "")
    if isinstance(payload, list):
        responses = []
        for item in payload:
            resp, _ = handle_mcp_jsonrpc(item, quota_manager=quota_manager)
            if resp is not None:
                responses.append(resp)
        return JSONResponse(status_code=200, content=responses)

    if isinstance(payload, dict):
        method = payload.get("method", "")
        params = payload.get("params") or {}
        req_id = str(payload.get("id", ""))
        client_name = (params.get("clientInfo") or {}).get("name", "") if isinstance(params, dict) else ""
        src = "Web Desk" if req_id.startswith("studio-") else detect_source(ua, path="/mcp", client_name=client_name)
        if method == "initialize":
            record_event(event_type="mcp_connect", source=src, detail=client_name or "MCP initialize")
        elif method == "tools/call":
            t_name = str(params.get("name", "-"))
            record_event(event_type="tool_call", source=src, tool_name=t_name, detail="MCP tools/call")

    resp_dict, status_code = handle_mcp_jsonrpc(payload, quota_manager=quota_manager)
    if status_code == 202 or resp_dict is None:
        return Response(status_code=202)
    return JSONResponse(status_code=status_code, content=resp_dict)


# ==============================================================================
# OAUTH 2.1 WITH S256 PKCE & DYNAMIC CLIENT REGISTRATION ENDPOINTS
# ==============================================================================

@app.get("/.well-known/oauth-authorization-server")
def oauth_metadata(request: Request) -> Response:
    """RFC 8414 OAuth 2.1 Authorization Server Metadata with S256 PKCE support."""
    is_prod_https = (
        request.headers.get("x-forwarded-proto") == "https"
        or "railway.app" in str(request.base_url)
        or bool(os.environ.get("PUBLIC_BASE_URL"))
    )
    if is_prod_https and request.query_params.get("oauth") != "1":
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    base = _resolve_public_origin(request)
    return JSONResponse(status_code=200, content=oauth_server.metadata(base_url=base))


@app.post("/oauth/register")
async def oauth_register(request: Request) -> JSONResponse:
    """RFC 7591 Dynamic Client Registration Endpoint for Claude & ChatGPT connectors."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    registered = oauth_server.register_client(
        client_name=str(body.get("client_name", "MCP Assistant Client")),
        redirect_uris=body.get("redirect_uris"),
    )
    return JSONResponse(status_code=201, content=registered)


@app.get("/oauth/authorize")
def oauth_authorize(
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query("S256"),
    state: Optional[str] = Query(None),
    scope: str = Query("mcp:tools mcp:export"),
) -> JSONResponse:
    """OAuth 2.1 Authorization Endpoint enforcing S256 PKCE code_challenge."""
    try:
        issued = oauth_server.issue_authorization_code(
            response_type=response_type,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            state=state,
            scope=scope,
        )
        return JSONResponse(status_code=200, content=issued)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/oauth/token")
async def oauth_token(request: Request) -> JSONResponse:
    """OAuth 2.1 Token Endpoint verifying S256 PKCE `code_verifier` or `refresh_token`."""
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
            grant_type=str(body.get("grant_type", "")),
            code=str(body.get("code", "")),
            client_id=str(body.get("client_id", "")),
            redirect_uri=str(body.get("redirect_uri", "")),
            code_verifier=str(body.get("code_verifier", "")),
            refresh_token=str(body.get("refresh_token", "")),
        )
        return JSONResponse(status_code=200, content=token_data)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_grant", "error_description": str(exc)},
        )


# ==============================================================================
# REST API & DOWNLOAD / MANIFEST ENDPOINTS
# ==============================================================================

@app.get("/api/presets")
def api_presets() -> Dict[str, Any]:
    return {"presets": get_all_presets()}


@app.get("/api/quota")
def api_quota_status(workspace_id: str = "default-workspace", api_key: Optional[str] = None) -> Dict[str, Any]:
    return quota_manager.get_status(workspace_id=workspace_id, api_key=api_key)


@app.post("/api/quota/upgrade")
def api_quota_upgrade(request: Request, workspace_id: str = "default-workspace") -> Dict[str, Any]:
    src = detect_source(request.headers.get("user-agent", ""), path="/api/quota/upgrade")
    record_event(event_type="pro_unlock", source=src, detail=workspace_id)
    return quota_manager.upgrade_to_pro(workspace_id=workspace_id)


@app.post("/api/extract")
def api_extract_document(req: ExtractDocumentRequest, request: Request) -> Dict[str, Any]:
    try:
        quota_state = quota_manager.consume_document(req.workspace_id, api_key=req.api_key)
    except PermissionError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    result = extract_financial_document(req, quota_state=quota_state)
    src = detect_source(request.headers.get("user-agent", ""), path="/api/extract")
    record_event(event_type="tool_call", source=src, tool_name="extract_financial_documents", detail=result.invoice_number)
    return result.model_dump()


@app.post("/api/reconcile")
def api_reconcile_ledger(req: ReconcileLedgerRequest, request: Request) -> Dict[str, Any]:
    report = reconcile_invoices_with_bank_ledger(req)
    src = detect_source(request.headers.get("user-agent", ""), path="/api/reconcile")
    record_event(event_type="tool_call", source=src, tool_name="reconcile_invoices_with_bank_ledger", detail=f"{len(req.invoices)} bills")
    return report.model_dump()


@app.post("/api/export")
def api_export_bundle(req: ExportBundleRequest, request: Request) -> Dict[str, Any]:
    result = export_ledger_bundle(req)
    src = detect_source(request.headers.get("user-agent", ""), path="/api/export")
    record_event(event_type="tool_call", source=src, tool_name="export_ledger_bundle", detail=result.filename)
    return result.model_dump()


@app.get("/downloads/{filename}")
def download_exported_bundle(filename: str, request: Request) -> FileResponse:
    safe_base = sanitize_export_filename(Path(filename).stem)
    ext = Path(filename).suffix.lower()
    if ext not in (".xlsx", ".csv"):
        raise HTTPException(status_code=400, detail="Unsupported file extension.")
    resolved = (DEFAULT_EXPORT_DIR / f"{safe_base}{ext}").resolve()
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Export file not found.")
    src = detect_source(request.headers.get("user-agent", ""), path="/downloads")
    record_event(event_type="spreadsheet_download", source=src, tool_name="export_ledger_bundle", detail=resolved.name)
    media_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if ext == ".xlsx"
        else "text/csv"
    )
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
