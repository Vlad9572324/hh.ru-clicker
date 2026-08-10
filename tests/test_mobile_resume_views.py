"""Тесты Phase 4: mobile-история просмотров резюме
(app/mobile_resume_views.py::fetch_resume_view_history).

Конвенция tests/test_mobile_phase2_integration.py: никаких живых HTTP —
все URL api.hh.ru перехвачены библиотекой `responses`; Bearer-токен
подменён через monkeypatch app.oauth._obtain_oauth_token; ACC — аккаунт
с resume_hash.

Контракт (докстринг app/mobile_resume_views.py):
    fetch_resume_view_history(acc, resume_id=None, limit=50) ->
        {"items": [{"employer_id", "name", "viewed_at", "viewed"}, ...],
         "total": found}
Политика ошибок: fallback-статусы (0/401/403/5xx) → MobileAPIError;
прочие не-2xx (404 и т.п.) → {"items": [], "total": 0} без исключения.
"""
from urllib.parse import parse_qsl, urlparse

import pytest
import responses

from app import oauth
from app.hh_client_mobile import MobileHHClient
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}

VIEWS_URL_RH1 = MOBILE_BASE + "/resumes/rh1/views"


@pytest.fixture
def oauth_token(monkeypatch):
    """Bearer-токен добывается через app.oauth._obtain_oauth_token —
    подменяем, чтобы не идти в реальный OAuth-flow."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")


def _query(req) -> dict:
    """Query-параметры запроса как dict (точная проверка page/per_page)."""
    return dict(parse_qsl(urlparse(req.url).query))


def _assert_bearer(req):
    assert req.headers["Authorization"] == "Bearer t"
    # мобильные заголовки транспорта (контракт APK)
    assert req.headers["x-force-app-access"] == "true"


def _view_item(employer_id, name, created_at, viewed):
    """Элемент ленты просмотров в live-форме (apidocs_group_2.yaml,
    live 2026-08-10): created_at/viewed + employer{...}."""
    return {
        "created_at": created_at,
        "viewed": viewed,
        "employer": {
            "id": employer_id,
            "name": name,
            "url": f"https://api.hh.ru/employers/{employer_id}",
            "alternate_url": f"https://hh.ru/employer/{employer_id}",
            "logo_urls": {"original": None},
            "vacancies_url": f"https://hh.ru/employer/{employer_id}/vacancies",
        },
    }


def _views_page(items, found, pages, page, per_page=20):
    """Конверт ответа GET /resumes/{id}/views — live-форма."""
    return {
        "items": items,
        "found": found,
        "pages": pages,
        "page": page,
        "per_page": per_page,
        "resume": {"id": "rh1", "first_name": {"name": "Иван"}},
    }


# ---------------------------------------------------------------------------
# 1. Happy-path: одна страница, маппинг элементов, URL и заголовки
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_resume_view_history_happy_path_single_page(oauth_token):
    from app.mobile_resume_views import fetch_resume_view_history

    responses.add(responses.GET, VIEWS_URL_RH1, json=_views_page(
        items=[
            _view_item("11583314", "Глобал Сервис",
                       "2026-08-10T10:33:00+0300", False),
            _view_item("99", "Ромашка", "2026-08-09T09:00:00+0300", True),
        ],
        found=2, pages=1, page=0,
    ), status=200)

    result = fetch_resume_view_history(ACC)

    assert result["total"] == 2
    assert result["items"] == [
        {"employer_id": "11583314", "name": "Глобал Сервис",
         "viewed_at": "2026-08-10T10:33:00+0300", "viewed": False},
        {"employer_id": "99", "name": "Ромашка",
         "viewed_at": "2026-08-09T09:00:00+0300", "viewed": True},
    ]

    assert len(responses.calls) == 1  # pages=1 → вторая страница не нужна
    req = responses.calls[0].request
    assert req.method == "GET"
    assert req.url.split("?")[0] == VIEWS_URL_RH1
    q = _query(req)
    assert q.get("page") == "0"
    assert q.get("per_page") == "50"  # дефолт limit=50
    _assert_bearer(req)


# ---------------------------------------------------------------------------
# 2. Пагинация: found=3, pages=2 — два запроса page=0 и page=1
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_resume_view_history_pagination_two_pages(oauth_token):
    from app.mobile_resume_views import fetch_resume_view_history

    responses.add(responses.GET, VIEWS_URL_RH1, json=_views_page(
        items=[
            _view_item("1", "Альфа", "2026-08-10T10:00:00+0300", False),
            _view_item("2", "Бета", "2026-08-10T09:00:00+0300", True),
        ],
        found=3, pages=2, page=0, per_page=2,
    ), status=200)
    responses.add(responses.GET, VIEWS_URL_RH1, json=_views_page(
        items=[_view_item("3", "Гамма", "2026-08-09T08:00:00+0300", False)],
        found=3, pages=2, page=1, per_page=2,
    ), status=200)

    result = fetch_resume_view_history(ACC)  # limit=50 → все 3 элемента

    assert [it["employer_id"] for it in result["items"]] == ["1", "2", "3"]
    assert result["total"] == 3
    assert len(responses.calls) == 2
    assert _query(responses.calls[0].request).get("page") == "0"
    assert _query(responses.calls[1].request).get("page") == "1"


# ---------------------------------------------------------------------------
# 3. Обрезка по limit: limit=1 → один элемент, total остаётся found
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_resume_view_history_limit_truncates(oauth_token):
    from app.mobile_resume_views import fetch_resume_view_history

    responses.add(responses.GET, VIEWS_URL_RH1, json=_views_page(
        items=[
            _view_item("1", "Альфа", "2026-08-10T10:00:00+0300", False),
            _view_item("2", "Бета", "2026-08-10T09:00:00+0300", True),
        ],
        found=3, pages=2, page=0, per_page=2,
    ), status=200)

    result = fetch_resume_view_history(ACC, limit=1)

    assert len(result["items"]) == 1
    assert result["items"][0]["employer_id"] == "1"
    assert result["total"] == 3  # total = found, а не размер обрезки
    assert len(responses.calls) == 1  # за второй страницей не идём
    assert _query(responses.calls[0].request).get("per_page") == "1"


# ---------------------------------------------------------------------------
# 4. Политика ошибок: 404 → пустой результат; 401/500 → MobileAPIError
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_resume_view_history_404_empty_result(oauth_token):
    from app.mobile_resume_views import fetch_resume_view_history

    responses.add(responses.GET, VIEWS_URL_RH1,
                  json={"errors": [{"value": "resume_not_found"}]},
                  status=404)

    assert fetch_resume_view_history(ACC) == {"items": [], "total": 0}
    assert len(responses.calls) == 1


@pytest.mark.parametrize("status", [401, 500])
@responses.activate
def test_fetch_resume_view_history_fallback_status_raises(oauth_token, status):
    """401/5xx — fallback-статусы: проглатывать нельзя (повтор через
    web-flow выше по стеку)."""
    from app.mobile_resume_views import fetch_resume_view_history

    responses.add(responses.GET, VIEWS_URL_RH1,
                  json={"errors": [{"value": "oops"}]}, status=status)

    with pytest.raises(MobileAPIError) as ei:
        fetch_resume_view_history(ACC)
    assert ei.value.status_code == status


# ---------------------------------------------------------------------------
# 5. Резолв резюме без resume_hash: /mobile/resumes/mine → /resumes/r7/views
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_resume_view_history_resolves_resume_via_mine(oauth_token):
    from app.mobile_resume_views import fetch_resume_view_history

    acc = {"name": "a1", "cookies": {}}  # без resume_hash
    responses.add(responses.GET, MOBILE_BASE + "/mobile/resumes/mine",
                  json={"items": [{"id": "r7"}], "found": 1, "pages": 1},
                  status=200)
    responses.add(responses.GET, MOBILE_BASE + "/resumes/r7/views",
                  json=_views_page(
                      items=[_view_item("5", "Дельта",
                                        "2026-08-10T08:00:00+0300", False)],
                      found=1, pages=1, page=0, per_page=50),
                  status=200)

    result = fetch_resume_view_history(acc)

    assert result["total"] == 1
    assert result["items"][0]["employer_id"] == "5"
    assert len(responses.calls) == 2
    assert responses.calls[0].request.url.split("?")[0] == \
        MOBILE_BASE + "/mobile/resumes/mine"
    assert responses.calls[1].request.url.split("?")[0] == \
        MOBILE_BASE + "/resumes/r7/views"


# ---------------------------------------------------------------------------
# 6. Пустой резолв: нет ни resume_hash, ни резюме в списке → дефолт без
#    запросов к /views
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_resume_view_history_no_resume_no_views_request(oauth_token):
    from app.mobile_resume_views import fetch_resume_view_history

    acc = {"name": "a1", "cookies": {}}
    empty = {"items": [], "found": 0, "pages": 0}
    responses.add(responses.GET, MOBILE_BASE + "/mobile/resumes/mine",
                  json=empty, status=200)
    responses.add(responses.GET, MOBILE_BASE + "/resumes/mine",
                  json=empty, status=200)

    assert fetch_resume_view_history(acc) == {"items": [], "total": 0}
    # оба запроса — списки резюме; ни одного к /views
    assert len(responses.calls) == 2
    for call in responses.calls:
        assert "/views" not in call.request.url


# ---------------------------------------------------------------------------
# 7. Делегат MobileHHClient.fetch_resume_view_history (позиционный limit
#    и keyword-вариант с resume_id)
# ---------------------------------------------------------------------------

@responses.activate
def test_client_delegate_positional_limit(oauth_token):
    responses.add(responses.GET, VIEWS_URL_RH1, json=_views_page(
        items=[_view_item("11583314", "Глобал Сервис",
                          "2026-08-10T10:33:00+0300", False)],
        found=1, pages=1, page=0, per_page=100,
    ), status=200)

    result = MobileHHClient(ACC).fetch_resume_view_history(100)  # позиционно!

    assert isinstance(result, dict)
    assert len(result["items"]) == 1
    assert result["items"][0]["employer_id"] == "11583314"
    assert result["total"] == 1
    assert _query(responses.calls[0].request).get("per_page") == "100"
    _assert_bearer(responses.calls[0].request)


@responses.activate
def test_client_delegate_keyword_resume_id(oauth_token):
    responses.add(responses.GET, MOBILE_BASE + "/resumes/rhX/views",
                  json=_views_page(
                      items=[_view_item("8", "Омега",
                                        "2026-08-01T00:00:00+0300", True)],
                      found=1, pages=1, page=0, per_page=5),
                  status=200)

    result = MobileHHClient(ACC).fetch_resume_view_history(limit=5,
                                                           resume_id="rhX")

    assert isinstance(result, dict) and result["items"]
    assert result["items"][0]["name"] == "Омега"
    assert result["items"][0]["viewed"] is True
    req = responses.calls[0].request
    assert req.url.split("?")[0] == MOBILE_BASE + "/resumes/rhX/views"
    assert _query(req).get("per_page") == "5"
