from types import SimpleNamespace

from app.manager import BotManager, _uses_api_search, parse_search_url


def test_parse_search_url_preserves_resume_and_multivalue_filters():
    text, area, filters = parse_search_url(
        "https://hh.ru/search/vacancy?resume=r1&text=python&area=2"
        "&professional_role=1&professional_role=2&items_on_page=20&page=3"
    )

    assert text == "python"
    assert area == "2"
    assert filters == {"resume": "r1", "professional_role": ["1", "2"]}


def test_parse_search_url_defaults_to_all_russia():
    text, area, filters = parse_search_url(
        "https://hh.ru/search/vacancy?resume=r1&order_by=publication_time"
    )

    assert text == ""
    assert area == 113
    assert filters == {"resume": "r1", "order_by": "publication_time"}


def test_mobile_resume_search_uses_exact_web_url_with_live_cookies():
    state = SimpleNamespace(cookies_expired=False, degraded_fallback_enabled=False)

    assert _uses_api_search({
        "mode": " mobile ",
        "urls": ["https://hh.ru/search/vacancy?resume=r1&area=113"],
    }, state) is False
    assert _uses_api_search({
        "mode": "mobile",
        "urls": ["https://hh.ru/search/vacancy?text=python&area=113"],
    }, state) is True
    assert _uses_api_search({"mode": "web", "resume_hash": "r1"}, state) is False


def test_mobile_resume_search_does_not_fall_back_to_incorrect_api_when_cookies_dead():
    state = SimpleNamespace(cookies_expired=True, degraded_fallback_enabled=True)

    assert _uses_api_search({
        "mode": "mobile", "resume_hash": "r1",
        "urls": ["https://hh.ru/search/vacancy?resume=r1&area=113"],
    }, state) is True


def test_api_collector_skips_unsupported_resume_filter(monkeypatch):
    url = "https://hh.ru/search/vacancy?resume=r1&area=113"
    acc = {"mode": "mobile", "urls": [url], "url_pages": {url: 1}}
    state = SimpleNamespace(
        acc=acc, _deleted=False, short="M", status_detail="", vacancy_meta={}
    )
    calls = []
    monkeypatch.setattr(
        "app.manager.get_client",
        lambda account: SimpleNamespace(
            search_vacancies=lambda *args, **kwargs: calls.append(1) or []
        ),
    )

    results, _, _ = BotManager.__new__(BotManager)._collect_via_oauth_api(state)

    assert results == {url: set()}
    assert calls == []


def test_api_collector_routes_url_through_selected_client(monkeypatch):
    url = "https://hh.ru/search/vacancy?resume=r1&text=python&area=2&schedule=remote"
    acc = {"mode": "mobile", "urls": [url], "url_pages": {url: 1}}
    state = SimpleNamespace(
        acc=acc, _deleted=False, short="M", status_detail="", vacancy_meta={}
    )
    calls = []
    client = SimpleNamespace(
        search_vacancies=lambda *args, **kwargs: calls.append((args, kwargs)) or [
            {"id": "42", "name": "Dev", "employer": {"id": "7", "name": "ACME"}}
        ]
    )
    monkeypatch.setattr("app.manager.get_client", lambda account: client)

    results, _, _ = BotManager.__new__(BotManager)._collect_via_oauth_api(state)

    assert results == {url: {"42"}}
    assert calls == [(('python',), {
        "area_id": "2", "per_page": 50, "page": 0,
        "filters": {"resume": "r1", "schedule": "remote"},
        "max_pages": 1,
    })]
