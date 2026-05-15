"""Tests for app.hh_chat._CHATIK_BASE env override."""

import pytest

try:
    from app.hh_chat import _CHATIK_BASE, send_negotiation_message
except ImportError as exc:
    pytest.skip(f"hh_chat helpers not available: {exc}", allow_module_level=True)


def test_chatik_base_default():
    assert _CHATIK_BASE == "https://chatik.hh.ru"


def test_chatik_base_env_override_allowed(monkeypatch):
    """HH_CHATIK_BASE из allowlist принимается (chatik.hh.kz — KZ зеркало)."""
    import importlib
    import os
    import app.hh_chat as hh_chat

    monkeypatch.setenv("HH_CHATIK_BASE", "https://chatik.hh.kz")
    importlib.reload(hh_chat)
    try:
        assert hh_chat._CHATIK_BASE == "https://chatik.hh.kz"
    finally:
        if "HH_CHATIK_BASE" in os.environ:
            del os.environ["HH_CHATIK_BASE"]
        importlib.reload(hh_chat)
        assert hh_chat._CHATIK_BASE == "https://chatik.hh.ru"


def test_chatik_base_env_unsafe_falls_back(monkeypatch):
    """HH_CHATIK_BASE=evil.com (НЕ в allowlist) → falls back to default."""
    import importlib
    import os
    import app.hh_chat as hh_chat

    monkeypatch.setenv("HH_CHATIK_BASE", "https://evil.com")
    importlib.reload(hh_chat)
    try:
        assert hh_chat._CHATIK_BASE == "https://chatik.hh.ru"
    finally:
        if "HH_CHATIK_BASE" in os.environ:
            del os.environ["HH_CHATIK_BASE"]
        importlib.reload(hh_chat)


def test_send_negotiation_message_url_respects_chatik_base(monkeypatch):
    import app.hh_chat as hh_chat

    calls = []

    class FakeResp:
        status_code = 200
        text = ""

    def fake_post(url, **kwargs):
        calls.append(url)
        return FakeResp()

    monkeypatch.setattr(hh_chat.requests, "post", fake_post)
    monkeypatch.setattr(hh_chat, "_ensure_chatik_cookies", lambda acc: None)

    acc = {"cookies": {"_xsrf": "x"}}
    send_negotiation_message(acc, "123", "hello")
    assert calls[0] == f"{hh_chat._CHATIK_BASE}/chatik/api/send"
