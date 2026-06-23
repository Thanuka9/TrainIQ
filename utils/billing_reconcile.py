"""Compare tenant billing state against Stripe subscriptions."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _expected_db_status(stripe_status: str) -> str | None:
    s = (stripe_status or '').lower()
    if s in ('past_due', 'unpaid'):
        return 'past_due'
    if s in ('active', 'trialing'):
        return 'active'
    if s in ('canceled', 'incomplete_expired'):
        return 'expired'
    return None


def reconcile_stripe_tenants(*, limit: int = 200) -> dict[str, Any]:
    """
    Fetch Stripe subscriptions for tenants with stripe_subscription_id and
    report mismatches vs local plan/status.
    """
    from models import Tenant
    from utils.stripe_billing import STRIPE_SECRET_KEY, stripe_available

    if not stripe_available():
        return {
            'available': False,
            'checked': 0,
            'mismatches': [],
            'message': 'Stripe is not configured.',
        }

    try:
        import stripe
    except ImportError:
        return {
            'available': False,
            'checked': 0,
            'mismatches': [],
            'message': 'Stripe SDK not installed.',
        }

    stripe.api_key = STRIPE_SECRET_KEY
    tenants = (
        Tenant.query.filter(Tenant.stripe_subscription_id.isnot(None))
        .order_by(Tenant.id)
        .limit(max(1, limit))
        .all()
    )
    mismatches: list[dict[str, Any]] = []

    for tenant in tenants:
        sub_id = (tenant.stripe_subscription_id or '').strip()
        if not sub_id:
            continue
        try:
            sub = stripe.Subscription.retrieve(sub_id)
        except Exception as exc:
            err_cls = type(exc).__name__
            if err_cls == 'InvalidRequestError':
                mismatches.append({
                    'tenant_id': tenant.id,
                    'tenant_name': tenant.name,
                    'issue': 'subscription_not_found',
                    'local_status': tenant.status,
                    'local_plan': tenant.plan,
                    'stripe_subscription_id': sub_id,
                })
                continue
            logger.warning('[billing_reconcile] tenant=%s sub=%s: %s', tenant.id, sub_id, exc)
            mismatches.append({
                'tenant_id': tenant.id,
                'tenant_name': tenant.name,
                'issue': 'stripe_error',
                'detail': str(exc)[:200],
            })
            continue

        stripe_status = (sub.get('status') or '').lower()
        expected = _expected_db_status(stripe_status)
        local_status = (tenant.status or 'active').lower()

        if expected and local_status != expected:
            mismatches.append({
                'tenant_id': tenant.id,
                'tenant_name': tenant.name,
                'issue': 'status_mismatch',
                'local_status': local_status,
                'expected_status': expected,
                'stripe_status': stripe_status,
            })

        if stripe_status in ('canceled', 'incomplete_expired') and tenant.stripe_subscription_id:
            mismatches.append({
                'tenant_id': tenant.id,
                'tenant_name': tenant.name,
                'issue': 'subscription_ended',
                'local_status': local_status,
                'stripe_status': stripe_status,
            })

    return {
        'available': True,
        'checked': len(tenants),
        'mismatch_count': len(mismatches),
        'mismatches': mismatches,
    }


def get_cached_stripe_reconcile(ttl_seconds: float = 900.0) -> dict[str, Any]:
    from utils.ops_cache import get_json_cached

    return get_json_cached(
        'stripe_billing_reconcile',
        ttl_seconds,
        reconcile_stripe_tenants,
    )
