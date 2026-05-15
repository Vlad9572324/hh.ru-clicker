"""Tests for app.hh_apply._with_retry."""
from unittest.mock import MagicMock
import app.hh_apply as ha


def _resp(status):
    r = MagicMock()
    r.status_code = status
    return r


def test_success_no_retry():
    fn = ha._with_retry(lambda: _resp(200))
    assert fn().status_code == 200


def test_503_once_then_ok(monkeypatch):
    monkeypatch.setattr("app.hh_apply.time.sleep", lambda *a: None)
    calls = []
    def side():
        calls.append(1)
        return _resp(503) if len(calls) == 1 else _resp(200)
    assert ha._with_retry(side)().status_code == 200
    assert len(calls) == 2


def test_connerror_then_ok(monkeypatch):
    monkeypatch.setattr("app.hh_apply.time.sleep", lambda *a: None)
    calls = []
    def side():
        calls.append(1)
        if len(calls) == 1:
            raise ha.requests.ConnectionError("boom")
        return _resp(200)
    assert ha._with_retry(side)().status_code == 200
    assert len(calls) == 2


def test_502_always_returns_after_retries(monkeypatch):
    monkeypatch.setattr("app.hh_apply.time.sleep", lambda *a: None)
    calls = []
    def side():
        calls.append(1)
        return _resp(502)
    assert ha._with_retry(side)().status_code == 502
    assert len(calls) == 4
