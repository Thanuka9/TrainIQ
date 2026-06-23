"""Optional OIDC SSO for the TrainIQ platform tenant (staff login)."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def platform_oidc_configured() -> bool:
    return bool(
        (os.getenv('PLATFORM_OIDC_CLIENT_ID') or '').strip()
        and (os.getenv('PLATFORM_OIDC_CLIENT_SECRET') or '').strip()
        and (os.getenv('PLATFORM_OIDC_ISSUER_URL') or '').strip()
    )


def apply_platform_oidc_to_tenant(tenant) -> bool:
    """Apply PLATFORM_OIDC_* env vars to the platform tenant when configured."""
    if not tenant or not platform_oidc_configured():
        return False

    tenant.sso_enabled = True
    tenant.sso_provider = (os.getenv('PLATFORM_OIDC_PROVIDER') or 'oidc').strip().lower()
    tenant.sso_client_id = os.getenv('PLATFORM_OIDC_CLIENT_ID', '').strip()
    tenant.sso_client_secret = os.getenv('PLATFORM_OIDC_CLIENT_SECRET', '').strip()
    tenant.sso_issuer_url = os.getenv('PLATFORM_OIDC_ISSUER_URL', '').strip()
    tenant.sso_tenant_domain = (os.getenv('PLATFORM_OIDC_TENANT_DOMAIN') or '').strip() or None
    tenant.plan = tenant.plan or 'enterprise'
    logger.info('[platform_sso] Applied PLATFORM_OIDC_* to tenant id=%s', tenant.id)
    return True
