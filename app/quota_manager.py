"""
Free Tier (15 docs/mo) vs Pro Tier Quota Manager for BillTally (`schemaextract-mcp`).
Separates `_pro_workspaces` from `_free_workspaces`, keeps `get_status()` side-effect-free,
enforces a monthly non-loopback IP free ceiling, and coordinates two-stage Stripe session redemption.
"""

from collections import OrderedDict
import copy
import hashlib
import hmac
import os
import secrets
import threading
import time
from typing import Any, Dict, Optional, Tuple

FREE_MONTHLY_LIMIT = 15
FREE_EXPORT_LIMIT = 3
PRO_MONTHLY_LIMIT = 5000
MAX_FREE_DOCS_PER_IP_MONTHLY = 60
MAX_FREE_EXPORTS_PER_IP_MONTHLY = 12
PRO_PRICE_USD = 29
PRO_STRIPE_PASS_USD = 49.99
STRIPE_UPGRADE_URL = "https://buy.stripe.com/bJedR9cK12BN90903MfAc01"
CHECK2QBO_COMPANION_URL = "https://exactbaseline.com/qbo-check-reconcile"
MAX_WORKSPACES = 4096
LOCAL_IPS = ("", "local", "testclient", "127.0.0.1", "localhost", "::1")


def bounded_put(store: "OrderedDict[str, Any]", key: str, value: Any, max_len: int) -> None:
    if key in store:
        store.move_to_end(key)
    store[key] = value
    while len(store) > max_len:
        store.popitem(last=False)


class QuotaManager:
    """Manages Free Tier (15 docs/mo) vs Pro Tier usage with isolated Pro/Free stores and 2-stage Stripe claim."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ephemeral_secret = secrets.token_bytes(32)
        self._free_workspaces: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._pro_workspaces: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._pro_keys: "OrderedDict[str, str]" = OrderedDict()
        self._redeemed_sessions: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._ip_free_counts: "OrderedDict[str, int]" = OrderedDict()
        self._ip_free_export_counts: "OrderedDict[str, int]" = OrderedDict()
        self._free_export_counts: "OrderedDict[str, int]" = OrderedDict()

    def _sign_pro_key(self, raw_token: str) -> str:
        secret = os.environ.get("ADMIN_API_SECRET", "").strip()
        if not secret:
            return f"se_pro_{raw_token}"
        sig = hmac.new(secret.encode("utf-8"), raw_token.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
        return f"se_pro_{raw_token}_{sig}"

    def _session_pro_key(self, session_id: str) -> str:
        """Derive a keyed HMAC key per Stripe session so post-restart replay cannot mint new distinct keys."""
        secret = os.environ.get("ADMIN_API_SECRET", "").strip()
        key_bytes = secret.encode("utf-8") if secret else self._ephemeral_secret
        raw_token = hmac.new(key_bytes, f"session:{session_id}".encode("utf-8"), hashlib.sha256).hexdigest()[:24]
        return self._sign_pro_key(raw_token)

    def is_valid_pro_key(self, api_key: Optional[str], *, is_prod: bool = False) -> bool:
        if not isinstance(api_key, str):
            return False
        key = api_key.strip()
        if not key:
            return False
        with self._lock:
            for issued_key in self._pro_keys:
                if hmac.compare_digest(key, issued_key):
                    return True
        if not is_prod and hmac.compare_digest(key, "se_pro_demo_2026_unlimited"):
            return True
        secret = os.environ.get("ADMIN_API_SECRET", "").strip()
        if secret and key.startswith("se_pro_"):
            parts = key[len("se_pro_") :].rsplit("_", 1)
            if len(parts) == 2 and parts[0] and len(parts[1]) == 24:
                expected = hmac.new(secret.encode("utf-8"), parts[0].encode("utf-8"), hashlib.sha256).hexdigest()[:24]
                if hmac.compare_digest(parts[1], expected):
                    return True
        return False

    def _apply_pro_upgrade(self, workspace_id: str, api_key: str) -> Dict[str, Any]:
        current = self.get_status(workspace_id)
        ws_id = current["workspace_id"]
        bounded_put(self._pro_keys, api_key, ws_id, MAX_WORKSPACES)
        upgraded = {
            **current,
            "tier": "pro",
            "limit": PRO_MONTHLY_LIMIT,
            "remaining": max(0, PRO_MONTHLY_LIMIT - current["used"]),
            "price_usd_monthly": PRO_PRICE_USD,
            "stripe_pass_usd": PRO_STRIPE_PASS_USD,
            "api_key": api_key,
        }
        self._free_workspaces.pop(ws_id, None)
        self._free_export_counts.pop(ws_id, None)
        bounded_put(self._pro_workspaces, ws_id, upgraded, MAX_WORKSPACES)
        return copy.deepcopy(upgraded)

    def redeem_stripe_webhook(self, session_id: str, workspace_id: str) -> Tuple[Optional[Dict[str, Any]], bool]:
        """Record paid Stripe webhook idempotently WITHOUT locking out the buyer's browser redirect claim."""
        sid = (session_id or "").strip()
        if not sid:
            return None, False
        with self._lock:
            rec = self._redeemed_sessions.get(sid)
            if rec and rec.get("webhook_recorded"):
                return None, False
            api_key = (rec or {}).get("api_key") or self._session_pro_key(sid)
            should_log = not bool((rec or {}).get("event_logged"))
            new_rec = {
                "webhook_recorded": True,
                "browser_claimed": bool((rec or {}).get("browser_claimed")),
                "api_key": api_key,
                "event_logged": True,
                "ts": int(time.time()),
            }
            bounded_put(self._redeemed_sessions, sid, new_rec, MAX_WORKSPACES)
            return self._apply_pro_upgrade(workspace_id, api_key), should_log

    def claim_stripe_browser_session(self, session_id: str, workspace_id: str) -> Tuple[Optional[Dict[str, Any]], bool]:
        """Single-use browser claim for `/?session_id=cs_...` that succeeds even after webhook delivery."""
        sid = (session_id or "").strip()
        if not sid:
            return None, False
        with self._lock:
            rec = self._redeemed_sessions.get(sid)
            if rec and rec.get("browser_claimed"):
                return None, False
            api_key = (rec or {}).get("api_key") or self._session_pro_key(sid)
            should_log = not bool((rec or {}).get("event_logged"))
            new_rec = {
                "webhook_recorded": bool((rec or {}).get("webhook_recorded")),
                "browser_claimed": True,
                "api_key": api_key,
                "event_logged": True,
                "ts": int(time.time()),
            }
            bounded_put(self._redeemed_sessions, sid, new_rec, MAX_WORKSPACES)
            return self._apply_pro_upgrade(workspace_id, api_key), should_log

    def mark_stripe_session_redeemed(self, session_id: str) -> bool:
        sid = (session_id or "").strip()
        with self._lock:
            if not sid or sid in self._redeemed_sessions:
                return False
            bounded_put(
                self._redeemed_sessions,
                sid,
                {"webhook_recorded": True, "browser_claimed": True, "api_key": "", "event_logged": True, "ts": int(time.time())},
                MAX_WORKSPACES,
            )
            return True

    def get_status(
        self,
        workspace_id: str = "default-workspace",
        api_key: Optional[str] = None,
        *,
        is_prod: bool = False,
    ) -> Dict[str, Any]:
        """Read-only status lookup: NEVER mutates stores and NEVER leaks stored Pro API keys to callers."""
        ws_id = (workspace_id or "").strip()[:120] or "default-workspace"
        with self._lock:
            is_pro_key = self.is_valid_pro_key(api_key, is_prod=is_prod)
            if is_pro_key and api_key in self._pro_keys:
                ws_id = self._pro_keys[api_key]

            existing = self._pro_workspaces.get(ws_id) or self._free_workspaces.get(ws_id)
            if not existing:
                tier = "pro" if is_pro_key else "free"
                limit = PRO_MONTHLY_LIMIT if tier == "pro" else FREE_MONTHLY_LIMIT
                return {
                    "workspace_id": ws_id,
                    "tier": tier,
                    "used": 0,
                    "limit": limit,
                    "remaining": limit,
                    "price_usd_monthly": PRO_PRICE_USD if tier == "pro" else 0,
                    "stripe_pass_usd": PRO_STRIPE_PASS_USD,
                    "api_key": None,
                }
            out = copy.deepcopy(existing)
            out["api_key"] = None
            if is_pro_key and out["tier"] != "pro":
                out["tier"] = "pro"
                out["limit"] = PRO_MONTHLY_LIMIT
                out["remaining"] = max(0, PRO_MONTHLY_LIMIT - out["used"])
                out["price_usd_monthly"] = PRO_PRICE_USD
                out["stripe_pass_usd"] = PRO_STRIPE_PASS_USD
            return out

    def _raise_quota_exceeded(self, used: int, limit: int) -> None:
        raise PermissionError(
            f"Free tier quota exhausted ({used}/{limit} docs/mo). "
            f"Upgrade to BillTally Pro ({STRIPE_UPGRADE_URL}) for {PRO_MONTHLY_LIMIT} docs/mo, "
            f"or convert scanned bank statement PDFs directly to QuickBooks .QBO at {CHECK2QBO_COMPANION_URL}"
        )

    def check_available(
        self,
        workspace_id: str = "default-workspace",
        api_key: Optional[str] = None,
        *,
        is_prod: bool = False,
        caller_ip: str = "",
    ) -> Dict[str, Any]:
        with self._lock:
            current = self.get_status(workspace_id, api_key=api_key, is_prod=is_prod)
            if current["used"] >= current["limit"]:
                self._raise_quota_exceeded(current["used"], current["limit"])
            clean_ip = (caller_ip or "").strip()
            if current["tier"] != "pro" and clean_ip not in LOCAL_IPS:
                ip_bucket = f"{clean_ip}:{time.strftime('%Y-%m', time.gmtime())}"
                ip_used = self._ip_free_counts.get(ip_bucket, 0)
                if ip_used >= MAX_FREE_DOCS_PER_IP_MONTHLY:
                    self._raise_quota_exceeded(ip_used, MAX_FREE_DOCS_PER_IP_MONTHLY)
            return current

    def consume_document(
        self,
        workspace_id: str = "default-workspace",
        api_key: Optional[str] = None,
        *,
        is_prod: bool = False,
        caller_ip: str = "",
    ) -> Dict[str, Any]:
        with self._lock:
            current = self.check_available(workspace_id, api_key=api_key, is_prod=is_prod, caller_ip=caller_ip)
            new_used = current["used"] + 1
            updated = {**current, "used": new_used, "remaining": max(0, current["limit"] - new_used)}
            target_store = self._pro_workspaces if updated["tier"] == "pro" else self._free_workspaces
            bounded_put(target_store, current["workspace_id"], updated, MAX_WORKSPACES)
            clean_ip = (caller_ip or "").strip()
            if updated["tier"] != "pro" and clean_ip not in LOCAL_IPS:
                ip_bucket = f"{clean_ip}:{time.strftime('%Y-%m', time.gmtime())}"
                bounded_put(self._ip_free_counts, ip_bucket, self._ip_free_counts.get(ip_bucket, 0) + 1, MAX_WORKSPACES)
            return copy.deepcopy(updated)

    def check_export_available(
        self,
        workspace_id: str = "default-workspace",
        api_key: Optional[str] = None,
        *,
        doc_count: int = 1,
        is_prod: bool = False,
        caller_ip: str = "",
    ) -> Dict[str, Any]:
        """Validate free-tier export eligibility without mutating counters."""
        with self._lock:
            current = self.get_status(workspace_id, api_key=api_key, is_prod=is_prod)
            if current["tier"] == "pro":
                return {**current, "exports_used": 0, "exports_limit": PRO_MONTHLY_LIMIT}
            ws_id = current["workspace_id"]
            used = self._free_export_counts.get(ws_id, 0)
            if used >= FREE_EXPORT_LIMIT or doc_count > FREE_EXPORT_LIMIT:
                raise PermissionError(
                    f"Free tier export limit reached ({used}/{FREE_EXPORT_LIMIT} spreadsheet exports; up to {FREE_EXPORT_LIMIT} bills per export). "
                    f"Unlock the ${PRO_STRIPE_PASS_USD:.2f} One-Time Pro Pass ({STRIPE_UPGRADE_URL}) for unlimited exports."
                )
            clean_ip = (caller_ip or "").strip()
            if clean_ip not in LOCAL_IPS:
                ip_bucket = f"{clean_ip}:{time.strftime('%Y-%m', time.gmtime())}"
                ip_used = self._ip_free_export_counts.get(ip_bucket, 0)
                if ip_used >= MAX_FREE_EXPORTS_PER_IP_MONTHLY:
                    raise PermissionError(
                        f"Monthly free export ceiling reached for this network ({ip_used}/{MAX_FREE_EXPORTS_PER_IP_MONTHLY}). "
                        f"Unlock the ${PRO_STRIPE_PASS_USD:.2f} One-Time Pro Pass ({STRIPE_UPGRADE_URL})."
                    )
            return {**current, "exports_used": used, "exports_limit": FREE_EXPORT_LIMIT}

    def consume_export(
        self,
        workspace_id: str = "default-workspace",
        api_key: Optional[str] = None,
        *,
        doc_count: int = 1,
        is_prod: bool = False,
        caller_ip: str = "",
    ) -> Dict[str, Any]:
        """Enforce the 3-export free preview cap + per-IP ceiling for non-Pro workspaces."""
        with self._lock:
            checked = self.check_export_available(
                workspace_id, api_key=api_key, doc_count=doc_count, is_prod=is_prod, caller_ip=caller_ip
            )
            if checked["tier"] == "pro":
                return checked
            ws_id = checked["workspace_id"]
            new_used = checked["exports_used"] + 1
            bounded_put(self._free_export_counts, ws_id, new_used, MAX_WORKSPACES)
            clean_ip = (caller_ip or "").strip()
            if clean_ip not in LOCAL_IPS:
                ip_bucket = f"{clean_ip}:{time.strftime('%Y-%m', time.gmtime())}"
                bounded_put(self._ip_free_export_counts, ip_bucket, self._ip_free_export_counts.get(ip_bucket, 0) + 1, MAX_WORKSPACES)
            return {**checked, "exports_used": new_used}

    def upgrade_to_pro(self, workspace_id: str = "default-workspace") -> Dict[str, Any]:
        with self._lock:
            return self._apply_pro_upgrade(workspace_id, self._sign_pro_key(secrets.token_hex(12)))
