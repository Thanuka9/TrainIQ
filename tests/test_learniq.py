"""LearnIQ / Ollama status and cache tests (mocked — no live Ollama required)."""
from unittest.mock import patch

from utils import ai_cache
from utils.local_ai import get_ai_status, is_available, list_installed_models


def test_get_ai_status_offline():
    with patch("utils.local_ai.list_installed_models", return_value=[]), patch(
        "utils.local_ai._ping_base", return_value=False
    ):
        status = get_ai_status()
    assert status["available"] is False
    assert status["engine"] == "ollama"
    assert "Ollama" in status["message"]


def test_get_ai_status_online_with_model():
    with patch("utils.local_ai.list_installed_models", return_value=["gemma4:e4b"]), patch(
        "utils.local_ai.resolve_model", return_value="gemma4:e4b"
    ):
        status = get_ai_status()
    assert status["available"] is True
    assert status["model_ready"] is True
    assert status["resolved_model"] == "gemma4:e4b"


def test_is_available_follows_status():
    with patch("utils.local_ai.get_ai_status", return_value={"available": True, "model_ready": True}):
        assert is_available() is True
    with patch("utils.local_ai.get_ai_status", return_value={"available": False, "model_ready": False}):
        assert is_available() is False


def test_ai_cache_roundtrip():
    key = ai_cache.make_key("summarize", 99999, "file-test", 2, "pdf", 0, "gemma4:e4b")
    cache_path = __import__("os").path.join(ai_cache.CACHE_DIR, f"{key}.json")
    if __import__("os").path.isfile(cache_path):
        __import__("os").remove(cache_path)
    assert ai_cache.get(key) is None
    ai_cache.set(key, {"summary": "Hello world"})
    cached = ai_cache.get(key)
    assert cached["summary"] == "Hello world"
    __import__("os").remove(cache_path)


def test_list_installed_models_cached(monkeypatch):
    monkeypatch.setattr("utils.local_ai._MODEL_CACHE", {"installed": None, "resolved": None})
    calls = {"n": 0}

    def fake_tags(*args, **kwargs):
        calls["n"] += 1
        class R:
            status_code = 200
            def json(self):
                return {"models": [{"name": "gemma4:e4b"}]}
        return R()

    with patch("utils.local_ai.requests.get", side_effect=fake_tags):
        first = list_installed_models(refresh=True)
        second = list_installed_models()
    assert first == ["gemma4:e4b"]
    assert second == first
    assert calls["n"] == 1
