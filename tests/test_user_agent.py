from types import SimpleNamespace

from app import mobile_auth, user_agent


def test_mobile_user_agent_uses_config_and_strips_non_ascii(monkeypatch):
    cfg = SimpleNamespace(user_agent="ru.hh.android/1.2.3, Device: Pixel Тест")
    monkeypatch.setattr(mobile_auth, "effective_config", lambda: (cfg, {}))

    assert user_agent.mobile_user_agent() == "ru.hh.android/1.2.3, Device: Pixel "


def test_webview_user_agent_appends_mobile_identity(monkeypatch):
    monkeypatch.setattr(user_agent, "mobile_user_agent", lambda: "ru.hh.android/mobile")

    assert user_agent.webview_user_agent("Browser/1") == "Browser/1 ru.hh.android/mobile"
