from datetime import datetime, timedelta, timezone

from app import oauth


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_today_count_does_not_count_old_items_when_tzdata_is_unavailable(monkeypatch):
    msk = timezone(timedelta(hours=3))
    now = datetime.now(msk)
    old = now - timedelta(days=2)
    pages = [
        _Response({
            "found": 500,
            "items": [
                {"created_at": now.isoformat()},
                {"created_at": old.isoformat()},
            ],
        }),
    ]

    monkeypatch.setattr(oauth, "_oauth_headers", lambda acc: {"Authorization": "Bearer token"})
    monkeypatch.setattr(oauth.HH, "get", lambda *args, **kwargs: pages.pop(0))
    oauth._negotiations_count_cache.clear()

    result = oauth.fetch_negotiations_today_count({"resume_hash": "tz-regression"})

    assert result["today"] == 1
    assert result["total_found"] == 500
