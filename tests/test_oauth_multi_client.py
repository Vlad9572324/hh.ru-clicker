"""Tests for OAuth multi-client fallback."""

import pytest

try:
    from app.oauth import _HH_OAUTH_CLIENT_ID_2, _do_refresh, _obtain_oauth_token
except ImportError as exc:
    pytest.skip(f"OAuth helpers not available: {exc}", allow_module_level=True)


def test_oauth_client_id_2_env_loads(monkeypatch):
    import importlib
    import os
    import app.oauth as oauth

    monkeypatch.setenv("HH_OAUTH_CLIENT_ID_2", "MY_SECOND_ID")
    importlib.reload(oauth)
    try:
        assert oauth._HH_OAUTH_CLIENT_ID_2 == "MY_SECOND_ID"
    finally:
        if "HH_OAUTH_CLIENT_ID_2" in os.environ:
            del os.environ["HH_OAUTH_CLIENT_ID_2"]
        importlib.reload(oauth)


def test_do_refresh_returns_none_on_invalid_client(monkeypatch):
    from unittest.mock import MagicMock
    import app.oauth as oauth

    fake_resp = MagicMock(status_code=400, json=lambda: {"error": "invalid_client"})
    monkeypatch.setattr(oauth.requests, "post", lambda *a, **kw: fake_resp)
    result = _do_refresh("refresh_token", "client_id", "secret", "ua")
    assert result is None


def test_fallback_kicks_in_on_primary_invalid_client(monkeypatch):
    from unittest.mock import MagicMock
    import app.oauth as oauth

    # Avoid disk writes during test
    monkeypatch.setattr(oauth, "_save_oauth_tokens", lambda: None)

    # Clean state
    with oauth._oauth_lock:
        oauth._oauth_tokens.clear()

    monkeypatch.setattr(oauth, "_HH_OAUTH_CLIENT_ID_2", "SECONDARY_ID")
    monkeypatch.setattr(oauth, "_HH_OAUTH_CLIENT_SECRET_2", "SECONDARY_SECRET")

    acc = {"resume_hash": "abc123", "cookies": {"hhtoken": "tok123"}}
    key = oauth._token_key(acc)

    with oauth._oauth_lock:
        oauth._oauth_tokens[key] = {
            "access_token": "old",
            "refresh_token": "ref123",
            "expires_at": 0,
        }

    calls = []

    def fake_post(url, **kwargs):
        data = kwargs.get("data", {})
        calls.append({
            "client_id": data.get("client_id"),
            "client_secret": data.get("client_secret"),
        })
        if len(calls) == 1:
            return MagicMock(status_code=400, json=lambda: {"error": "invalid_client"})
        return MagicMock(
            status_code=200,
            json=lambda: {
                "access_token": "new_token",
                "refresh_token": "new_refresh",
                "expires_in": 3600,
            },
        )

    monkeypatch.setattr(oauth.requests, "post", fake_post)

    try:
        token = _obtain_oauth_token(acc)
        assert token == "new_token"
        assert len(calls) == 2
        assert calls[0]["client_id"] == oauth._HH_OAUTH_CLIENT_ID
        assert calls[1]["client_id"] == "SECONDARY_ID"
    finally:
        with oauth._oauth_lock:
            oauth._oauth_tokens.pop(key, None)
            oauth._oauth_tokens.pop(acc["resume_hash"], None)
