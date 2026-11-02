"""
OAuth 2.1 with S256 PKCE Authorization Server & Free/Pro Quota Manager.
Enables seamless authentication (including RFC 7591 Dynamic Client Registration and refresh_token)
for both Claude Connectors Directory and ChatGPT MCP Apps, and manages Free (15 docs/mo) vs Pro ($29/mo) quotas.
"""

import base64
import copy
import hashlib
import secrets
import time
from typing import Any, Dict, List, Optional

FREE_MONTHLY_LIMIT = 15
PRO_MONTHLY_LIMIT = 5000
PRO_PRICE_USD = 29


def compute_s256_challenge(code_verifier: str) -> str:
    """Compute RFC 7636 S256 code_challenge from a PKCE code_verifier."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class OAuth21Server:
    """Stateless-friendly OAuth 2.1 + S256 PKCE provider for MCP connectors."""

    def __init__(self, base_url: str = "http://localhost:8791") -> None:
        self._base_url = base_url.rstrip("/")
        self._auth_codes: Dict[str, Dict[str, Any]] = {}
        self._tokens: Dict[str, Dict[str, Any]] = {}
        self._refresh_tokens: Dict[str, Dict[str, Any]] = {}
        self._registered_clients: Dict[str, Dict[str, Any]] = {}

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
    ) -> Dict[str, Any]:
        """RFC 7591 Dynamic Client Registration for Claude & ChatGPT MCP connectors."""
        client_id = f"se_client_{secrets.token_hex(8)}"
        record = {
            "client_id": client_id,
            "client_name": client_name.strip() or "MCP Assistant Client",
            "redirect_uris": list(redirect_uris or ["https://claude.ai/api/mcp/auth_callback"]),
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "client_id_issued_at": int(time.time()),
        }
        self._registered_clients = {**self._registered_clients, client_id: record}
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
        if response_type != "code":
            raise ValueError("Unsupported response_type; OAuth 2.1 requires 'code'.")
        if code_challenge_method.upper() != "S256":
            raise ValueError("OAuth 2.1 requires code_challenge_method='S256'.")
        if not client_id.strip() or not redirect_uri.strip() or len(code_challenge.strip()) < 16:
            raise ValueError("Missing or invalid client_id, redirect_uri, or code_challenge.")

        code = f"se_auth_{secrets.token_urlsafe(24)}"
        record = {
            "code": code,
            "client_id": client_id.strip(),
            "redirect_uri": redirect_uri.strip(),
            "code_challenge": code_challenge.strip(),
            "code_challenge_method": "S256",
            "scope": scope,
            "state": state,
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + 600,
            "used": False,
        }
        self._auth_codes = {**self._auth_codes, code: record}
        redirect_target = f"{redirect_uri}?code={code}" + (f"&state={state}" if state else "")
        return {
            "code": code,
            "state": state,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "redirect_target": redirect_target,
            "code_challenge_method": "S256",
            "expires_in": 600,
        }

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
        if grant_type == "refresh_token":
            ref_record = self._refresh_tokens.get(refresh_token.strip())
            if not ref_record:
                raise ValueError("Invalid or expired refresh_token.")
            new_access = f"se_mcp_live_{secrets.token_urlsafe(28)}"
            new_refresh = f"se_mcp_ref_{secrets.token_urlsafe(28)}"
            token_entry = {
                "access_token": new_access,
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": new_refresh,
                "scope": ref_record["scope"],
                "client_id": ref_record["client_id"],
            }
            self._tokens = {**self._tokens, new_access: token_entry}
            self._refresh_tokens = {**self._refresh_tokens, new_refresh: token_entry}
            return copy.deepcopy(token_entry)

        if grant_type != "authorization_code":
            raise ValueError("Unsupported grant_type; expected 'authorization_code' or 'refresh_token'.")
        record = self._auth_codes.get(code)
        if not record:
            raise ValueError("Invalid or expired authorization code.")
        if record.get("used"):
            raise ValueError("Authorization code has already been redeemed.")
        if record["client_id"] != client_id.strip():
            raise ValueError("client_id mismatch.")
        if record["redirect_uri"] != redirect_uri.strip():
            raise ValueError("redirect_uri mismatch.")
        if not code_verifier or len(code_verifier.strip()) < 20:
            raise ValueError("Invalid PKCE code_verifier length.")

        computed_challenge = compute_s256_challenge(code_verifier.strip())
        if not secrets.compare_digest(computed_challenge, record["code_challenge"]):
            raise ValueError("PKCE S256 verification failed: code_verifier does not match code_challenge.")

        updated_record = {**record, "used": True}
        self._auth_codes = {**self._auth_codes, code: updated_record}

        access_token = f"se_mcp_live_{secrets.token_urlsafe(28)}"
        new_ref_token = f"se_mcp_ref_{secrets.token_urlsafe(28)}"
        token_entry = {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": new_ref_token,
            "scope": record["scope"],
            "client_id": client_id,
        }
        self._tokens = {**self._tokens, access_token: token_entry}
        self._refresh_tokens = {**self._refresh_tokens, new_ref_token: token_entry}
        return copy.deepcopy(token_entry)


class QuotaManager:
    """Manages Free Tier (15 docs/mo) vs Pro Tier ($29/mo) usage and API keys immutably."""

    def __init__(self) -> None:
        self._workspaces: Dict[str, Dict[str, Any]] = {}
        self._pro_keys: Dict[str, str] = {
            "se_pro_demo_2026_unlimited": "demo-pro-workspace",
        }

    def get_status(self, workspace_id: str = "default-workspace", api_key: Optional[str] = None) -> Dict[str, Any]:
        ws_id = workspace_id.strip() or "default-workspace"
        is_pro_key = bool(api_key and (api_key in self._pro_keys or api_key.startswith("se_pro_")))
        existing = self._workspaces.get(ws_id)
        if not existing:
            tier = "pro" if is_pro_key else "free"
            limit = PRO_MONTHLY_LIMIT if tier == "pro" else FREE_MONTHLY_LIMIT
            existing = {
                "workspace_id": ws_id,
                "tier": tier,
                "used": 0,
                "limit": limit,
                "remaining": limit,
                "price_usd_monthly": PRO_PRICE_USD if tier == "pro" else 0,
                "api_key": api_key if is_pro_key else None,
            }
            self._workspaces = {**self._workspaces, ws_id: existing}
        elif is_pro_key and existing["tier"] != "pro":
            existing = {
                **existing,
                "tier": "pro",
                "limit": PRO_MONTHLY_LIMIT,
                "remaining": max(0, PRO_MONTHLY_LIMIT - existing["used"]),
                "price_usd_monthly": PRO_PRICE_USD,
                "api_key": api_key,
            }
            self._workspaces = {**self._workspaces, ws_id: existing}
        return copy.deepcopy(existing)

    def consume_document(self, workspace_id: str = "default-workspace", api_key: Optional[str] = None) -> Dict[str, Any]:
        current = self.get_status(workspace_id, api_key=api_key)
        if current["used"] >= current["limit"]:
            raise PermissionError(
                f"Free tier quota exhausted ({current['used']}/{current['limit']} docs/mo). "
                f"Upgrade to SchemaExtract Pro ($29/mo) for {PRO_MONTHLY_LIMIT} docs/mo and automated spreadsheet exports."
            )
        new_used = current["used"] + 1
        updated = {
            **current,
            "used": new_used,
            "remaining": max(0, current["limit"] - new_used),
        }
        self._workspaces = {**self._workspaces, current["workspace_id"]: updated}
        return copy.deepcopy(updated)

    def upgrade_to_pro(self, workspace_id: str = "default-workspace") -> Dict[str, Any]:
        current = self.get_status(workspace_id)
        generated_key = f"se_pro_{secrets.token_hex(12)}"
        self._pro_keys = {**self._pro_keys, generated_key: current["workspace_id"]}
        upgraded = {
            **current,
            "tier": "pro",
            "limit": PRO_MONTHLY_LIMIT,
            "remaining": max(0, PRO_MONTHLY_LIMIT - current["used"]),
            "price_usd_monthly": PRO_PRICE_USD,
            "api_key": generated_key,
        }
        self._workspaces = {**self._workspaces, current["workspace_id"]: upgraded}
        return copy.deepcopy(upgraded)
