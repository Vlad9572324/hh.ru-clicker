from app import mobile_auth as auth_impl
from app.instances import bot
from app.routes import mobile_auth as route


class FakeMobileClient:
    def login(self, code):
        assert code == "1234"
        return (
            {"access_token": "oauth", "refresh_token": "refresh"},
            {"id": "user-1", "first_name": "Ada", "last_name": "Lovelace"},
            [{"id": "resume-1", "title": "Engineer"}],
        )

    def create_browser_cookies(self, token, me):
        return {"hhtoken": "web", "_xsrf": "csrf"}

    def collect_vacancies(self, *args, **kwargs):
        raise AssertionError("collect_vacancies must not run in verify hot-path")


def test_verify_materializes_session_and_reloads_bot(monkeypatch):
    saved = []
    old_sessions = list(bot.temp_sessions)
    monkeypatch.setattr(route, "HHMobileClient", FakeMobileClient)
    monkeypatch.setattr(route, "save_config", lambda values: {})
    monkeypatch.setattr(route, "import_mobile_tokens", lambda tokens, resumes, me: 1)
    monkeypatch.setattr(route, "clear_auth_state", lambda: None)
    monkeypatch.setattr("app.storage.load_browser_sessions", lambda: [])
    monkeypatch.setattr("app.storage.save_browser_sessions", lambda sessions, **kwargs: saved.append(list(sessions)))
    try:
        result = route._verify_code(route.VerifyBody(code="1234"))
        assert result["ok"] is True
        assert result["browser_sessions_updated"] == 1
        assert result["vacancies_deferred"] is True
        assert saved and saved[0][0]["resume_hash"] == "resume-1"
        assert bot.temp_sessions and bot.temp_sessions[0]["resume_hash"] == "resume-1"
    finally:
        bot.temp_sessions[:] = old_sessions


def test_upsert_failure_is_explicit_verify_error(monkeypatch):
    monkeypatch.setattr(route, "HHMobileClient", FakeMobileClient)
    monkeypatch.setattr(route, "save_config", lambda values: {})
    monkeypatch.setattr(route, "import_mobile_tokens", lambda tokens, resumes, me: 1)
    monkeypatch.setattr(
        route, "upsert_browser_sessions",
        lambda *args: (_ for _ in ()).throw(auth_impl.MobileAuthError("disk unavailable")),
    )

    try:
        route._verify_code(route.VerifyBody(code="1234"))
    except auth_impl.MobileAuthError as exc:
        assert "аккаунт не добавлен" in str(exc)
        assert "disk unavailable" in str(exc)
    else:
        raise AssertionError("verify must fail when a browser session cannot be saved")
