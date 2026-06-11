"""PII-safe logging helpers."""
import re


def mask_email(email):
    if not email or "@" not in str(email):
        return "***"
    local, domain = str(email).split("@", 1)
    if len(local) <= 1:
        return f"*@{domain}"
    return f"{local[0]}***@{domain}"


def safe_user_ref(user):
    if user is None:
        return "user:unknown"
    return f"user_id={getattr(user, 'id', '?')}"


def scrub_pii(text):
    if not text:
        return text
    return re.sub(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        lambda m: mask_email(m.group(0)),
        str(text),
    )
