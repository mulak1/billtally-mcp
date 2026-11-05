"""
8-Step TDD Comprehensive Test Suite for SchemaExtract MCP.
Covers:
1. Deterministic Financial Document Extraction & Mathematical Reconciliation
2. Discrepant Invoice Detection (Line-item & Total math errors)
3. Input Boundary Validation & Immutability guarantees
4. Invoice-to-Bank-Ledger Cross-Matching & Duplicate Detection
5. Multi-Tab .xlsx (with Excel SUM/ROUND formulas) and QuickBooks .csv Exports
6. Streamable HTTP MCP JSON-RPC 2.0 Endpoint (`POST /mcp` & `GET /mcp`) & Tool Annotations
7. OAuth 2.1 with S256 PKCE Flow (`/.well-known/oauth-authorization-server`, `/oauth/authorize`, `/oauth/token`)
8. Free (15 docs/mo) vs Pro ($29/mo) Quota Enforcement, Web Studio UI, and Store Manifests
"""

import base64
import hashlib
import io
import json
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.exporter import export_ledger_bundle, sanitize_export_filename
from app.extractor import extract_financial_document
from app.main import app
from app.models import (
    ExportBundleRequest,
    ExtractDocumentRequest,
    ReconcileLedgerRequest,
)
from app.oauth_quota import QuotaManager
from app.presets import get_all_presets, get_preset_by_id
from app.reconciler import reconcile_invoices_with_bank_ledger


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ==============================================================================
# 1. FINANCIAL EXTRACTION & MATHEMATICAL RECONCILIATION TESTS
# ==============================================================================

def test_extract_balanced_saas_invoice_verifies_math():
    """
    User Journey 1: As a bookkeeper, I want multi-line supplier bills checked
    with deterministic math verification (`sum(line_items) + tax == total`) and plain-English summary.
    """
    preset = get_preset_by_id("messy_saas_invoice")
    req = ExtractDocumentRequest(
        raw_text=preset["raw_text"],
        document_type="invoice",
    )
    result = extract_financial_document(req)

    assert result.vendor == "Heartland Flour & Pantry Supply Co."
    assert result.invoice_number == "INV-2026-0842"
    assert result.currency == "USD"
    assert len(result.line_items) == 5
    assert result.math_verified is True
    assert result.discrepancy_delta == 0.0
    assert len(result.discrepancies) == 0
    assert result.computed_subtotal == result.subtotal
    assert result.computed_total == result.total
    assert result.confidence_score >= 0.90
    assert "add up to the penny" in result.plain_english_summary
    assert result.vendor_dispute_note is None
    assert "Food & Pantry" in result.suggested_category
    assert len(result.normalized_rows) == len(result.line_items)


def test_extract_discrepant_contractor_invoice_flags_exact_delta():
    """
    User Journey 2: As a bookkeeper, I want bills with line-item or subtotal/total
    addition errors flagged with `math_verified=False`, exact discrepancy delta, and a polite supplier note.
    """
    preset = get_preset_by_id("discrepant_contractor_invoice")
    req = ExtractDocumentRequest(
        raw_text=preset["raw_text"],
        document_type="invoice",
    )
    result = extract_financial_document(req)

    assert result.vendor == "Oakridge Plumbing & Heating Services"
    assert result.invoice_number == "INV-9914-B"
    assert result.math_verified is False
    # Reported total is $200.00 higher than true computed line item sum + tax
    assert abs(result.discrepancy_delta) == pytest.approx(200.0, abs=0.01)
    assert len(result.discrepancies) >= 1
    assert any(d.field in ("line_item_3", "subtotal", "total") for d in result.discrepancies)
    assert "Hold payment" in result.plain_english_summary
    assert result.vendor_dispute_note is not None
    assert "INV-9914-B" in result.vendor_dispute_note
    assert "$6,505.30" in result.vendor_dispute_note


def test_extract_markdown_table_and_structured_json_payload():
    """Supports markdown tables as well as base64/JSON structured payloads."""
    md_doc = """
    Vendor: Northbound Paper & Packaging Co.
    Invoice #: NPP-2026-441
    Date: 2026-10-14
    Due Date: 2026-11-13
    Currency: EUR

    | Description | Qty | Unit Price | Amount |
    | :--- | ---: | ---: | ---: |
    | Corrugated Shipping Boxes (Bundle of 50) | 2 | 450.00 | 900.00 |
    | Kraft Paper Packing Tape Rolls (Case) | 3 | 220.00 | 660.00 |
    | Scheduled Warehouse Pallet Delivery | 1 | 340.00 | 340.00 |

    Subtotal: 1900.00
    Tax: 380.00
    Total: 2280.00
    """
    res_md = extract_financial_document(ExtractDocumentRequest(raw_text=md_doc, document_type="invoice"))
    assert res_md.vendor == "Northbound Paper & Packaging Co."
    assert res_md.invoice_number == "NPP-2026-441"
    assert res_md.currency == "EUR"
    assert len(res_md.line_items) == 3
    assert res_md.subtotal == 1900.00
    assert res_md.tax == 380.00
    assert res_md.total == 2280.00
    assert res_md.math_verified is True

    # Also test base64 encoded JSON payload
    structured = {
        "vendor": "Harbor Merchant Processing",
        "invoice_number": "HMP-88210",
        "issue_date": "2026-10-20",
        "currency": "USD",
        "line_items": [
            {"description": "Monthly Card Terminal Processing", "quantity": 1, "unit_price": 412.50, "amount": 412.50},
            {"description": "Receipt Paper Roll Supply Box", "quantity": 2, "unit_price": 75.00, "amount": 150.00},
        ],
        "subtotal": 562.50,
        "tax": 45.00,
        "total": 607.50,
    }
    b64_payload = "base64:" + base64.b64encode(json.dumps(structured).encode("utf-8")).decode("utf-8")
    res_b64 = extract_financial_document(ExtractDocumentRequest(raw_text=b64_payload, document_type="receipt"))
    assert res_b64.vendor == "Harbor Merchant Processing"
    assert res_b64.math_verified is True
    assert res_b64.total == 607.50


def test_extract_boundary_validation_rejects_empty_or_oversized_input():
    """
    User Journey 3: Boundary validation rejects empty strings or payloads > 250k chars.
    """
    with pytest.raises(ValueError):
        ExtractDocumentRequest(raw_text="   ", document_type="invoice")

    with pytest.raises(ValueError):
        ExtractDocumentRequest(raw_text="x" * 300_005, document_type="invoice")


# ==============================================================================
# 2. BANK STATEMENT LEDGER RECONCILIATION TESTS
# ==============================================================================

def test_reconcile_invoices_with_bank_ledger_flags_matched_unmatched_and_duplicates():
    """
    User Journey 4: Cross-matches extracted invoices against bank statement rows
    and accurately identifies matched, unmatched invoices, unmatched bank debits,
    and duplicate charges.
    """
    preset = get_preset_by_id("bank_reconciliation_batch")
    req = ReconcileLedgerRequest(
        invoices=preset["invoices"],
        bank_transactions=preset["bank_transactions"],
        date_tolerance_days=7,
        amount_tolerance=0.05,
    )
    report = reconcile_invoices_with_bank_ledger(req)

    assert len(report.matched) == 3
    assert len(report.unmatched_invoices) == 1
    assert report.unmatched_invoices[0]["invoice_number"] == "INV-2026-0912"
    assert len(report.unmatched_bank_txns) >= 1
    assert len(report.duplicate_charges) >= 1
    assert report.summary_metrics["matched_count"] == 3
    assert report.summary_metrics["duplicate_count"] >= 1
    assert report.reconciliation_balanced is False


def test_reconcile_clean_batch_marks_reconciliation_balanced():
    """When every invoice matches a single bank transaction with zero duplicates, balanced is True."""
    req = ReconcileLedgerRequest(
        invoices=[
            {
                "invoice_number": "INV-100",
                "vendor": "Linear Orbit Inc",
                "date": "2026-10-05",
                "total": 240.00,
                "currency": "USD",
            }
        ],
        bank_transactions=[
            {
                "txn_id": "TXN-01",
                "date": "2026-10-06",
                "description": "ACH DEBIT LINEAR ORBIT INC",
                "amount": 240.00,
                "currency": "USD",
            }
        ],
        date_tolerance_days=5,
        amount_tolerance=0.01,
    )
    report = reconcile_invoices_with_bank_ledger(req)
    assert len(report.matched) == 1
    assert len(report.unmatched_invoices) == 0
    assert len(report.unmatched_bank_txns) == 0
    assert len(report.duplicate_charges) == 0
    assert report.reconciliation_balanced is True


# ==============================================================================
# 3. MULTI-TAB XLSX & QUICKBOOKS CSV EXPORT TESTS
# ==============================================================================

def test_export_ledger_bundle_xlsx_contains_native_excel_sum_formulas(tmp_path: Path):
    """
    User Journey 5: Export generates a real multi-tab .xlsx workbook with native
    Excel `=SUM(...)` and `=ROUND(...)` formulas and accounting tabs.
    """
    preset = get_preset_by_id("messy_saas_invoice")
    extracted = extract_financial_document(
        ExtractDocumentRequest(raw_text=preset["raw_text"], document_type="invoice")
    )
    recon_preset = get_preset_by_id("bank_reconciliation_batch")
    recon_report = reconcile_invoices_with_bank_ledger(
        ReconcileLedgerRequest(
            invoices=recon_preset["invoices"],
            bank_transactions=recon_preset["bank_transactions"],
        )
    )

    export_req = ExportBundleRequest(
        documents=[extracted.model_dump()],
        reconciliation=recon_report.model_dump(),
        format="xlsx",
        bundle_name="october_2026_audit",
    )
    result = export_ledger_bundle(export_req, export_dir=tmp_path)

    assert result.format == "xlsx"
    assert result.filename.endswith(".xlsx")
    assert result.download_url.startswith("/downloads/")
    assert result.size_bytes > 2000
    assert "Executive_Summary" in result.sheets_included
    assert "Normalized_Line_Items" in result.sheets_included
    assert "Bank_Reconciliation" in result.sheets_included

    raw_bytes = base64.b64decode(result.base64_content)
    wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=False)
    assert set(wb.sheetnames) >= {"Executive_Summary", "Normalized_Line_Items", "Bank_Reconciliation"}

    ws_items = wb["Normalized_Line_Items"]
    formulas_found = []
    for row in ws_items.iter_rows(values_only=True):
        for cell_val in row:
            if isinstance(cell_val, str) and cell_val.startswith("="):
                formulas_found.append(cell_val)

    assert any("SUM(" in f for f in formulas_found), f"Expected =SUM() formula in workbook, got {formulas_found}"
    assert any("ROUND(" in f for f in formulas_found), f"Expected =ROUND() formula in workbook, got {formulas_found}"


def test_export_ledger_bundle_quickbooks_csv_and_path_traversal_guard(tmp_path: Path):
    """Verifies QuickBooks-compatible CSV output and strict filename sanitization."""
    preset = get_preset_by_id("messy_saas_invoice")
    extracted = extract_financial_document(
        ExtractDocumentRequest(raw_text=preset["raw_text"], document_type="invoice")
    )
    export_req = ExportBundleRequest(
        documents=[extracted.model_dump()],
        format="quickbooks_csv",
        bundle_name="../../../etc/passwd_attempt",
    )
    result = export_ledger_bundle(export_req, export_dir=tmp_path)

    assert ".." not in result.filename
    assert "/" not in result.filename
    assert result.filename.endswith(".csv")
    csv_text = base64.b64decode(result.base64_content).decode("utf-8")
    assert "Date,Description,Amount,Account,Vendor,RefNumber,Memo,MathVerified" in csv_text
    assert "Heartland Flour & Pantry Supply Co." in csv_text

    # Also test sanitize_export_filename directly
    assert sanitize_export_filename("../../secret/file..name") == "secret_file_name"


# ==============================================================================
# 4. STREAMABLE HTTP MCP ENDPOINT (`POST /mcp` & `GET /mcp`) TESTS
# ==============================================================================

def test_mcp_initialize_and_tools_list_annotations(client: TestClient):
    """
    User Journey 6: Claude Connectors Directory and ChatGPT Apps require JSON-RPC 2.0
    `initialize`, `notifications/initialized`, and `tools/list` with explicit annotations
    (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`).
    """
    # 1. GET /mcp discovery
    get_res = client.get("/mcp")
    assert get_res.status_code == 200
    assert get_res.json()["protocolVersion"] >= "2025-03-26"

    # 2. POST /mcp initialize
    init_res = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "claude-ai-connector", "version": "1.0.0"},
            },
        },
    )
    assert init_res.status_code == 200
    init_body = init_res.json()
    assert init_body["jsonrpc"] == "2.0"
    assert init_body["id"] == 1
    assert init_body["result"]["serverInfo"]["name"] == "billtally-mcp"

    # 3. POST /mcp notifications/initialized
    notif_res = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert notif_res.status_code in (200, 202)

    # 4. POST /mcp tools/list
    list_res = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert list_res.status_code == 200
    tools = list_res.json()["result"]["tools"]
    tool_names = {t["name"] for t in tools}
    assert tool_names == {
        "extract_financial_documents",
        "reconcile_invoices_with_bank_ledger",
        "export_ledger_bundle",
    }
    for tool in tools:
        annotations = tool.get("annotations", {})
        assert annotations.get("readOnlyHint") is True
        assert annotations.get("destructiveHint") is False
        assert annotations.get("idempotentHint") is True
        assert annotations.get("openWorldHint") is False
        for prop_name, prop_schema in tool["inputSchema"]["properties"].items():
            assert prop_schema.get("description"), f"Missing description on {tool['name']}.{prop_name}"


def test_mcp_tools_call_executes_all_three_tools(client: TestClient):
    """Tests `tools/call` over JSON-RPC 2.0 for all 3 MCP tools + unknown tool error."""
    preset = get_preset_by_id("messy_saas_invoice")

    # Call 1: extract_financial_documents
    call_extract = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": "call-1",
            "method": "tools/call",
            "params": {
                "name": "extract_financial_documents",
                "arguments": {
                    "raw_text": preset["raw_text"],
                    "document_type": "invoice",
                },
            },
        },
    )
    assert call_extract.status_code == 200
    res1 = call_extract.json()["result"]
    assert res1["isError"] is False
    structured1 = res1["structuredContent"]
    assert structured1["math_verified"] is True
    assert structured1["vendor"] == "Heartland Flour & Pantry Supply Co."

    # Call 2: reconcile_invoices_with_bank_ledger
    recon_preset = get_preset_by_id("bank_reconciliation_batch")
    call_recon = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": "call-2",
            "method": "tools/call",
            "params": {
                "name": "reconcile_invoices_with_bank_ledger",
                "arguments": {
                    "invoices": recon_preset["invoices"],
                    "bank_transactions": recon_preset["bank_transactions"],
                    "date_tolerance_days": 7,
                },
            },
        },
    )
    assert call_recon.status_code == 200
    res2 = call_recon.json()["result"]
    assert res2["isError"] is False
    assert res2["structuredContent"]["summary_metrics"]["matched_count"] == 3

    # Call 3: export_ledger_bundle
    call_export = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": "call-3",
            "method": "tools/call",
            "params": {
                "name": "export_ledger_bundle",
                "arguments": {
                    "documents": [structured1],
                    "reconciliation": res2["structuredContent"],
                    "format": "xlsx",
                    "bundle_name": "mcp_test_bundle",
                },
            },
        },
    )
    assert call_export.status_code == 200
    res3 = call_export.json()["result"]
    assert res3["isError"] is False
    download_url = res3["structuredContent"]["download_url"]

    # Verify the generated file is downloadable via GET /downloads/{filename}
    dl_res = client.get(download_url)
    assert dl_res.status_code == 200
    assert len(dl_res.content) > 2000

    # Call 4: Unknown tool returns JSON-RPC error or isError
    call_unknown = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": "call-err",
            "method": "tools/call",
            "params": {"name": "non_existent_tool", "arguments": {}},
        },
    )
    assert call_unknown.status_code == 200
    assert "error" in call_unknown.json()


# ==============================================================================
# 5. OAUTH 2.1 WITH S256 PKCE TESTS
# ==============================================================================

def test_oauth21_pkce_s256_complete_handshake(client: TestClient):
    """
    User Journey 7: Full OAuth 2.1 with S256 PKCE handshake for Claude & ChatGPT Connectors.
    """
    # 1. Metadata discovery
    meta_res = client.get("/.well-known/oauth-authorization-server")
    assert meta_res.status_code == 200
    meta = meta_res.json()
    assert "S256" in meta["code_challenge_methods_supported"]
    assert meta["authorization_endpoint"].endswith("/oauth/authorize")
    assert meta["token_endpoint"].endswith("/oauth/token")

    # 2. Generate PKCE verifier & S256 challenge
    code_verifier = "schemaextract_pkce_verifier_secret_string_2026_compliant_43chars"
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    # 3. Authorize request
    auth_res = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "claude-connector-client",
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": "xyz-state-991",
            "scope": "mcp:tools mcp:export",
        },
        follow_redirects=False,
    )
    assert auth_res.status_code == 200
    auth_data = auth_res.json()
    auth_code = auth_data["code"]
    assert auth_data["state"] == "xyz-state-991"

    # 4. Tampered verifier must be rejected (HTTP 400)
    bad_token_res = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": "claude-connector-client",
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "code_verifier": "wrong_verifier_value_that_does_not_match_s256_hash",
        },
    )
    assert bad_token_res.status_code == 400

    # 5. Valid verifier exchanges code for Bearer token
    good_token_res = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": "claude-connector-client",
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "code_verifier": code_verifier,
        },
    )
    assert good_token_res.status_code == 200
    token_payload = good_token_res.json()
    assert token_payload["token_type"] == "Bearer"
    assert len(token_payload["access_token"]) > 20
    assert "refresh_token" in token_payload


# ==============================================================================
# 6. FREE (15 DOCS/MO) VS PRO ($29/MO) QUOTA & WEB STUDIO / MANIFEST TESTS
# ==============================================================================

def test_quota_manager_enforces_free_15_limit_and_upgrades_to_pro():
    """
    User Journey 8: Free tier allows 15 docs/month; 16th raises quota limit error
    until upgraded to Pro tier ($29/mo) or given a valid Pro key.
    """
    qm = QuotaManager()
    workspace_id = "test-workspace-free"

    for i in range(15):
        state = qm.consume_document(workspace_id)
        assert state["tier"] == "free"
        assert state["used"] == i + 1
        assert state["remaining"] == 15 - (i + 1)

    with pytest.raises(PermissionError, match="Free tier quota exhausted"):
        qm.consume_document(workspace_id)

    # Upgrade workspace to Pro ($29/mo)
    upgraded = qm.upgrade_to_pro(workspace_id)
    assert upgraded["tier"] == "pro"
    assert upgraded["price_usd_monthly"] == 29
    assert upgraded["api_key"].startswith("se_pro_")

    # 16th document now succeeds on Pro tier
    after_pro = qm.consume_document(workspace_id, api_key=upgraded["api_key"])
    assert after_pro["tier"] == "pro"
    assert after_pro["remaining"] > 4900


def test_web_studio_and_submission_manifests(client: TestClient):
    """Verifies Interactive Web Studio (`GET /`) greeting, plain-English UI, public pages, and Claude/OpenAI manifests."""
    studio_res = client.get("/")
    assert studio_res.status_code == 200
    html = studio_res.text
    assert "BillTally" in html
    assert "Welcome to your Bill & Bank Math Check Desk" in html
    assert 'href="/about"' in html
    assert 'href="/docs"' in html
    assert 'href="/privacy"' in html
    assert 'href="/terms"' in html
    assert "extract_financial_documents" in html
    assert "reconcile_invoices_with_bank_ledger" in html
    assert "export_ledger_bundle" in html
    assert "+ Optional Step 3: Compare against monthly bank statement" in html
    assert "Jump to Disputed Line" in html
    assert "billed-strike" in html
    assert "active-sample-pill" in html
    assert "line-counter-badge" in html
    assert "Download 3-Tab Excel (.xlsx)" in html
    assert "Copy Supplier Dispute Email" in html

    # Verify /about, /docs, /documentation, /privacy, /terms HTML pages
    about_res = client.get("/about")
    assert about_res.status_code == 200
    assert "Kader Mula" in about_res.text
    assert "mulak1@gmail.com" in about_res.text

    docs_res = client.get("/docs")
    assert docs_res.status_code == 200
    assert "User &amp; IT Administrator Documentation" in docs_res.text
    assert "Read-Only" in docs_res.text

    doc_alias_res = client.get("/documentation")
    assert doc_alias_res.status_code == 200

    # Verify /analytics, /api/analytics, and /chatgpt-openapi.json
    analytics_html = client.get("/analytics")
    assert analytics_html.status_code == 200
    assert "BillTally Live Analytics" in analytics_html.text

    analytics_json = client.get("/api/analytics")
    assert analytics_json.status_code == 200
    assert analytics_json.json()["service"] == "BillTally"
    assert "by_source" in analytics_json.json()

    openapi_res = client.get("/chatgpt-openapi.json")
    assert openapi_res.status_code == 200
    openapi_data = openapi_res.json()
    assert openapi_data["openapi"] == "3.1.0"
    for path_item in openapi_data["paths"].values():
        assert "content" in path_item["post"]["responses"]["200"]

    # Verify OpenAI domain verification challenge & plugin zip download
    set_chal = client.post("/api/admin/openai-challenge", json={"token": "openai-verify-billtally-123"})
    assert set_chal.status_code == 200
    get_chal = client.get("/.well-known/openai-apps-challenge")
    assert get_chal.status_code == 200
    assert get_chal.text == "openai-verify-billtally-123"
    client.post("/api/admin/openai-challenge", json={"token": "YFsHN-fut-TBj-AukzfY5eO_uhEp47qd-ApSrLkjdPg"})

    zip_res = client.get("/openai-plugin.zip")
    assert zip_res.status_code == 200
    assert len(zip_res.content) > 1000

    # Verify REST API endpoints used by Web Studio
    presets_res = client.get("/api/presets")
    assert presets_res.status_code == 200
    assert len(presets_res.json()["presets"]) == 3

    claude_manifest_res = client.get("/manifests/claude")
    assert claude_manifest_res.status_code == 200
    assert claude_manifest_res.json()["name"] == "BillTally"
    assert "sample_prompts" in claude_manifest_res.json()

    openai_manifest_res = client.get("/manifests/openai")
    assert openai_manifest_res.status_code == 200
    assert "mcp_endpoints" in openai_manifest_res.json()
    assert "conversation_starters" in openai_manifest_res.json()

    # Verify /privacy, /terms, and /oauth/register
    priv_res = client.get("/privacy")
    assert priv_res.status_code == 200
    assert "trains_on_customer_data: false" in priv_res.text

    terms_res = client.get("/terms")
    assert terms_res.status_code == 200
    assert "pro_price_usd_monthly: 29" in terms_res.text

    reg_res = client.post("/oauth/register", json={"client_name": "Claude Connector Test"})
    assert reg_res.status_code == 201
    assert reg_res.json()["client_id"].startswith("se_client_")


def test_rest_api_endpoints_and_mcp_batch_and_standard_csv(client: TestClient):
    """Covers REST API endpoints (`/health`, `/api/extract`, `/api/reconcile`, `/api/export`, `/api/quota`) and MCP batch/ping."""
    # Health check
    health_res = client.get("/health")
    assert health_res.status_code == 200
    assert health_res.json()["status"] == "ok"

    # Quota status & upgrade via REST
    q_res = client.get("/api/quota?workspace_id=rest-ws")
    assert q_res.status_code == 200
    assert q_res.json()["tier"] == "free"

    up_res = client.post("/api/quota/upgrade?workspace_id=rest-ws")
    assert up_res.status_code == 200
    assert up_res.json()["tier"] == "pro"

    # Inline pattern extraction (`1. Item 2 x $150.00 = $300.00`) via REST `/api/extract`
    inline_doc = (
        "Vendor: Inline Cloud Co\n"
        "Invoice #: INL-2026-09\n"
        "Date: 2026-10-12\n"
        "1. Dedicated Worker Nodes 2 x $150.00 = $300.00\n"
        "2. Load Balancer Tier 1 x $75.00 = $75.00\n"
        "Subtotal: $375.00\n"
        "Tax: $25.00\n"
        "Total: $400.00\n"
    )
    ext_res = client.post(
        "/api/extract",
        json={"raw_text": inline_doc, "document_type": "invoice", "workspace_id": "rest-ws"},
    )
    assert ext_res.status_code == 200
    ext_data = ext_res.json()
    assert ext_data["math_verified"] is True
    assert ext_data["total"] == 400.00

    # REST `/api/reconcile`
    preset = get_preset_by_id("bank_reconciliation_batch")
    rec_res = client.post(
        "/api/reconcile",
        json={
            "invoices": preset["invoices"],
            "bank_transactions": preset["bank_transactions"],
        },
    )
    assert rec_res.status_code == 200
    assert rec_res.json()["summary_metrics"]["matched_count"] == 3

    # REST `/api/export` with standard `csv` format
    exp_res = client.post(
        "/api/export",
        json={
            "documents": [ext_data],
            "format": "csv",
            "bundle_name": "standard_csv_bundle",
        },
    )
    assert exp_res.status_code == 200
    assert exp_res.json()["format"] == "csv"

    # MCP batch JSON-RPC (`ping`, `resources/list`, `prompts/list`, unknown method)
    batch_res = client.post(
        "/mcp",
        json=[
            {"jsonrpc": "2.0", "id": 10, "method": "ping"},
            {"jsonrpc": "2.0", "id": 11, "method": "resources/list"},
            {"jsonrpc": "2.0", "id": 12, "method": "prompts/list"},
            {"jsonrpc": "2.0", "id": 13, "method": "unknown/method"},
        ],
    )
    assert batch_res.status_code == 200
    batch_items = batch_res.json()
    assert len(batch_items) == 4
    assert batch_items[0]["result"] == {}
    assert "error" in batch_items[3]


def test_p0_intelligence_upgrades_and_cold_call_coercion(client: TestClient, tmp_path: Path):
    """Verifies P0 duplicate detector, >12% tax warning, Audit_Memo export, and LLM alias coercion."""
    dup_and_high_tax_bill = (
        "Vendor: Metro Restaurant Supply\nInvoice #: MRS-2026-991\nDate: 2026-10-15\n"
        "1. Stainless Prep Table | Qty: 1 | Unit Price: $500.00 | Amount: $500.00\n"
        "2. Stainless Prep Table | Qty: 1 | Unit Price: $500.00 | Amount: $500.00\n"
        "Subtotal: $1,000.00\nTax: $150.00\nTotal: $1,150.00\n"
    )
    mcp_ext = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 901, "method": "tools/call", "params": {"name": "extract_financial_documents", "arguments": {"invoice_text": dup_and_high_tax_bill}}},
    )
    assert mcp_ext.status_code == 200
    ext_sc = mcp_ext.json()["result"]["structuredContent"]
    assert ext_sc["duplicate_line_items_count"] == 1
    assert "Potential duplicate line item" in (ext_sc["duplicate_line_items_warning"] or "")
    assert ext_sc["effective_tax_rate_pct"] == 15.0
    assert "High effective tax rate" in (ext_sc["high_tax_rate_warning"] or "")

    preset = get_preset_by_id("bank_reconciliation_batch")
    mcp_rec = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 902, "method": "tools/call", "params": {"name": "reconcile_invoices_with_bank_ledger", "arguments": {"bills": preset["invoices"], "transactions": preset["bank_transactions"]}}},
    )
    assert mcp_rec.status_code == 200
    assert mcp_rec.json()["result"]["isError"] is False

    discrepant_doc = extract_financial_document(ExtractDocumentRequest(raw_text=get_preset_by_id("discrepant_contractor_invoice")["raw_text"])).model_dump()
    mcp_exp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 903, "method": "tools/call", "params": {"name": "export_ledger_bundle", "arguments": {"document": discrepant_doc, "format": "quickbooks_csv", "use_corrected_amounts": True}}},
    )
    assert mcp_exp.status_code == 200
    qb_csv = base64.b64decode(mcp_exp.json()["result"]["structuredContent"]["base64_content"]).decode("utf-8")
    assert "Audit_Memo" in qb_csv
    assert "Short-Pay Adjusted: Billed $6705.30 vs True Math $6505.30 (Saved $200.00 on disputed line items)" in qb_csv

    studio_html = client.get("/").text
    assert "copyVerifiedSummary()" in studio_html
    assert "Check bill math to the penny (⌘↵)" in studio_html
    assert "@media print" in studio_html
    assert "not certified public accounting (CPA) or tax advice" in studio_html


