"""MRR/ARR history derived from BillingEvent (Stripe-backed when amount_cents present)."""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from typing import Any


def _ro(model):
    from utils.db_replica import using_analytics_bind

    return using_analytics_bind(model.query)


def monthly_revenue_series(*, months: int = 12) -> list[dict[str, Any]]:
    """Return last N months of recognized revenue from applied billing events."""
    from models import BillingEvent

    months = max(1, min(months, 36))
    events = (
        _ro(BillingEvent).filter(BillingEvent.status == 'applied')
        .filter(BillingEvent.amount_cents.isnot(None))
        .filter(BillingEvent.amount_cents > 0)
        .order_by(BillingEvent.created_at.asc())
        .all()
    )
    buckets: OrderedDict[str, dict] = OrderedDict()
    for ev in events:
        if not ev.created_at:
            continue
        key = ev.created_at.strftime('%Y-%m')
        if key not in buckets:
            buckets[key] = {'cents': 0, 'events': 0}
        buckets[key]['cents'] += int(ev.amount_cents or 0)
        buckets[key]['events'] += 1

    series = []
    for key, data in buckets.items():
        try:
            month_dt = datetime.strptime(key, '%Y-%m')
            label = month_dt.strftime('%b %Y')
        except ValueError:
            label = key
        mrr = round(data['cents'] / 100.0, 2)
        series.append({
            'month': label,
            'month_key': key,
            'mrr': mrr,
            'arr': round(mrr * 12, 2),
            'events': data['events'],
        })
    return series[-months:]


def recent_billing_events(*, limit: int = 25) -> list[dict[str, Any]]:
    from models import BillingEvent, Tenant

    limit = max(1, min(limit, 100))
    events = (
        _ro(BillingEvent).filter(BillingEvent.status == 'applied')
        .order_by(BillingEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for ev in events:
        tenant = _ro(Tenant).get(ev.tenant_id)
        out.append({
            'id': ev.id,
            'tenant_id': ev.tenant_id,
            'tenant_name': tenant.name if tenant else f'Tenant {ev.tenant_id}',
            'plan_id': ev.plan_id,
            'billing_cycle': ev.billing_cycle,
            'amount_cents': ev.amount_cents,
            'amount_usd': round((ev.amount_cents or 0) / 100.0, 2),
            'source': ev.source,
            'created_at': ev.created_at.isoformat() if ev.created_at else None,
        })
    return out
