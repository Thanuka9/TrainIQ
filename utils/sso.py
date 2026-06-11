"""Enterprise SSO via OpenID Connect (Google, Microsoft, custom OIDC)."""
from __future__ import annotations

import logging
import secrets
from typing import Any
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

PROVIDER_LABELS = {
    "google": "Google Workspace",
    "microsoft": "Microsoft Entra ID",
    "oidc": "Single Sign-On",
}


def tenant_sso_available(tenant) -> bool:
    if not tenant or not getattr(tenant, "sso_enabled", False):
        return False
    if (getattr(tenant, "plan", "") or "").lower() != "enterprise":
        return False
    return bool(tenant.sso_client_id and tenant.sso_client_secret and _issuer_for_tenant(tenant))


def _issuer_for_tenant(tenant) -> str | None:
    provider = (getattr(tenant, "sso_provider", "") or "").lower()
    if provider == "google":
        return "https://accounts.google.com"
    if provider == "microsoft":
        domain = (getattr(tenant, "sso_tenant_domain", "") or "common").strip()
        return f"https://login.microsoftonline.com/{domain}/v2.0"
    return (getattr(tenant, "sso_issuer_url", "") or "").strip() or None


def _discovery(issuer: str) -> dict[str, Any]:
    base = issuer.rstrip("/")
    url = f"{base}/.well-known/openid-configuration"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


def build_authorization_url(tenant, *, redirect_uri: str, state: str, nonce: str) -> str:
    issuer = _issuer_for_tenant(tenant)
    if not issuer:
        raise ValueError("SSO is not configured for this organization.")
    meta = _discovery(issuer)
    params = {
        "client_id": tenant.sso_client_id,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": redirect_uri,
        "state": state,
        "nonce": nonce,
    }
    if (tenant.sso_provider or "").lower() == "microsoft":
        params["response_mode"] = "query"
    return f"{meta['authorization_endpoint']}?{urlencode(params)}"


def exchange_code_and_userinfo(tenant, *, code: str, redirect_uri: str) -> dict[str, Any]:
    issuer = _issuer_for_tenant(tenant)
    meta = _discovery(issuer)
    token_resp = requests.post(
        meta["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": tenant.sso_client_id,
            "client_secret": tenant.sso_client_secret,
        },
        timeout=15,
    )
    token_resp.raise_for_status()
    tokens = token_resp.json()
    access_token = tokens.get("access_token")
    if not access_token:
        raise ValueError("SSO token response missing access_token.")

    userinfo_resp = requests.get(
        meta["userinfo_endpoint"],
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    userinfo_resp.raise_for_status()
    return userinfo_resp.json()


def new_sso_state() -> tuple[str, str]:
    return secrets.token_urlsafe(32), secrets.token_urlsafe(32)


def sso_label(tenant) -> str:
    provider = (getattr(tenant, "sso_provider", "") or "oidc").lower()
    return PROVIDER_LABELS.get(provider, "Single Sign-On")
