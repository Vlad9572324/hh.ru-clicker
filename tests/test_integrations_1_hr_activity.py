"""Интеграционные тесты feat1: GET /api/vacancy/{id}/hr_activity.

Свой мини-app (FastAPI + router) без lifespan всего веб-приложения.
HTTP к api.hh.ru мокается через `responses` (роут ходит через requests.get
в run_in_executor — responses патчит requests глобально, работает из потоков,
прецедент: tests/test_ws_client.py).

bot.account_states подменяется monkeypatch'ем на список из объекта с .acc = {},
_obtain_oauth_token патчится в модуле роута (имя импортировано туда напрямую).
"""

import types

import pytest
import requests as requests_lib
import responses
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.instances import bot
from app.routes import hr_activity
from app.routes.hr_activity import router

_app = FastAPI()
_app.include_router(router)
client = TestClient(_app)

VID = "123456"
STATS_URL = f"https://api.hh.ru/vacancies/{VID}/employer_stats"


@pytest.fixture(autouse=True)
def _clean_cache():
    """Module-level кэш роута переживает тесты — вычищаем до и после."""
    hr_activity._cache.clear()
    yield
    hr_activity._cache.clear()


@pytest.fixture
def one_account(monkeypatch):
    """Один аккаунт (idx=0) + живой OAuth-токен."""
    monkeypatch.setattr(bot, "account_states", [types.SimpleNamespace(acc={})])
    monkeypatch.setattr(hr_activity, "_obtain_oauth_token", lambda acc: "test-token")


@responses.activate
def test_live_hr(one_account):
    """inactive=1 мин → live=True, badge='live'; заголовки HH мобильные."""
    responses.add(
        responses.GET, STATS_URL,
        json={"manager_inactive_minutes": 1, "employer_responses_read_percent": 92},
        status=200,
    )
    r = client.get(f"/api/vacancy/{VID}/hr_activity")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["vacancy_id"] == VID
    assert data["manager_inactive_minutes"] == 1
    assert data["employer_responses_read_percent"] == 92
    assert data["live"] is True
    assert data["badge"] == "live"
    # Проверяем, что к HH ушли правильные заголовки мобильного клиента.
    req = responses.calls[0].request
    assert req.headers["Authorization"] == "Bearer test-token"
    assert req.headers["User-Agent"] == "ru.hh.android/26.28.1"
    assert req.headers["x-force-app-access"] == "true"


@responses.activate
def test_pipeline_hr(one_account):
    """inactive=328320 мин (228 дней) → live=False, badge='pipeline'."""
    responses.add(
        responses.GET, STATS_URL,
        json={"manager_inactive_minutes": 328320, "employer_responses_read_percent": 5},
        status=200,
    )
    r = client.get(f"/api/vacancy/{VID}/hr_activity")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["manager_inactive_minutes"] == 328320
    assert data["live"] is False
    assert data["badge"] == "pipeline"


@responses.activate
def test_unknown_when_inactive_missing(one_account):
    """manager_inactive_minutes отсутствует → badge='unknown', поле null."""
    responses.add(
        responses.GET, STATS_URL,
        json={"employer_responses_read_percent": 42},
        status=200,
    )
    r = client.get(f"/api/vacancy/{VID}/hr_activity")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["manager_inactive_minutes"] is None
    assert data["employer_responses_read_percent"] == 42
    assert data["live"] is False
    assert data["badge"] == "unknown"


@responses.activate
def test_hh_404_maps_to_502(one_account):
    """HH вернул 404 → 502 {"ok": false, "error": "hh_http_404"}."""
    responses.add(responses.GET, STATS_URL, json={"message": "not found"}, status=404)
    r = client.get(f"/api/vacancy/{VID}/hr_activity")
    assert r.status_code == 502
    assert r.json() == {"ok": False, "error": "hh_http_404"}


@responses.activate
def test_network_error_maps_to_502(one_account):
    """Сетевая ошибка requests → 502, error начинается с 'network:'."""
    responses.add(responses.GET, STATS_URL, body=requests_lib.exceptions.ConnectionError("boom"))
    r = client.get(f"/api/vacancy/{VID}/hr_activity")
    assert r.status_code == 502
    data = r.json()
    assert data["ok"] is False
    assert data["error"].startswith("network:")


def test_no_oauth_token(monkeypatch):
    """Нет токена → 400 no_oauth_token, к HH не ходим."""
    monkeypatch.setattr(bot, "account_states", [types.SimpleNamespace(acc={})])
    monkeypatch.setattr(hr_activity, "_obtain_oauth_token", lambda acc: "")
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsp:
        rsp.add(responses.GET, STATS_URL, json={}, status=200)
        r = client.get(f"/api/vacancy/{VID}/hr_activity")
        assert len(rsp.calls) == 0  # до HH дело не дошло
    assert r.status_code == 400
    assert r.json() == {"ok": False, "error": "no_oauth_token"}


@responses.activate
def test_cache_prevents_second_http_call(one_account):
    """Повторный запрос в пределах 10 мин — из кэша: новый HTTP-вызов не делается."""
    responses.add(
        responses.GET, STATS_URL,
        json={"manager_inactive_minutes": 1, "employer_responses_read_percent": 92},
        status=200,
    )
    r1 = client.get(f"/api/vacancy/{VID}/hr_activity")
    r2 = client.get(f"/api/vacancy/{VID}/hr_activity")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json()
    assert len(responses.calls) == 1  # второй запрос обслужен кэшем


@responses.activate
def test_invalid_account_idx(one_account):
    """account_idx вне диапазона → 404, к HH не ходим."""
    responses.add(responses.GET, STATS_URL, json={}, status=200)
    r = client.get(f"/api/vacancy/{VID}/hr_activity", params={"account_idx": 99})
    assert r.status_code == 404
    assert r.json()["ok"] is False
    assert len(responses.calls) == 0


def test_invalid_vacancy_id():
    """Не-числовой id вакансии → 404 (URL к HH не конструируется)."""
    r = client.get("/api/vacancy/abc/hr_activity")
    assert r.status_code == 404
    assert r.json() == {"ok": False, "error": "invalid_vacancy_id"}
