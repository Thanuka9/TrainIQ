"""Service split configuration — run LMS web, platform web, or full monolith."""
from __future__ import annotations

import os

# full | web (tenant LMS + admin, no /platform) | platform (/platform + support enter)
VALID_MODES = frozenset({'full', 'web', 'platform'})


def service_mode() -> str:
    mode = (os.getenv('SERVICE_MODE') or 'full').strip().lower()
    return mode if mode in VALID_MODES else 'full'


def register_platform_blueprints() -> bool:
    return service_mode() in ('full', 'platform')


def register_lms_blueprints() -> bool:
    return service_mode() in ('full', 'web')


def register_support_admin_blueprints() -> bool:
    """Auth + tenant admin when running platform-only workers (support enter)."""
    return service_mode() == 'platform'


def is_ops_worker_process() -> bool:
    return (os.getenv('OPS_WORKER_MODE') or '').lower() in ('1', 'true', 'yes')


def event_bus_consumer_enabled() -> bool:
    explicit = (os.getenv('EVENT_BUS_CONSUMER') or '').strip().lower()
    if explicit in ('1', 'true', 'yes'):
        return True
    if explicit in ('0', 'false', 'no'):
        return False
    return is_ops_worker_process()
