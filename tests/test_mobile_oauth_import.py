import json

from app import oauth


def test_mobile_tokens_import_to_oauth_format(monkeypatch, tmp_path):
    target = tmp_path / "oauth_tokens.json"
    monkeypatch.setattr(oauth, "_OAUTH_FILE", target)
    monkeypatch.setattr(oauth, "_oauth_tokens", {})
    count = oauth.import_mobile_tokens(
        {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600, "obtained_at": 100},
        [{"id": "resume-a"}, {"id": "resume-b"}], {"id": "user"},
    )
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert count == 2
    assert set(saved) == {"resume-a", "resume-b"}
    assert saved["resume-a"]["source"] == "mobile_otp"
    assert saved["resume-a"]["refresh_token"] == "refresh"


def test_mobile_logout_preserves_other_tokens(monkeypatch, tmp_path):
    monkeypatch.setattr(oauth, "_OAUTH_FILE", tmp_path / "oauth_tokens.json")
    monkeypatch.setattr(oauth, "_oauth_tokens", {
        "mobile": {"source": "mobile_otp", "access_token": "a"},
        "legacy": {"access_token": "b"},
    })
    assert oauth.remove_mobile_tokens() == 1
    assert set(oauth._oauth_tokens) == {"legacy"}
