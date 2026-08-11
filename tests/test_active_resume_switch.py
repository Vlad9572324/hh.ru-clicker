import asyncio
from types import SimpleNamespace

from app.config import accounts_data
from app.instances import bot
from app.routes.accounts import api_account_active_resume


class Request:
    async def json(self):
        return {"resume_hash": "r2"}


def test_put_switches_temp_active_resume(monkeypatch):
    old_accounts, old_sessions, old_states = list(bot.account_states), list(bot.temp_sessions), dict(bot.temp_states)
    saved = []
    try:
        bot.account_states[:] = []
        bot.temp_sessions[:] = [{"resume_hash": "r1", "all_resumes": [{"hash": "r1"}, {"hash": "r2"}]}]
        bot.temp_states.clear()
        bot.temp_states[0] = SimpleNamespace(acc={"resume_hash": "r1"})
        monkeypatch.setattr("app.routes.accounts.save_browser_sessions", lambda value: saved.append(value))
        result = asyncio.run(api_account_active_resume(0, Request()))
        assert result == {"ok": True, "resume_hash": "r2"}
        assert bot.temp_sessions[0]["resume_hash"] == "r2"
        assert bot.temp_states[0].acc["resume_hash"] == "r2"
        assert saved
    finally:
        bot.account_states[:] = old_accounts
        bot.temp_sessions[:] = old_sessions
        bot.temp_states.clear(); bot.temp_states.update(old_states)


def test_put_rejects_foreign_resume():
    class BadRequest:
        async def json(self): return {"resume_hash": "foreign"}
    old_accounts, old_sessions = list(bot.account_states), list(bot.temp_sessions)
    try:
        bot.account_states[:] = []
        bot.temp_sessions[:] = [{"resume_hash": "r1", "all_resumes": [{"hash": "r1"}]}]
        result = asyncio.run(api_account_active_resume(0, BadRequest()))
        assert result["ok"] is False
        assert bot.temp_sessions[0]["resume_hash"] == "r1"
    finally:
        bot.account_states[:] = old_accounts
        bot.temp_sessions[:] = old_sessions
