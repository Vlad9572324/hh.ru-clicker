from app import oauth


class _Response:
    status_code = 200

    @staticmethod
    def json():
        return {
            "status": {"id": "published", "name": "Опубликовано"},
            "blocked": False,
            "can_publish_or_update": True,
            "next_publish_at": "2026-08-10T00:00:00+0300",
            "progress": {"percentage": 87},
            "moderation_note": [{"name": "Проверено"}],
        }


def test_fetch_resume_status_uses_android_resume_endpoint(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(oauth, "_oauth_headers", lambda acc: {"Authorization": "Bearer token"})
    monkeypatch.setattr(oauth, "_extras_get", lambda kind, key, ttl, loader: loader())
    monkeypatch.setattr(oauth.HH, "get", fake_get)

    result = oauth.fetch_resume_status({"resume_hash": "resume/id"})

    assert captured["url"] == "https://api.hh.ru/resumes/resume%2Fid"
    assert captured["params"] == {"with_professional_roles": "true", "with_creds": "true"}
    assert result["status_id"] == "published"
    assert result["progress"] == 87
    assert result["can_publish_or_update"] is True
