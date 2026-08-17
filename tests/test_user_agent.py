from types import SimpleNamespace

from app import mobile_auth, user_agent


def test_mobile_user_agent_uses_config_and_strips_non_ascii(monkeypatch):
    user_agent.invalidate_mobile_user_agent_cache()
    cfg = SimpleNamespace(user_agent="ru.hh.android/1.2.3, Device: Pixel Тест")
    monkeypatch.setattr(mobile_auth, "effective_config", lambda: (cfg, {}))

    assert user_agent.mobile_user_agent() == "ru.hh.android/1.2.3, Device: Pixel "
    user_agent.invalidate_mobile_user_agent_cache()


def test_webview_user_agent_keeps_desktop_identity():
    assert user_agent.webview_user_agent("Browser/1 Тест") == "Browser/1"
    assert "Windows NT" in user_agent.webview_user_agent()
    assert "ru.hh.android" not in user_agent.webview_user_agent()
