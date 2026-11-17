"""
tests/test_goldfish_r2_regressions.py
Round-2 Goldfish regression tests for BillTally (`GF-R2-01`..`GF-R2-03` + Nits):
- Two-stage Stripe webhook -> browser redirect claim without race lockout, with replay block & zero double-counted `pro_unlocks`.
- Public `/api/analytics` zero token / Pro key / invoice number leakage.
- OAuth `refresh_token` rotation quota continuity, side-effect-free `GET /api/quota`, UA-invariant IP bucket, and 60-doc monthly IP cap.
- Accounting parentheses `($400.00)` / trailing minus `50.00-` and JSON-RPC batch `[]` (`400`) / notification (`202`).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.analytics import _COUNTERS
from app.exporter import _EPHEMERAL_EXPORTS
from app.extractor import extract_financial_document
from app.main import app, oauth_server, quota_manager
from app.models import ExtractDocumentRequest
from app.oauth_quota import compute_s256_challenge


@pytest.fixture(autouse=True)
def _reset_r2_singletons():
    yield
    _EPHEMERAL_EXPORTS.clear()
    quota_manager._redeemed_sessions.clear()
    quota_manager._ip_free_counts.clear()
    oauth_server._ip_registrations.clear()


def test_r2_webhook_then_browser_claim_succeeds_once_and_analytics_scrubs_tokens(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_r2_race_secret")
    client = TestClient(app, base_url="https://billtally.app")

    ts = int(time.time())
    bad_json = b"{not-valid-json"
    bad_sig = hmac.new(b"whsec_r2_race_secret", f"{ts}.".encode() + bad_json, hashlib.sha256).hexdigest()
    r_malformed = client.post("/webhooks/stripe", content=bad_json, headers={"Stripe-Signature": f"t={ts},v1={bad_sig}"})
    assert r_malformed.status_code == 400

    before_unlocks = _COUNTERS["pro_unlocks"]
    wh_payload = json.dumps({
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_live_race_9001", "payment_status": "paid", "amount_total": 4999}},
    }).encode("utf-8")
    wh_sig = hmac.new(b"whsec_r2_race_secret", f"{ts}.".encode() + wh_payload, hashlib.sha256).hexdigest()
    r_wh = client.post("/webhooks/stripe", content=wh_payload, headers={"Stripe-Signature": f"t={ts},v1={wh_sig}"})
    assert r_wh.status_code == 200
    assert _COUNTERS["pro_unlocks"] == before_unlocks + 1

    with patch("app.main._verify_paid_stripe_checkout_session", return_value=True):
        r_claim = client.post(
            "/api/quota/upgrade",
            headers={"X-Forwarded-For": "198.51.100.42"},
            json={"checkout_session_id": "cs_live_race_9001"},
        )
        assert r_claim.status_code == 200
        claimed_key = r_claim.json()["api_key"]
        assert quota_manager.is_valid_pro_key(claimed_key, is_prod=True) is True
        assert _COUNTERS["pro_unlocks"] == before_unlocks + 1

        r_replay = client.post(
            "/api/quota/upgrade",
            headers={"X-Forwarded-For": "198.51.100.99"},
            json={"checkout_session_id": "cs_live_race_9001"},
        )
        assert r_replay.status_code == 403

    exp_res = client.post(
        "/api/export",
        json={"documents": [{"vendor": "Acme", "invoice_number": "SECRET-INV-7788", "line_items": [{"description": "Part", "quantity": 1, "unit_price": 10, "amount": 10}]}], "format": "csv"},
    ).json()
    secret_token_match = re.search(r"_([0-9a-f]{24})\.csv$", exp_res["download_url"])
    assert secret_token_match is not None
    secret_hex = secret_token_match.group(1)
    assert client.get(exp_res["download_url"]).status_code == 200
    client.post("/api/extract", json={"raw_text": "Vendor: Acme\nInvoice #: SECRET-INV-7788\nTotal: $10.00"})

    analytics_blob = json.dumps(client.get("/api/analytics").json())
    assert secret_hex not in analytics_blob
    assert "SECRET-INV-7788" not in analytics_blob
    assert claimed_key not in analytics_blob


def test_r2_oauth_refresh_quota_continuity_ip_ceiling_and_accounting_negatives():
    prod_client = TestClient(app, base_url="https://billtally.app")

    paid_ws = quota_manager.upgrade_to_pro("ws_protected_pro")
    free_before = len(quota_manager._free_workspaces)
    for i in range(20):
        prod_client.get("/api/quota", headers={"X-Forwarded-For": f"198.51.100.{i + 1}"})
    assert len(quota_manager._free_workspaces) == free_before
    assert quota_manager.get_status("ws_protected_pro", api_key=paid_ws["api_key"], is_prod=True)["tier"] == "pro"

    ws_ua1 = prod_client.get("/api/quota", headers={"X-Forwarded-For": "203.0.113.77", "User-Agent": "ChatGPT/1.0"}).json()["workspace_id"]
    ws_ua2 = prod_client.get("/api/quota", headers={"X-Forwarded-For": "203.0.113.77", "User-Agent": "Mozilla/5.0"}).json()["workspace_id"]
    assert ws_ua1 == ws_ua2

    reg = oauth_server.register_client("Claude Connector", ["https://claude.ai/api/mcp/auth_callback"])
    verifier = "pkce_verifier_secret_string_9876543210"
    code_res = oauth_server.issue_authorization_code(
        response_type="code",
        client_id=reg["client_id"],
        redirect_uri="https://claude.ai/api/mcp/auth_callback",
        code_challenge=compute_s256_challenge(verifier),
    )
    tok_a = oauth_server.exchange_code_for_token(
        grant_type="authorization_code",
        code=code_res["code"],
        client_id=reg["client_id"],
        redirect_uri="https://claude.ai/api/mcp/auth_callback",
        code_verifier=verifier,
    )
    r_use1 = prod_client.post(
        "/api/extract",
        headers={"Authorization": f"Bearer {tok_a['access_token']}", "X-Forwarded-For": "203.0.113.88"},
        json={"raw_text": "Vendor: One\nInvoice #: 1\nTotal: $5.00"},
    )
    assert r_use1.status_code == 200 and r_use1.json()["quota_state"]["used"] == 1
    tok_b = oauth_server.exchange_code_for_token(
        grant_type="refresh_token",
        refresh_token=tok_a["refresh_token"],
        client_id=reg["client_id"],
    )
    r_use2 = prod_client.post(
        "/api/extract",
        headers={"Authorization": f"Bearer {tok_b['access_token']}", "X-Forwarded-For": "203.0.113.88"},
        json={"raw_text": "Vendor: One\nInvoice #: 2\nTotal: $5.00"},
    )
    assert r_use2.status_code == 200 and r_use2.json()["quota_state"]["used"] == 2

    month_tag = time.strftime("%Y-%m", time.gmtime())
    quota_manager._ip_free_counts[f"203.0.113.200:{month_tag}"] = 60
    r_blocked = prod_client.post(
        "/api/extract",
        headers={"X-Forwarded-For": "203.0.113.200", "OpenAI-Ephemeral-User-Id": f"spoof-{time.time()}"},
        json={"raw_text": "Vendor: Flood\nInvoice #: 9\nTotal: $5.00"},
    )
    assert r_blocked.status_code == 402

    acct_json = json.dumps({
        "vendor": "Credit Memo Co",
        "invoice_number": "CM-1",
        "line_items": [
            {"description": "Charge", "quantity": 1, "unit_price": "500.00", "amount": "500.00"},
            {"description": "Paren Credit", "quantity": 1, "unit_price": "($400.00)", "amount": "($400.00)"},
            {"description": "Trailing Credit", "quantity": 1, "unit_price": "50.00-", "amount": "50.00-"},
        ],
        "subtotal": "50.00",
        "tax": "0.00",
        "total": "50.00",
    })
    parsed_cm = extract_financial_document(ExtractDocumentRequest(raw_text=acct_json))
    assert parsed_cm.math_verified is True and parsed_cm.computed_total == 50.00
    assert prod_client.post("/mcp", json=[]).status_code == 400
    assert prod_client.post("/mcp", json=[{"jsonrpc": "2.0", "method": "notifications/initialized"}]).status_code == 202
