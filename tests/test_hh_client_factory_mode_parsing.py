"""Tests for P2 finding: get_client must not crash on non-string account["mode"].

Не-строковые mode (int/bool/None) и неизвестные строки не должны ронять
factory с AttributeError — только устойчивый fallback (auto → web без токена,
unknown → CONFIG.default_client_mode → "web").
"""
import pytest

from app import oauth
from app.config import CONFIG
from app.hh_client_fallback import FallbackHHClient
from app.hh_client_factory import get_client
from app.hh_client_mobile import MobileHHClient
from app.hh_client_web import WebHHClient


@pytest.fixture
def deterministic_env(monkeypatch):
    """Изолировать factory: default="web", OAuth-токенов нет."""
    monkeypatch.setattr(CONFIG, "default_client_mode", "web")
    monkeypatch.setattr(oauth, "_oauth_tokens", {})
    monkeypatch.setattr(oauth, "get_oauth_status", lambda resume_hash: {})
    return monkeypatch


def _account(mode):
    return {"name": "a1", "cookies": {}, "resume_hash": "rh1", "mode": mode}


def test_mode_int_does_not_crash_and_falls_back_to_web(deterministic_env):
    client = get_client(_account(1))  # раньше: AttributeError на (1).strip()
    assert isinstance(client, WebHHClient)


def test_mode_bool_does_not_crash_and_falls_back_to_web(deterministic_env):
    client = get_client(_account(True))  # раньше: AttributeError на True.strip()
    assert isinstance(client, WebHHClient)


def test_mode_none_falls_back_to_web(deterministic_env):
    client = get_client(_account(None))
    assert isinstance(client, WebHHClient)


def test_mode_unknown_string_uses_default_web(deterministic_env):
    client = get_client(_account("desktop"))
    assert isinstance(client, WebHHClient)


def test_mode_whitespace_and_case_is_normalized_to_mobile(deterministic_env):
    client = get_client(_account("  MOBILE  "))
    # Phase 2: mode=mobile → FallbackHHClient поверх MobileHHClient.
    assert isinstance(client, FallbackHHClient)
    assert isinstance(client.mobile, MobileHHClient)


def test_mode_missing_field_uses_default_web(deterministic_env):
    acc = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
    client = get_client(acc)
    assert isinstance(client, WebHHClient)


def test_mode_explicit_web_string(deterministic_env):
    client = get_client(_account("web"))
    assert isinstance(client, WebHHClient)
