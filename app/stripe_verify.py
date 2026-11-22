"""
Stripe Checkout Session & Webhook HMAC-SHA256 verification helpers for BillTally Pro.
"""

import hashlib
import hmac
import json
import os
import ssl
import time
from typing import Dict
from urllib.parse import quote
import urllib.request


def verify_paid_stripe_checkout_session(session_id: str) -> bool:
    """Verify a Stripe Checkout Session (`cs_...`) upstream via Stripe REST API using STRIPE_SECRET_KEY."""
    sid = (session_id or "").strip()
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not sid.startswith("cs_") or len(sid) > 128 or not stripe_key:
        return False
    url = f"https://api.stripe.com/v1/checkout/sessions/{quote(sid, safe='')}"
    req = urllib.request.Request(url, method="GET", headers={"Authorization": f"Bearer {stripe_key}"})
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8"))
            amount_total = int(data.get("amount_total") or 0)
            currency = str(data.get("currency") or "").lower()
            status = str(data.get("status") or "").lower()
            return (
                data.get("payment_status") == "paid"
                and data.get("id") == sid
                and status == "complete"
                and currency == "usd"
                and amount_total >= 4999
            )
    except Exception:
        return False


def verify_stripe_webhook_signature(raw_body: bytes, sig_header: str, secret: str) -> bool:
    """Verify Stripe `Stripe-Signature` header (`t=...,v1=...`) within a 300-second replay window."""
    if not sig_header or not secret:
        return False
    parts: Dict[str, str] = {}
    sigs = []
    for item in sig_header.split(","):
        if "=" in item:
            k, v = item.strip().split("=", 1)
            if k == "v1":
                sigs.append(v)
            else:
                parts[k] = v
    ts_str = parts.get("t", "")
    if not ts_str.isdigit() or not sigs:
        return False
    if abs(int(time.time()) - int(ts_str)) > 300:
        return False
    signed_payload = ts_str.encode("utf-8") + b"." + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)
