"""Shared branding helpers for templates and exports."""


def resolve_display_brand(tenant):
    """Return (display_name, is_platform_brand, org_initial) for templates."""
    if not tenant:
        return 'TrainIQ', True, 'T'
    name = (tenant.name or '').strip()
    if not name or name.lower() in ('trainiq', 'default'):
        return 'TrainIQ', True, 'T'
    return name, False, name[0].upper()
