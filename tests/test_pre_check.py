"""Тесты на _check_vacancy_before_apply — фикс H1 + retry distinction.

Защищает:
- H1: fail-closed на 401/403/non-200/parse-error/exception
- swarm-9 #10: 5xx → retry, 4xx → permanent skip
"""
from unittest.mock import patch, MagicMock

from app.hh_apply import _check_vacancy_before_apply


def _mock_resp(status=200, text="", json_data=None):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json = MagicMock(return_value=json_data) if json_data is not None else MagicMock(side_effect=ValueError())
    r.headers = {}
    return r


def test_h1_401_returns_auth_error():
    with patch("app.hh_apply.requests.get", return_value=_mock_resp(401)):
        result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["ok"] is False
    assert result["reason"] == "auth_error"
    assert result["skip_reason"] == "auth"


def test_h1_403_login_page_returns_auth_error():
    html = '<html>Войти в аккаунт</html>'
    with patch("app.hh_apply.requests.get", return_value=_mock_resp(200, html)):
        result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["reason"] == "auth_error"


def test_h1_429_returns_retry_not_skip():
    """Rate-limit ≠ permanent skip."""
    with patch("app.hh_apply.requests.get", return_value=_mock_resp(429, "")):
        result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["skip_reason"] == "retry"


def test_h1_502_returns_retry_not_skip():
    """5xx ≠ permanent skip."""
    with patch("app.hh_apply.requests.get", return_value=_mock_resp(502, "")):
        result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["skip_reason"] == "retry"


def test_h1_404_returns_permanent_skip():
    """4xx other → permanent skip."""
    with patch("app.hh_apply.requests.get", return_value=_mock_resp(404, "Not found")):
        result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["skip_reason"] == "skip"


def test_h1_bad_json_fails_closed():
    """Невалидный JSON → не пропускаем (fail-closed)."""
    r = _mock_resp(200, "<html>not json</html>")
    with patch("app.hh_apply.requests.get", return_value=r):
        result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["ok"] is False
    assert result["reason"] == "bad_json"


def test_h1_exception_fails_closed():
    """Network error → не пропускаем (fail-closed)."""
    with patch("app.hh_apply.requests.get", side_effect=ConnectionError("net")):
        result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["ok"] is False
    assert result["skip_reason"] == "exception"


def test_h1_response_impossible_returns_not_ok():
    json_data = {"responseStatus": {"responseImpossible": True, "responseImpossibleReason": "blacklist"}}
    with patch("app.hh_apply.requests.get", return_value=_mock_resp(200, '{"foo":1}', json_data)):
        result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["ok"] is False
    assert result["reason"] == "blacklist"


def test_h1_clean_200_ok():
    json_data = {"responseStatus": {"shortVacancy": {"name": "Dev"}}}
    with patch("app.hh_apply.requests.get", return_value=_mock_resp(200, '{"x":1}', json_data)):
        result = _check_vacancy_before_apply({"cookies": {}}, "123")
    assert result["ok"] is True
