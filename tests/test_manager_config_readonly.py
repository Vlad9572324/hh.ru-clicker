"""Regression: восстановление сессий при старте не пишет config.json."""

from app import manager as manager_module


def test_build_session_urls_does_not_mutate_or_save_global_config(monkeypatch):
    pool = [
        {"url": "https://hh.ru/search/vacancy?text=python", "pages": 1},
        # Сохранённый resume URL другого аккаунта не должен использоваться.
        {"url": "https://hh.ru/search/vacancy?resume=other", "pages": 2},
    ]
    monkeypatch.setattr(manager_module.CONFIG, "url_pool", pool)
    monkeypatch.setattr(manager_module.CONFIG, "pages_per_url", 7)

    save_calls = []
    monkeypatch.setattr(manager_module, "save_config", lambda: save_calls.append(True))
    before = [dict(item) for item in pool]

    mgr = manager_module.BotManager.__new__(manager_module.BotManager)
    urls = mgr._build_session_urls("resume-123")

    assert urls == [
        "https://hh.ru/search/vacancy?resume=resume-123"
        "&area=113&order_by=publication_time&items_on_page=20",
        "https://hh.ru/search/vacancy?text=python",
    ]
    assert pool == before
    assert save_calls == []


def test_build_session_urls_reuses_matching_resume_search_preferences(monkeypatch):
    preferred = (
        "https://hh.ru/search/vacancy?resume=resume-123&area=2&text=python"
        "&professional_role=96&order_by=publication_time"
    )
    monkeypatch.setattr(manager_module.CONFIG, "url_pool", [
        {"url": preferred, "pages": 1},
        {"url": "https://hh.ru/search/vacancy?resume=other&area=1", "pages": 9},
    ])

    mgr = manager_module.BotManager.__new__(manager_module.BotManager)

    assert mgr._build_session_urls("resume-123") == [preferred]
