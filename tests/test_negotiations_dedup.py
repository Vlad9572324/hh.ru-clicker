"""Tests for interview pagination dedup in fetch_hh_negotiations_stats."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.hh_negotiations import fetch_hh_negotiations_stats
import app.hh_negotiations as hh_neg

_INTERVIEW_HTML = (
    '<div data-qa="negotiations-item" class="item">'
    '<span>"chatId": 99999</span>'
    '<time datetime="2024-01-15T10:00:00+03:00"></time>'
    'Interview text'
    '</div>'
)


def _mock_get(url, **kwargs):
    r = MagicMock()
    if "state=INTERVIEW" in url:
        r.status_code = 200
        r.text = _INTERVIEW_HTML
    else:
        r.status_code = 404
        r.text = ""
    return r


def test_interview_dedup_does_not_double_count(monkeypatch):
    # Граница моков — HH (код ушёл с requests.get на HH.get)
    monkeypatch.setattr(hh_neg, "HH", SimpleNamespace(get=_mock_get))
    result = fetch_hh_negotiations_stats({"cookies": {}})
    assert result["interview"] == 1
    assert result["auth_error"] is False
