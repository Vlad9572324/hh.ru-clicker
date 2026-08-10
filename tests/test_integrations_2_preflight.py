"""
Integration feat2: pre-flight check data_inconsistency перед откликом.

Свой мини-app (только роутер preflight) + TestClient + responses-моки HH.
bot.account_states и OAuth подменяются monkeypatch'ем.
"""

from urllib.parse import parse_qs, urlparse

import pytest
import responses
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.routes.preflight as preflight
from app.instances import bot

HH_URL = "https://api.hh.ru/resume_profile/data_inconsistency"


class FakeState:
    """Минимальная замена AccountState: роутер читает только .acc."""

    def __init__(self, acc):
        self.acc = acc


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(bot, "account_states", [FakeState({"resume_hash": "abc123"})])
    monkeypatch.setattr(preflight, "_obtain_oauth_token", lambda acc: "tok123")
    app = FastAPI()
    app.include_router(preflight.router)
    return TestClient(app)


@responses.activate
def test_required_fields_block_and_humanize(client):
    responses.add(
        responses.GET,
        HH_URL,
        json={"data_inconsistency": {"required_additional_data": ["PHOTO", "WORK_FORMAT"]}},
        status=200,
    )
    r = client.get("/api/account/0/vacancy/130334718/data_inconsistency")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["ready"] is False
    assert data["skipped"] is False
    assert data["required"] == ["PHOTO", "WORK_FORMAT"]
    assert "фотография в резюме" in data["humanized"]
    assert "формат работы (удалёнка/офис/гибрид)" in data["humanized"]

    # Запрос к HH: OAuth-заголовок, мобильный UA, правильные query-параметры.
    req = responses.calls[0].request
    assert req.headers["Authorization"] == "Bearer tok123"
    assert req.headers["User-Agent"] == "ru.hh.android/26.28.1"
    assert req.headers["x-force-app-access"] == "true"
    q = parse_qs(urlparse(req.url).query)
    assert q["vacancy_id"] == ["130334718"]
    assert q["resume_id"] == ["abc123"]
    assert q["flow"] == ["vacancy_response"]


@responses.activate
def test_empty_required_is_ready(client):
    responses.add(
        responses.GET,
        HH_URL,
        json={"data_inconsistency": {"required_additional_data": []}},
        status=200,
    )
    r = client.get("/api/account/0/vacancy/130334718/data_inconsistency")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["ready"] is True
    assert data["required"] == []
    assert data["humanized"] == []


@responses.activate
def test_missing_required_list_is_ready(client):
    # Список required_additional_data отсутствует — не блокируем.
    responses.add(responses.GET, HH_URL, json={"data_inconsistency": {}}, status=200)
    r = client.get("/api/account/0/vacancy/130334718/data_inconsistency")
    data = r.json()
    assert data["ok"] is True
    assert data["ready"] is True
    assert data["required"] == []


@responses.activate
def test_no_resume_hash_skipped(client, monkeypatch):
    monkeypatch.setattr(bot, "account_states", [FakeState({"resume_hash": ""})])
    r = client.get("/api/account/0/vacancy/130334718/data_inconsistency")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["skipped"] is True
    assert data["reason"] == "no_resume"
    assert data["ready"] is True
    assert data["required"] == []
    assert len(responses.calls) == 0  # HH не дёргали


@responses.activate
def test_hh_500_does_not_block(client):
    responses.add(responses.GET, HH_URL, body="internal error", status=500)
    r = client.get("/api/account/0/vacancy/130334718/data_inconsistency")
    assert r.status_code == 200  # статус остаётся 200, ошибка в поле error
    data = r.json()
    assert data["ok"] is False
    assert data["ready"] is True  # ошибка проверки НЕ блокирует отклик
    assert data["required"] == []
    assert "500" in data["error"]


@responses.activate
def test_network_error_does_not_block(client):
    import requests as req_lib

    responses.add(responses.GET, HH_URL, body=req_lib.exceptions.ConnectionError("boom"))
    r = client.get("/api/account/0/vacancy/130334718/data_inconsistency")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["ready"] is True
    assert data["required"] == []
    assert "NETWORK_ERROR" in data["error"]


@responses.activate
def test_no_oauth_token_400(client, monkeypatch):
    monkeypatch.setattr(preflight, "_obtain_oauth_token", lambda acc: "")
    r = client.get("/api/account/0/vacancy/130334718/data_inconsistency")
    assert r.status_code == 400
    data = r.json()
    assert data["ok"] is False
    assert data["error"] == "no_oauth_token"
    assert len(responses.calls) == 0  # без токена к HH не идём


def test_invalid_idx_404(client):
    assert client.get("/api/account/5/vacancy/130334718/data_inconsistency").status_code == 404
    assert client.get("/api/account/-1/vacancy/130334718/data_inconsistency").status_code == 404


def test_invalid_vacancy_id_400(client):
    # Не числовой ID и не ссылка на вакансию — 400 (фронтенд такое не шлёт,
    # но от прямого запроса защищаемся).
    r = client.get("/api/account/0/vacancy/not-a-vacancy/data_inconsistency")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_vacancy_id"
