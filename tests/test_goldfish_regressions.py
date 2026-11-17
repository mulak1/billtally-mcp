"""
tests/test_goldfish_regressions.py
Comprehensive security, financial math, OAuth 2.1, CSP/XSS, XFF isolation,
XLSX/CSV DDE formula neutralization, and Stripe telemetry integrity regression tests
for BillTally / SchemaExtract MCP (`GF-R1-01`..`GF-R1-16` + Test Plan Reviewer P0-P2).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import re
import subprocess
import time
from unittest.mock import patch

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.analytics import _COUNTERS
from app.exporter import _EPHEMERAL_EXPORTS, export_ledger_bundle
from app.extractor import extract_financial_document
from app.main import app, oauth_server, quota_manager
from app.mcp_server import handle_mcp_jsonrpc
from app.models import ExportBundleRequest, ExtractDocumentRequest, ReconcileLedgerRequest
from app.oauth_quota import compute_s256_challenge, resolve_request_workspace
from app.reconciler import reconcile_invoices_with_bank_ledger
from app.stripe_verify import verify_paid_stripe_checkout_session, verify_stripe_webhook_signature


@pytest.fixture(autouse=True)
def _reset_billtally_singletons():
    yield
    _EPHEMERAL_EXPORTS.clear()
    quota_manager._redeemed_sessions.clear()
    quota_manager._ip_free_counts.clear()
    oauth_server._ip_registrations.clear()


def test_pro_key_wildcard_and_demo_key_rejected_on_prod_host():
    assert quota_manager.is_valid_pro_key("se_pro_arbitrary_forged_99999999", is_prod=True) is False
    assert quota_manager.is_valid_pro_key("se_pro_demo_2026_unlimited", is_prod=True) is False
    assert quota_manager.is_valid_pro_key("se_pro_demo_2026_unlimited", is_prod=False) is True

    upgraded = quota_manager.upgrade_to_pro("ws_customer_paid")
    minted = upgraded["api_key"]
    assert quota_manager.is_valid_pro_key(minted, is_prod=True) is True
    assert quota_manager.is_valid_pro_key(minted[:-2] + "ff", is_prod=True) is False


def test_spoofed_stripe_return_and_query_param_never_mint_pro_or_log_paid():
    client = TestClient(app, base_url="https://billtally.app")
    before_paid = _COUNTERS["pro_unlocks"]

    r_get = client.get("/?pro_activated=1")
    assert r_get.status_code == 200
    assert _COUNTERS["pro_unlocks"] == before_paid

    r_spoof = client.post(
        "/api/quota/upgrade?workspace_id=ws_attacker",
        headers={"X-Stripe-Return": "1", "X-Forwarded-Proto": "https"},
        json={},
    )
    assert r_spoof.status_code == 403
    assert _COUNTERS["pro_unlocks"] == before_paid


def test_stripe_webhook_hmac_replay_window_and_single_use_session_redemption(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_unit_test_secret_99")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_mock_99")
    client = TestClient(app, base_url="https://billtally.app")

    ts = int(time.time())
    payload_bytes = json.dumps({
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_webhook_paid_001",
                "payment_status": "paid",
                "amount_total": 4999,
                "client_reference_id": "ws_wh_buyer",
            }
        },
    }).encode("utf-8")
    good_sig = hmac.new(
        b"whsec_unit_test_secret_99",
        f"{ts}.".encode("utf-8") + payload_bytes,
        hashlib.sha256,
    ).hexdigest()

    assert verify_stripe_webhook_signature(payload_bytes, f"t={ts},v1=oldsig,v1={good_sig}", "whsec_unit_test_secret_99") is True
    assert verify_stripe_webhook_signature(payload_bytes, f"t={ts - 301},v1={good_sig}", "whsec_unit_test_secret_99") is False
    assert verify_stripe_webhook_signature(payload_bytes, "t=notadigit,v1=abc", "whsec_unit_test_secret_99") is False
    assert verify_paid_stripe_checkout_session("not_cs_prefix") is False

    wh_bad = client.post(
        "/webhooks/stripe",
        content=payload_bytes,
        headers={"Stripe-Signature": f"t={ts},v1=bad", "Content-Type": "application/json"},
    )
    assert wh_bad.status_code == 400

    wh_ok = client.post(
        "/webhooks/stripe",
        content=payload_bytes,
        headers={"Stripe-Signature": f"t={ts},v1={good_sig}", "Content-Type": "application/json"},
    )
    assert wh_ok.status_code == 200
    assert quota_manager.get_status("ws_wh_buyer")["tier"] == "pro"

    with patch("app.main._verify_paid_stripe_checkout_session", return_value=True):
        act1 = client.post(
            "/api/quota/upgrade?workspace_id=ws_once_1",
            headers={"X-Forwarded-Proto": "https"},
            json={"checkout_session_id": "cs_test_once_777"},
        )
        assert act1.status_code == 200
        assert act1.json()["tier"] == "pro"

        # Replaying the same Stripe Checkout session_id MUST fail closed with 403
        act2 = client.post(
            "/api/quota/upgrade?workspace_id=ws_once_2",
            headers={"X-Forwarded-Proto": "https"},
            json={"checkout_session_id": "cs_test_once_777"},
        )
        assert act2.status_code == 403


def test_studio_csp_nonce_zero_inline_handlers_and_js_syntax():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    csp = resp.headers.get("Content-Security-Policy", "")

    nonce_match = re.search(r"'nonce-([A-Za-z0-9_-]+)'", csp)
    assert nonce_match is not None, f"Missing script nonce in CSP: {csp}"
    nonce = nonce_match.group(1)
    assert "'unsafe-inline'" not in csp.split("style-src")[0]
    assert f'<script nonce="{nonce}">' in html
    assert re.search(r"\bon(?:click|change|blur|submit|keyup|keydown)\s*=", html, re.I) is None

    script_match = re.search(r'<script nonce="[^"]+">([\s\S]*?)</script>', html)
    assert script_match is not None
    proc = subprocess.run(["node", "--check"], input=script_match.group(1), capture_output=True, text=True)
    assert proc.returncode == 0, f"Inline studio JS syntax error: {proc.stderr}"


def test_subcent_unit_price_zero_subtotal_malformed_input_and_strict_reconciliation():
    structured_subcent = json.dumps({
        "vendor": "Usage Cloud",
        "invoice_number": "UC-99",
        "line_items": [
            {"description": "API Calls", "quantity": 1000, "unit_price": "0.1235", "amount": "123.50"},
            {"description": "Volume Credit", "quantity": 1, "unit_price": "-23.50", "amount": "-23.50"},
        ],
        "subtotal": "100.00",
        "tax": "0.00",
        "total": "100.00",
    })
    doc = extract_financial_document(ExtractDocumentRequest(raw_text=structured_subcent))
    assert doc.computed_subtotal == 100.00
    assert doc.discrepancy_delta == 0.00
    assert doc.math_verified is True

    # Zero-subtotal invoice does not divide-by-zero on effective_tax_rate_pct, and 0-line bill yields 0.55 confidence
    zero_doc = extract_financial_document(ExtractDocumentRequest(raw_text="Vendor: Zero Corp\nInvoice #: Z-1\nTotal: $0.00"))
    assert zero_doc.effective_tax_rate_pct == 0.0
    assert zero_doc.confidence_score == 0.55

    # Malformed currency strings like "$--" degrade safely without Decimal InvalidOperation crash
    messy_curr = json.dumps({
        "vendor": "Messy Vendor",
        "invoice_number": "MV-1",
        "line_items": [{"description": "Item", "quantity": 1, "unit_price": "$--", "amount": "0.00"}],
        "subtotal": "$--",
        "tax": "1.2.3",
        "total": "0.00",
    })
    messy_res = extract_financial_document(ExtractDocumentRequest(raw_text=messy_curr))
    assert messy_res.total == 0.0

    penny_json = json.dumps({
        "vendor": "Penny Co",
        "invoice_number": "PN-1",
        "line_items": [{"description": "Service", "quantity": 1, "unit_price": "10.00", "amount": "10.00"}],
        "subtotal": "10.00",
        "tax": "0.00",
        "total": "10.01",
    })
    loose = extract_financial_document(ExtractDocumentRequest(raw_text=penny_json, strict_reconciliation=False))
    strict = extract_financial_document(ExtractDocumentRequest(raw_text=penny_json, strict_reconciliation=True))
    assert loose.math_verified is True
    assert strict.math_verified is False

    # Failed validation MUST NOT burn workspace quota
    ws_id = f"ws_no_burn_{int(time.time() * 1000)}"
    before_used = quota_manager.get_status(ws_id)["used"]
    rpc_err, _status = handle_mcp_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 91,
            "method": "tools/call",
            "params": {"name": "extract_financial_documents", "arguments": {"raw_text": "   "}},
        },
        quota_manager,
        default_workspace_id=ws_id,
    )
    assert "error" in rpc_err or rpc_err.get("result", {}).get("isError") is True
    assert quota_manager.get_status(ws_id)["used"] == before_used


def test_decimal_reconciler_exact_boundary_and_currency_mismatch():
    res_ok = reconcile_invoices_with_bank_ledger(
        ReconcileLedgerRequest(
            invoices=[{"invoice_number": "INV-1", "vendor": "Acme", "total": "100.10", "currency": "USD", "issue_date": "2026-11-01"}],
            bank_transactions=[{"id": "BNK-1", "description": "Acme Payout", "amount": "-100.15", "currency": "USD", "date": "2026-11-02"}],
            amount_tolerance=0.05,
        )
    )
    assert len(res_ok.matched) == 1

    res_cur = reconcile_invoices_with_bank_ledger(
        ReconcileLedgerRequest(
            invoices=[{"invoice_number": "INV-2", "vendor": "EuroVendor", "total": "100.00", "currency": "EUR", "issue_date": "2026-11-01"}],
            bank_transactions=[{"id": "BNK-2", "description": "EuroVendor", "amount": "-100.00", "currency": "USD", "date": "2026-11-01"}],
            amount_tolerance=0.05,
        )
    )
    assert len(res_cur.matched) == 0
    assert len(res_cur.unmatched_invoices) == 1


def test_oauth_expiry_code_replay_refresh_rotation_redirect_guard_and_xff_isolation():
    with pytest.raises(ValueError):
        oauth_server.register_client("Evil App", ["javascript:alert(1)"])
    with pytest.raises(ValueError):
        oauth_server.register_client("Insecure HTTP", ["http://evil.example.com/cb"])

    client_meta = oauth_server.register_client("Good App", ["https://chatgpt.com/aip/callback"])
    cid = client_meta["client_id"]

    verifier = "pkce_verifier_secret_string_1234567890"
    challenge = compute_s256_challenge(verifier)

    with pytest.raises(ValueError):
        oauth_server.issue_authorization_code(
            response_type="code",
            client_id=cid,
            redirect_uri="https://evil.example.com/steal",
            code_challenge=challenge,
        )

    issued1 = oauth_server.issue_authorization_code(
        response_type="code",
        client_id=cid,
        redirect_uri="https://chatgpt.com/aip/callback",
        code_challenge=challenge,
    )
    oauth_server._auth_codes[issued1["code"]]["expires_at"] = int(time.time()) - 5
    with pytest.raises(ValueError):
        oauth_server.exchange_code_for_token(
            grant_type="authorization_code",
            code=issued1["code"],
            client_id=cid,
            redirect_uri="https://chatgpt.com/aip/callback",
            code_verifier=verifier,
        )

    issued2 = oauth_server.issue_authorization_code(
        response_type="code",
        client_id=cid,
        redirect_uri="https://chatgpt.com/aip/callback",
        code_challenge=challenge,
    )
    tok1 = oauth_server.exchange_code_for_token(
        grant_type="authorization_code",
        code=issued2["code"],
        client_id=cid,
        redirect_uri="https://chatgpt.com/aip/callback",
        code_verifier=verifier,
    )
    # Replaying an already-redeemed auth code MUST fail
    with pytest.raises(ValueError):
        oauth_server.exchange_code_for_token(
            grant_type="authorization_code",
            code=issued2["code"],
            client_id=cid,
            redirect_uri="https://chatgpt.com/aip/callback",
            code_verifier=verifier,
        )

    old_rt = tok1["refresh_token"]
    tok2 = oauth_server.exchange_code_for_token(
        grant_type="refresh_token",
        refresh_token=old_rt,
        client_id=cid,
    )
    assert tok2["access_token"] != tok1["access_token"]
    with pytest.raises(ValueError):
        oauth_server.exchange_code_for_token(
            grant_type="refresh_token",
            refresh_token=old_rt,
            client_id=cid,
        )

    # Prod HTTPS ignores spoofed left X-Forwarded-For hop AND ignores unauthenticated victim workspace_id
    prod_client = TestClient(app, base_url="https://billtally.app")
    r1 = prod_client.get(
        "/api/quota?workspace_id=victim-ws",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "10.0.0.1, 203.0.113.9"},
    )
    r2 = prod_client.get(
        "/api/quota?workspace_id=other-victim",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "192.168.1.9, 203.0.113.9"},
    )
    assert r1.json()["workspace_id"] != "victim-ws"
    assert r1.json()["workspace_id"] == r2.json()["workspace_id"]

    # Prod well-known OAuth returns 404 unless ?oauth=1
    assert prod_client.get("/.well-known/oauth-authorization-server", headers={"X-Forwarded-Proto": "https"}).status_code == 404
    assert prod_client.get("/.well-known/oauth-authorization-server?oauth=1", headers={"X-Forwarded-Proto": "https"}).status_code == 200


def test_ephemeral_download_underbilled_memo_and_xlsx_csv_dde_sanitization():
    underbilled_doc = {
        "invoice_number": "=CMD|' /C calc'!A0",
        "vendor": "+SUM(A1:A2)",
        "issue_date": "2026-11-10",
        "currency": "USD",
        "math_verified": False,
        "discrepancy_delta": -10.00,  # Under-billed (vendor billed $90 instead of $100)
        "subtotal": 90.00,
        "computed_subtotal": 100.00,
        "tax": 0.00,
        "total": 90.00,
        "computed_total": 100.00,
        "line_items": [
            {"line_number": 1, "description": "@EVIL_MACRO()", "quantity": 2, "unit_price": 50.00, "amount": 90.00, "expected_amount": 100.00}
        ],
    }

    csv_bundle = export_ledger_bundle(
        ExportBundleRequest(documents=[underbilled_doc], format="csv", bundle_name="audit_export", use_corrected_amounts=True)
    )
    csv_decoded = base64.b64decode(csv_bundle.base64_content).decode("utf-8")
    assert "'=CMD|' /C calc'!A0" in csv_decoded
    assert "'+SUM(A1:A2)" in csv_decoded
    assert "'@EVIL_MACRO()" in csv_decoded
    assert "True-Math Adjusted" in csv_decoded
    assert "Overcharge Removed" not in csv_decoded
    assert re.search(r"_[0-9a-f]{24}\.csv$", csv_bundle.download_url) is not None

    xlsx_bundle = export_ledger_bundle(
        ExportBundleRequest(documents=[underbilled_doc], format="xlsx", bundle_name="audit_xlsx", use_corrected_amounts=False)
    )
    wb = openpyxl.load_workbook(io.BytesIO(base64.b64decode(xlsx_bundle.base64_content)), data_only=False)
    ws_summary = wb["Executive_Summary"]
    summary_text = " ".join(str(cell.value or "") for row in ws_summary.iter_rows() for cell in row)
    assert "'+SUM(A1:A2)" in summary_text
    assert "Under-Billing Flagged" in summary_text

    client = TestClient(app)
    dl_resp = client.get(csv_bundle.download_url)
    assert dl_resp.status_code == 200
    assert "'+SUM(A1:A2)" in dl_resp.text


def test_streaming_body_cap_and_malformed_content_length():
    client = TestClient(app)
    bad_cl = client.post("/api/extract", content="{}", headers={"Content-Type": "application/json", "Content-Length": "NaN"})
    assert bad_cl.status_code == 400

    oversized = "x" * 5_000_100
    resp = client.post("/api/extract", content=oversized, headers={"Content-Type": "application/json"})
    assert resp.status_code == 413
