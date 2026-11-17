"""
OAuth 2.1 with S256 PKCE Authorization Server & Request Workspace Resolver.
Re-exports `QuotaManager` and pricing constants from `app.quota_manager` so every module stays < 350 lines.
"""

from collections import OrderedDict
import base64
import copy
import hashlib
import os
import secrets
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.quota_manager import (
    CHECK2QBO_COMPANION_URL,
    FREE_MONTHLY_LIMIT,
    LOCAL_IPS,
    MAX_FREE_DOCS_PER_IP_MONTHLY,
    MAX_WORKSPACES,
    PRO_MONTHLY_LIMIT,
    PRO_PRICE_USD,
    PRO_STRIPE_PASS_USD,
    QuotaManager,
    STRIPE_UPGRADE_URL,
    bounded_put as _bounded_put,
)

MAX_OAUTH_CLIENTS_PER_IP_HOURLY = 15
MAX_OAUTH_RECORDS = 4096
AUTH_CODE_TTL_SEC = 600
ACCESS_TOKEN_TTL_SEC = 3600
REFRESH_TOKEN_TTL_SEC = 30 * 86400

__all__ = [
    "ACCESS_TOKEN_TTL_SEC",
    "AUTH_CODE_TTL_SEC",
    "CHECK2QBO_COMPANION_URL",
    "FREE_MONTHLY_LIMIT",
    "MAX_FREE_DOCS_PER_IP_MONTHLY",
    "MAX_OAUTH_CLIENTS_PER_IP_HOURLY",
    "MAX_OAUTH_RECORDS",
    "MAX_WORKSPACES",
    "OAuth21Server",
    "PRO_MONTHLY_LIMIT",
    "PRO_PRICE_USD",
    "PRO_STRIPE_PASS_USD",
    "QuotaManager",
    "REFRESH_TOKEN_TTL_SEC",
    "STRIPE_UPGRADE_URL",
    "_is_production_runtime",
    "compute_s256_challenge",
    "extract_caller_ip",
    "resolve_request_workspace",
]


def _is_production_runtime(request: Any = None) -> bool:
    for env_key in ("PUBLIC_BASE_URL", "RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID"):
        if os.environ.get(env_key, "").strip():
            return True
    if request is None:
        return False
    headers = getattr(request, "headers", {}) or {}
    base_url = str(getattr(request, "base_url", "")).strip().lower()
    xf_proto = str(headers.get("x-forwarded-proto", "")).split(",")[0].strip().lower()
    return base_url.startswith("https://") or xf_proto == "https" or "railway.app" in base_url


def extract_caller_ip(request: Any) -> str:
    """Return rightmost proxy-appended X-Forwarded-For hop or direct client host."""
    if request is None:
        return "local"
    headers = getattr(request, "headers", {}) or {}
    xff = str(headers.get("x-forwarded-for", "")).strip()
    client_obj = getattr(request, "client", None)
    client_host = getattr(client_obj, "host", "") if client_obj else ""
    return (xff.split(",")[-1].strip() if xff else "") or client_host or "local"


def _validate_redirect_uri(uri: str) -> str:
    cleaned = (uri or "").strip()
    parsed = urlparse(cleaned)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme == "https" and host:
        return cleaned
    if scheme == "http" and host in ("localhost", "127.0.0.1", "::1"):
        return cleaned
    raise ValueError("Invalid redirect_uri: OAuth 2.1 requires https:// or loopback http://localhost.")


def resolve_request_workspace(
    request: Any,
    explicit_workspace_id: str = "default-workspace",
    *,
    oauth_server: Optional["OAuth21Server"] = None,
    quota_manager: Optional[QuotaManager] = None,
    api_key: Optional[str] = None,
) -> str:
    """Scope default-workspace per caller/month without trusting spoofable UA/XFF or rotating OAuth tokens."""
    ws = (explicit_workspace_id or "").strip()[:120]
    is_prod = _is_production_runtime(request)
    has_valid_pro = bool(quota_manager and api_key and quota_manager.is_valid_pro_key(api_key, is_prod=is_prod))

    if ws and ws != "default-workspace" and (not is_prod or has_valid_pro or request is None):
        return ws
    if request is None:
        return "default-workspace"

    headers = getattr(request, "headers", {}) or {}
    month_tag = time.strftime("%Y-%m", time.gmtime())

    auth_hdr = str(headers.get("authorization", "")).strip()
    if auth_hdr.lower().startswith("bearer ") and oauth_server is not None:
        raw_tok = auth_hdr[7:].strip()
        tok_rec = oauth_server.validate_access_token(raw_tok)
        if tok_rec:
            subj = tok_rec.get("subject_id") or tok_rec["client_id"]
            digest = hashlib.sha256(f"oauth:{tok_rec['client_id']}:{subj}".encode("utf-8")).hexdigest()[:16]
            return f"oauth-{digest}-{month_tag}"

    ephemeral_uid = (
        str(headers.get("openai-ephemeral-user-id", "")).strip()[:128]
        or str(headers.get("openai-conversation-id", "")).strip()[:128]
    )
    if ephemeral_uid:
        digest = hashlib.sha256(f"oai:{ephemeral_uid}".encode("utf-8")).hexdigest()[:16]
        return f"user-{digest}-{month_tag}"

    ip = extract_caller_ip(request)
    if ip in LOCAL_IPS:
        return f"local-{month_tag}"
    digest = hashlib.sha256(f"ip:{ip}".encode("utf-8")).hexdigest()[:16]
    return f"web-{digest}-{month_tag}"


def compute_s256_challenge(code_verifier: str) -> str:
    """Compute RFC 7636 S256 code_challenge from a PKCE code_verifier."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class OAuth21Server:
    """Bounded, TTL-enforced OAuth 2.1 + S256 PKCE provider for MCP connectors."""

    def __init__(self, base_url: str = "http://localhost:8791") -> None:
        self._base_url = base_url.rstrip("/")
        self._auth_codes: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._tokens: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._refresh_tokens: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._registered_clients: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._ip_registrations: "OrderedDict[str, int]" = OrderedDict()

    def _prune_expired(self) -> None:
        now = int(time.time())
        for store in (self._auth_codes, self._tokens, self._refresh_tokens):
            for k in [k for k, v in store.items() if now > v.get("expires_at", 0)]:
                store.pop(k, None)

    def metadata(self, base_url: Optional[str] = None) -> Dict[str, Any]:
        root = (base_url or self._base_url).rstrip("/")
        return {
            "issuer": root,
            "authorization_endpoint": f"{root}/oauth/authorize",
            "token_endpoint": f"{root}/oauth/token",
            "registration_endpoint": f"{root}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
            "scopes_supported": ["mcp:tools", "mcp:export", "mcp:read"],
            "service_documentation": f"{root}/",
            "op_policy_uri": f"{root}/privacy",
            "op_tos_uri": f"{root}/terms",
        }

    def register_client(
        self,
        client_name: str = "MCP Assistant Client",
        redirect_uris: Optional[List[str]] = None,
        *,
        caller_ip: str = "",
    ) -> Dict[str, Any]:
        clean_ip = (caller_ip or "").strip()
        if clean_ip and clean_ip not in LOCAL_IPS:
            bucket = f"{clean_ip}:{time.strftime('%Y-%m-%d-%H', time.gmtime())}"
            used = self._ip_registrations.get(bucket, 0)
            if used >= MAX_OAUTH_CLIENTS_PER_IP_HOURLY:
                raise ValueError("Too many OAuth client registrations from this IP; retry next hour.")
            _bounded_put(self._ip_registrations, bucket, used + 1, MAX_OAUTH_RECORDS)

        raw_uris = list(redirect_uris or ["https://claude.ai/api/mcp/auth_callback"])[:10]
        validated_uris = [_validate_redirect_uri(u) for u in raw_uris]
        client_id = f"se_client_{secrets.token_hex(8)}"
        record = {
            "client_id": client_id,
            "client_name": (client_name or "").strip()[:120] or "MCP Assistant Client",
            "redirect_uris": validated_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "client_id_issued_at": int(time.time()),
        }
        _bounded_put(self._registered_clients, client_id, record, MAX_OAUTH_RECORDS)
        return copy.deepcopy(record)

    def issue_authorization_code(
        self,
        *,
        response_type: str,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str = "S256",
        state: Optional[str] = None,
        scope: str = "mcp:tools mcp:export",
    ) -> Dict[str, Any]:
        self._prune_expired()
        if response_type != "code":
            raise ValueError("Unsupported response_type; OAuth 2.1 requires 'code'.")
        if code_challenge_method.upper() != "S256":
            raise ValueError("OAuth 2.1 requires code_challenge_method='S256'.")
        cid = client_id.strip()
        if not cid or len(code_challenge.strip()) < 16:
            raise ValueError("Missing or invalid client_id or code_challenge.")

        clean_redirect = _validate_redirect_uri(redirect_uri)
        registered = self._registered_clients.get(cid)
        if registered and registered.get("redirect_uris") and clean_redirect not in registered["redirect_uris"]:
            raise ValueError("redirect_uri does not match registered client redirect_uris.")

        now = int(time.time())
        code = f"se_auth_{secrets.token_urlsafe(24)}"
        record = {
            "code": code,
            "client_id": cid,
            "subject_id": secrets.token_hex(8),
            "redirect_uri": clean_redirect,
            "code_challenge": code_challenge.strip(),
            "code_challenge_method": "S256",
            "scope": scope,
            "state": state,
            "created_at": now,
            "expires_at": now + AUTH_CODE_TTL_SEC,
            "used": False,
        }
        _bounded_put(self._auth_codes, code, record, MAX_OAUTH_RECORDS)
        redirect_target = f"{clean_redirect}?code={code}" + (f"&state={state}" if state else "")
        return {
            "code": code,
            "state": state,
            "client_id": cid,
            "redirect_uri": clean_redirect,
            "redirect_target": redirect_target,
            "code_challenge_method": "S256",
            "expires_in": AUTH_CODE_TTL_SEC,
        }

    def validate_access_token(self, token: str) -> Optional[Dict[str, Any]]:
        self._prune_expired()
        rec = self._tokens.get((token or "").strip())
        if not rec or int(time.time()) > rec.get("expires_at", 0):
            return None
        return rec

    def _issue_token_pair(self, *, client_id: str, scope: str, subject_id: str, now: int) -> Dict[str, Any]:
        access_token = f"se_mcp_live_{secrets.token_urlsafe(28)}"
        new_ref_token = f"se_mcp_ref_{secrets.token_urlsafe(28)}"
        token_entry = {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_TTL_SEC,
            "expires_at": now + ACCESS_TOKEN_TTL_SEC,
            "refresh_token": new_ref_token,
            "scope": scope,
            "client_id": client_id,
            "subject_id": subject_id,
        }
        _bounded_put(self._tokens, access_token, token_entry, MAX_OAUTH_RECORDS)
        _bounded_put(self._refresh_tokens, new_ref_token, {**token_entry, "expires_at": now + REFRESH_TOKEN_TTL_SEC}, MAX_OAUTH_RECORDS)
        out = copy.deepcopy(token_entry)
        out.pop("expires_at", None)
        out.pop("subject_id", None)
        return out

    def exchange_code_for_token(
        self,
        *,
        grant_type: str,
        code: str = "",
        client_id: str = "",
        redirect_uri: str = "",
        code_verifier: str = "",
        refresh_token: str = "",
    ) -> Dict[str, Any]:
        self._prune_expired()
        now = int(time.time())

        if grant_type == "refresh_token":
            ref_key = refresh_token.strip()
            ref_record = self._refresh_tokens.get(ref_key)
            if not ref_record or now > ref_record.get("expires_at", 0):
                self._refresh_tokens.pop(ref_key, None)
                raise ValueError("Invalid or expired refresh_token.")
            if client_id.strip() and ref_record["client_id"] != client_id.strip():
                raise ValueError("client_id mismatch on refresh_token.")
            self._refresh_tokens.pop(ref_key, None)
            return self._issue_token_pair(
                client_id=ref_record["client_id"],
                scope=ref_record["scope"],
                subject_id=ref_record.get("subject_id") or ref_record["client_id"],
                now=now,
            )

        if grant_type != "authorization_code":
            raise ValueError("Unsupported grant_type; expected 'authorization_code' or 'refresh_token'.")
        record = self._auth_codes.get(code)
        if not record or now > record.get("expires_at", 0):
            self._auth_codes.pop(code, None)
            raise ValueError("Invalid or expired authorization code.")
        if record.get("used"):
            raise ValueError("Authorization code has already been redeemed.")
        if record["client_id"] != client_id.strip():
            raise ValueError("client_id mismatch.")
        if record["redirect_uri"] != redirect_uri.strip():
            raise ValueError("redirect_uri mismatch.")
        if not code_verifier or len(code_verifier.strip()) < 20:
            raise ValueError("Invalid PKCE code_verifier length.")
        if not secrets.compare_digest(compute_s256_challenge(code_verifier.strip()), record["code_challenge"]):
            raise ValueError("PKCE S256 verification failed: code_verifier does not match code_challenge.")

        record["used"] = True
        return self._issue_token_pair(
            client_id=client_id.strip(),
            scope=record["scope"],
            subject_id=record.get("subject_id") or client_id.strip(),
            now=now,
        )
