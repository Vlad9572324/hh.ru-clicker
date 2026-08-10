"""Тесты Phase 4: mobile-агрегация просмотров резюме
(app/mobile_resume_aggregate.py::fetch_resume_views_aggregate).

Конвенция tests/test_mobile_phase2_integration.py: полный путь функция →
app.hh_mobile_transport.mobile_request → HTTP, перехваченный библиотекой
`responses` (никаких живых запросов); Bearer-токен подменён через
monkeypatch app.oauth._obtain_oauth_token.

Контракт (см. докстринг app/mobile_resume_aggregate.py):
- GET /resumes/{rid}/views, per_page=100, page=0..pages-1, защитный
  потолок 10 страниц;
- возврат ВСЕГДА с ключами {"total", "new", "by_employer_top10",
  "total_all_time" (== total), "total_new" (== new), "graph_30d": []};
- fallback-статусы (0/401/403/5xx) → MobileAPIError; прочие не-2xx и
  пустой resume_id → нулевая структура без исключения.
"""
from urllib.parse import parse_qsl, urlsplit

import pytest
import responses

from app import oauth
from app.hh_client_mobile import MobileHHClient
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
VIEWS_URL = MOBILE_BASE + "/resumes/rh1/views"


@pytest.fixture
def oauth_token(monkeypatch):
    """Bearer-токен добывается через app.oauth._obtain_oauth_token —
    подменяем, чтобы не идти в реальный OAuth-flow."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")


def _last_request():
    assert responses.calls, "ни одного реального HTTP-запроса не было"
    return responses.calls[-1].request


def _assert_bearer(req):
    assert req.headers["Authorization"] == "Bearer t"
    # мобильные заголовки транспорта (контракт APK)
    assert req.headers["x-force-app-access"] == "true"


def _query(url) -> dict:
    """Query-параметры URL как dict — точнее подстрок ("page=1" не
    путается с "per_page=100")."""
    return dict(parse_qsl(urlsplit(url).query))


def _views_response(items, found, pages=1, page=0):
    """Форма ответа GET /resumes/{id}/views — коллекция api.hh.ru
    {"items", "found", "pages", "page", "per_page"}."""
    return {
        "items": items,
        "found": found,
        "pages": pages,
        "page": page,
        "per_page": 100,
    }


# ---------------------------------------------------------------------------
# 1. Happy path: агрегация, алиасы, топ работодателей, заголовки
# ---------------------------------------------------------------------------

HAPPY_ITEMS = [
    # "Глобал Сервис" — 2 просмотра, один новый (viewed=false)
    {"created_at": "2026-08-01T10:00:00+0300", "viewed": False,
     "employer": {"id": 11583314, "name": "Глобал Сервис"}},
    {"created_at": "2026-08-02T11:00:00+0300", "viewed": True,
     "employer": {"id": 11583314, "name": "Глобал Сервис"}},
    # "Хороший Сеть магазинов одежды" — 1 просмотр, прочитан
    {"created_at": "2026-08-03T12:00:00+0300", "viewed": True,
     "employer": {"id": 4527837, "name": "Хороший Сеть магазинов одежды"}},
    # работодатель без name — 1 новый просмотр → "Аноним"
    {"created_at": "2026-08-04T13:00:00+0300", "viewed": False,
     "employer": {"id": 999}},
]


@responses.activate
def test_aggregate_happy_path(oauth_token):
    from app.mobile_resume_aggregate import fetch_resume_views_aggregate

    responses.add(responses.GET, VIEWS_URL,
                  json=_views_response(HAPPY_ITEMS, found=4, pages=1),
                  status=200)

    result = fetch_resume_views_aggregate(ACC)

    # контракт: все ключи присутствуют
    assert set(result) == {"total", "new", "by_employer_top10",
                           "total_all_time", "total_new", "graph_30d"}
    assert result["total"] == 4  # found из ответа
    assert result["new"] == 2  # два item c viewed == false
    # web-совместимые алиасы (hh_resume.fetch_resume_views_aggregate)
    assert result["total_all_time"] == result["total"] == 4
    assert result["total_new"] == result["new"] == 2
    # 30-дневного графика в mobile-API нет
    assert result["graph_30d"] == []

    # топ работодателей: views desc, при равенстве name asc
    assert result["by_employer_top10"][0] == {
        "employer_id": "11583314", "name": "Глобал Сервис", "views": 2}
    assert result["by_employer_top10"] == [
        {"employer_id": "11583314", "name": "Глобал Сервис", "views": 2},
        {"employer_id": "999", "name": "Аноним", "views": 1},
        {"employer_id": "4527837",
         "name": "Хороший Сеть магазинов одежды", "views": 1},
    ]

    # один запрос: pages=1 → page=0 и стоп
    assert len(responses.calls) == 1
    req = _last_request()
    assert req.method == "GET"
    assert req.url.split("?")[0] == VIEWS_URL
    assert _query(req.url) == {"per_page": "100", "page": "0"}
    _assert_bearer(req)


# ---------------------------------------------------------------------------
# 2. Топ-10 обрезка: 12 работодателей → 10 записей, порядок views desc
# ---------------------------------------------------------------------------

@responses.activate
def test_aggregate_top10_truncation(oauth_token):
    from app.mobile_resume_aggregate import fetch_resume_views_aggregate

    items = [
        {"created_at": "2026-08-01T10:00:00+0300", "viewed": True,
         "employer": {"id": 1000 + i, "name": f"Компания {i:02d}"}}
        for i in range(1, 13)  # 12 разных работодателей
    ]
    responses.add(responses.GET, VIEWS_URL,
                  json=_views_response(items, found=12, pages=1), status=200)

    result = fetch_resume_views_aggregate(ACC)

    assert result["total"] == 12
    top = result["by_employer_top10"]
    assert len(top) == 10  # обрезка до топ-10
    # порядок views desc (все по 1 → тайбрейк name asc)
    assert all(a["views"] >= b["views"] for a, b in zip(top, top[1:]))
    assert [e["name"] for e in top] == sorted(e["name"] for e in top)
    # последние два работодателя отсечены
    names = {e["name"] for e in top}
    assert "Компания 11" not in names and "Компания 12" not in names


# ---------------------------------------------------------------------------
# 3. Пагинация: found=150, pages=2 → два запроса (page=0, page=1)
# ---------------------------------------------------------------------------

@responses.activate
def test_aggregate_pagination_two_pages(oauth_token):
    from app.mobile_resume_aggregate import fetch_resume_views_aggregate

    page0_items = [
        {"created_at": "2026-08-01T10:00:00+0300", "viewed": True,
         "employer": {"id": i, "name": f"Р{i}"}}
        for i in range(100)
    ]
    page1_items = [
        {"created_at": "2026-08-02T10:00:00+0300", "viewed": False,
         "employer": {"id": 1000 + i, "name": f"Р{i}"}}
        for i in range(50)
    ]
    responses.add(responses.GET, VIEWS_URL,
                  json=_views_response(page0_items, found=150, pages=2, page=0),
                  status=200)
    responses.add(responses.GET, VIEWS_URL,
                  json=_views_response(page1_items, found=150, pages=2, page=1),
                  status=200)

    result = fetch_resume_views_aggregate(ACC)

    assert result["total"] == 150  # found из ответа page=0
    assert result["new"] == 50  # вся вторая страница — viewed=false
    # ровно 2 запроса к /views: page=0 и page=1
    assert len(responses.calls) == 2
    for c in responses.calls:
        assert c.request.url.split("?")[0] == VIEWS_URL
        _assert_bearer(c.request)
    assert _query(responses.calls[0].request.url) == {"per_page": "100", "page": "0"}
    assert _query(responses.calls[1].request.url) == {"per_page": "100", "page": "1"}


# ---------------------------------------------------------------------------
# 4. Политика ошибок: 404 → нулевая структура; 401/500 → MobileAPIError
# ---------------------------------------------------------------------------

@responses.activate
def test_aggregate_404_returns_zero_structure(oauth_token):
    from app.mobile_resume_aggregate import fetch_resume_views_aggregate

    responses.add(responses.GET, VIEWS_URL,
                  json={"errors": [{"value": "resume_not_found"}]}, status=404)

    result = fetch_resume_views_aggregate(ACC)  # без исключения

    assert result == {"total": 0, "new": 0, "by_employer_top10": [],
                      "total_all_time": 0, "total_new": 0, "graph_30d": []}


@pytest.mark.parametrize("status", [401, 500])
@responses.activate
def test_aggregate_fallback_status_raises(oauth_token, status):
    """401/5xx — fallback-статусы: проглатывать нельзя, кидает
    MobileAPIError (повтор через web-flow)."""
    from app.mobile_resume_aggregate import fetch_resume_views_aggregate

    responses.add(responses.GET, VIEWS_URL,
                  json={"errors": [{"value": "token_expired"}]}, status=status)

    with pytest.raises(MobileAPIError) as ei:
        fetch_resume_views_aggregate(ACC)
    assert ei.value.status_code == status


# ---------------------------------------------------------------------------
# 5. Пустой resume_id (нет ни явного, ни в acc, ни в списке резюме) —
#    нулевая структура БЕЗ запросов к /views
# ---------------------------------------------------------------------------

@responses.activate
def test_aggregate_no_resume_returns_zero_without_views_requests(oauth_token):
    from app.mobile_resume_aggregate import fetch_resume_views_aggregate

    acc = {"name": "a2", "cookies": {}}  # без resume_hash
    # список резюме аккаунта пуст по обоим путям resolve
    responses.add(responses.GET, MOBILE_BASE + "/mobile/resumes/mine",
                  json={"items": [], "found": 0}, status=200)
    responses.add(responses.GET, MOBILE_BASE + "/resumes/mine",
                  json={"items": [], "found": 0}, status=200)

    result = fetch_resume_views_aggregate(acc)

    assert result == {"total": 0, "new": 0, "by_employer_top10": [],
                      "total_all_time": 0, "total_new": 0, "graph_30d": []}
    # запросы были только к списку резюме, к /views — ни одного
    assert responses.calls, "резолв резюме должен был сходить в /resumes/mine"
    assert all("/views" not in c.request.url for c in responses.calls)


# ---------------------------------------------------------------------------
# 6. Делегат MobileHHClient.fetch_resume_views_aggregate
# ---------------------------------------------------------------------------

@responses.activate
def test_client_delegate_returns_aggregate(oauth_token):
    responses.add(responses.GET, VIEWS_URL,
                  json=_views_response(HAPPY_ITEMS, found=4, pages=1),
                  status=200)

    result = MobileHHClient(ACC).fetch_resume_views_aggregate()

    assert isinstance(result, dict)
    for key in ("total", "new", "by_employer_top10",
                "total_all_time", "total_new", "graph_30d"):
        assert key in result, f"делегат не вернул ключ {key}"
    assert result["total"] == 4
    assert result["new"] == 2
