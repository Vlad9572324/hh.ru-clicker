"""Tests for interview pagination dedup in fetch_hh_negotiations_stats."""
from unittest.mock import patch, MagicMock

from app.hh_negotiations import fetch_hh_negotiations_stats

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


def test_interview_dedup_does_not_double_count():
    with patch("app.hh_negotiations.requests.get", side_effect=_mock_get):
        result = fetch_hh_negotiations_stats({"cookies": {}})
    assert result["interview"] == 1
    assert result["auth_error"] is False
