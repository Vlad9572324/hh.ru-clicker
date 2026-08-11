from app.mobile_auth import upsert_browser_sessions


def test_otp_three_resumes_creates_one_session(monkeypatch):
    saved = []
    monkeypatch.setattr("app.storage.load_browser_sessions", lambda: [])
    monkeypatch.setattr("app.storage.save_browser_sessions", lambda value, **kw: saved.append(value))
    count = upsert_browser_sessions(
        {"hhtoken": "token", "_xsrf": "csrf"},
        {"id": "user-7", "first_name": "Ada"},
        [{"id": f"r{i}", "title": f"Resume {i}"} for i in range(3)],
    )
    assert count == 1
    assert len(saved[-1]) == 1
    assert saved[-1][0]["user_id"] == "user-7"
    assert saved[-1][0]["resume_hash"] == "r0"
    assert [r["hash"] for r in saved[-1][0]["all_resumes"]] == ["r0", "r1", "r2"]


def test_relogin_preserves_active_resume(monkeypatch):
    sessions = [{"user_id": "u", "resume_hash": "r2", "all_resumes": [{"hash": "r2", "title": "Two"}]}]
    saved = []
    monkeypatch.setattr("app.storage.load_browser_sessions", lambda: sessions)
    monkeypatch.setattr("app.storage.save_browser_sessions", lambda value, **kw: saved.append(value))
    upsert_browser_sessions({"hhtoken": "t", "_xsrf": "x"}, {"id": "u"},
                            [{"id": "r1", "title": "One"}, {"id": "r2", "title": "Two"}])
    assert len(saved[-1]) == 1
    assert saved[-1][0]["resume_hash"] == "r2"
