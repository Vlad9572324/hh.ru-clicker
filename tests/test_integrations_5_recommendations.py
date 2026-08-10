"""Интеграционные тесты feat5: GET /api/account/{idx}/hh_recommendations.

Мини-app только с роутером hh_recommendations (полный app.routes не нужен —
но импорт пакета app.routes всё равно происходит, как в test_truthy.py).
HH API мокается через responses; bot.account_states — через monkeypatch.
"""

import types

import pytest
import responses
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.instances import bot
from app.routes import hh_recommendations
from app.routes.hh_recommendations import router, HH_OFFERS_URL

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def _acc():
    return {"name": "a1", "cookies": {}, "resume_hash": "rh1"}


@pytest.fixture
def one_account(monkeypatch):
    """Один аккаунт (idx=0). Handler трогает только state.acc."""
    state = types.SimpleNamespace(acc=_acc())
    monkeypatch.setattr(bot, "account_states", [state])
    return state


@pytest.fixture
def with_token(monkeypatch):
    """Живой OAuth-токен (импорт в роутере by-name → патчим атрибут модуля)."""
    monkeypatch.setattr(
        hh_recommendations, "_obtain_oauth_token", lambda acc: "tok123"
    )


def test_200_two_offers(one_account, with_token):
    payload = {"possible_job_offers": [
        {"vacancy_id": 111, "vacancy_name": "Python Developer",
         "employer_name": "Foo LLC", "employer_id": 1},
        {"vacancy_id": 222, "vacancy_name": "Go Developer",
         "employer_name": "Bar Inc", "employer_id": 2},
    ]}
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, HH_OFFERS_URL, json=payload, status=200)
        r = client.get("/api/account/0/hh_recommendations")
        # Bearer-токен и мобильный UA действительно ушли в заголовках.
        # ВАЖНО: проверяем внутри with — на выходе из контекста responses
        # очищает список calls.
        sent = rsps.calls[0].request
        assert sent.headers["Authorization"] == "Bearer tok123"
        assert sent.headers["User-Agent"] == "ru.hh.android/26.28.1"
        assert sent.headers["x-force-app-access"] == "true"

    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["found"] == 2
    assert data["offers"][0] == {
        "vacancy_id": "111",
        "name": "Python Developer",
        "employer": "Foo LLC",
        "url": "https://hh.ru/vacancy/111",
    }
    assert data["offers"][1]["vacancy_id"] == "222"
    assert data["offers"][1]["url"] == "https://hh.ru/vacancy/222"


def test_200_empty_list(one_account, with_token):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, HH_OFFERS_URL,
                 json={"possible_job_offers": []}, status=200)
        r = client.get("/api/account/0/hh_recommendations")

    assert r.status_code == 200
    assert r.json() == {"ok": True, "found": 0, "offers": []}


def test_hh_401_maps_to_502(one_account, with_token):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, HH_OFFERS_URL,
                 json={"error_description": "unauthorized"}, status=401)
        r = client.get("/api/account/0/hh_recommendations")

    assert r.status_code == 502
    body = r.json()
    assert body["ok"] is False
    assert "401" in body["error"]


def test_hh_response_without_list_maps_to_502(one_account, with_token):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, HH_OFFERS_URL, json={"items": []}, status=200)
        r = client.get("/api/account/0/hh_recommendations")

    assert r.status_code == 502
    assert r.json()["ok"] is False


def test_no_token_400(one_account, monkeypatch):
    monkeypatch.setattr(hh_recommendations, "_obtain_oauth_token", lambda acc: "")
    with responses.RequestsMock() as rsps:
        r = client.get("/api/account/0/hh_recommendations")
        # Без токена до HH запрос не доходит (внутри with: на выходе calls чистятся)
        assert len(rsps.calls) == 0

    assert r.status_code == 400
    assert r.json() == {"ok": False, "error": "no_oauth_token"}


def test_invalid_idx_404(one_account, with_token):
    r = client.get("/api/account/99/hh_recommendations")
    assert r.status_code == 404
    assert r.json()["ok"] is False
