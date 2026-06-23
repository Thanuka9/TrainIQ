"""Tests for platform support-mode session TTL."""
from datetime import datetime, timedelta

from utils.support_session import support_session_expired


class _Session(dict):
    def get(self, key, default=None):
        return super().get(key, default)

    def pop(self, key, default=None):
        return super().pop(key, default)


def test_support_session_not_expired_within_ttl(monkeypatch):
    monkeypatch.setenv('PLATFORM_SUPPORT_TTL_HOURS', '2')
    import utils.support_session as mod
    from importlib import reload
    reload(mod)

    started = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    sess = _Session({'platform_support': True, mod.SESSION_STARTED_KEY: started})
    monkeypatch.setattr(mod, 'session', sess)
    assert mod.support_session_expired() is False


def test_support_session_expired_after_ttl(monkeypatch):
    monkeypatch.setenv('PLATFORM_SUPPORT_TTL_HOURS', '1')
    import utils.support_session as mod
    from importlib import reload
    reload(mod)

    started = (datetime.utcnow() - timedelta(hours=3)).isoformat()
    sess = _Session({'platform_support': True, mod.SESSION_STARTED_KEY: started})
    monkeypatch.setattr(mod, 'session', sess)
    assert mod.support_session_expired() is True
