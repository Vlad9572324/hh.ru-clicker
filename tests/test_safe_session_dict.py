"""Tests for _safe_session_dict redaction helper."""
from app.routes.debug import _safe_session_dict


def test_removes_cookies():
    result = _safe_session_dict({"cookies": "secret", "name": "n"})
    assert "cookies" not in result
    assert "name" in result


def test_removes_raw_cookie_line():
    result = _safe_session_dict({"_raw_cookie_line": "secret"})
    assert "_raw_cookie_line" not in result


def test_removes_api_key():
    result = _safe_session_dict({"api_key": "secret"})
    assert "api_key" not in result


def test_preserves_other_fields():
    data = {"name": "n", "short": "s", "other": 1}
    assert _safe_session_dict(data) == data
