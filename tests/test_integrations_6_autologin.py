"""Интеграционные тесты feat6: autologin bridge.

POST /api/account/{idx}/autologin_url:
  OAuth-токен → GET /me (hhid, кэш 30 мин) → GET /autologin_key/<hhid> →
  {"ok": true, "url": "https://hh.ru/?loginkey=<KEY>", "note": "одноразовый ключ"}

Мини-app + TestClient, HTTP мокается responses. bot.account_states подменяется
monkeypatch'ем, OAuth-токен — патчем _obtain_oauth_token в модуле роута.
"""

import types

import pytest
import responses
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.instances import bot
from app.routes import autologin as autologin_mod


ME_URL = "https://api.hh.ru/me"
KEY_URL = "https://api.hh.ru/autologin_key/123"


@pytest.fixture
def client(monkeypatch):
    """Мини-app только с roутером autologin + один фейковый аккаунт (idx=0)."""
    autologin_mod._hhid_cache.clear()  # изоляция от других тестов
    acc = {"name": "Test Acc", "resume_hash": "rh_feat6_test", "cookies": {}}
    state = types.SimpleNamespace(acc=acc)
    monkeypatch.setattr(bot, "account_states", [state])
    monkeypatch.setattr(
        autologin_mod, "_obtain_oauth_token", lambda acc: "TEST_OAUTH_TOKEN"
    )
    app = FastAPI()
    app.include_router(autologin_mod.router)
    with TestClient(app) as c:
        yield c
    autologin_mod._hhid_cache.clear()


@responses.activate
def test_ok_json_key(client):
    """/me 200 {"id":"123"} + /autologin_key/123 200 {"key":"SECRET123"} → url."""
    responses.add(responses.GET, ME_URL, json={"id": "123"}, status=200)
    responses.add(responses.GET, KEY_URL, json={"key": "SECRET123"}, status=200)

    r = client.post("/api/account/0/autologin_url")

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["url"] == "https://hh.ru/?loginkey=SECRET123"
    assert body["note"] == "одноразовый ключ"


@responses.activate
def test_ok_plain_text_key(client):
    """Ответ не JSON (content-type text), тело "XYZ999" → ключ из текста."""
    responses.add(responses.GET, ME_URL, json={"id": "123"}, status=200)
    responses.add(
        responses.GET, KEY_URL, body="XYZ999", status=200, content_type="text/plain"
    )

    r = client.post("/api/account/0/autologin_url")

    assert r.status_code == 200
    assert r.json()["url"] == "https://hh.ru/?loginkey=XYZ999"


@responses.activate
def test_no_known_keys_in_json(client):
    """JSON без известных ключей ({"foo": 1}) → 502 no_key_in_response."""
    responses.add(responses.GET, ME_URL, json={"id": "123"}, status=200)
    responses.add(responses.GET, KEY_URL, json={"foo": 1}, status=200)

    r = client.post("/api/account/0/autologin_url")

    assert r.status_code == 502
    assert r.json() == {"ok": False, "error": "no_key_in_response"}


@responses.activate
def test_me_401(client):
    """/me вернул 401 → 502 (без hhid ключ не получить)."""
    responses.add(responses.GET, ME_URL, json={"error": "unauthorized"}, status=401)

    r = client.post("/api/account/0/autologin_url")

    assert r.status_code == 502
    assert r.json()["ok"] is False


def test_no_oauth_token(client, monkeypatch):
    """Нет OAuth-токена → 400 no_oauth_token, HTTP-запросов к HH нет."""

    @responses.activate
    def _run():
        r = client.post("/api/account/0/autologin_url")
        assert r.status_code == 400
        assert r.json() == {"ok": False, "error": "no_oauth_token"}
        assert len(responses.calls) == 0

    monkeypatch.setattr(autologin_mod, "_obtain_oauth_token", lambda acc: "")
    _run()


def test_invalid_idx(client):
    """idx вне диапазона (и отрицательный) → 404 invalid_idx."""
    r = client.post("/api/account/99/autologin_url")
    assert r.status_code == 404
    assert r.json() == {"ok": False, "error": "account not found"}

    r2 = client.post("/api/account/-1/autologin_url")
    assert r2.status_code == 404


@responses.activate
def test_hhid_cached_me_called_once(client):
    """Кэш hhid: 2 запроса подряд → /me вызван 1 раз, autologin_key — 2 раза
    (ключ одноразовый, каждый раз новый)."""
    responses.add(responses.GET, ME_URL, json={"id": "123"}, status=200)
    responses.add(responses.GET, KEY_URL, json={"key": "KEY_ONE"}, status=200)
    responses.add(responses.GET, KEY_URL, json={"key": "KEY_TWO"}, status=200)

    r1 = client.post("/api/account/0/autologin_url")
    r2 = client.post("/api/account/0/autologin_url")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["url"] == "https://hh.ru/?loginkey=KEY_ONE"
    assert r2.json()["url"] == "https://hh.ru/?loginkey=KEY_TWO"

    me_calls = [c for c in responses.calls if c.request.url == ME_URL]
    key_calls = [
        c for c in responses.calls
        if c.request.url.startswith("https://api.hh.ru/autologin_key/")
    ]
    assert len(me_calls) == 1
    assert len(key_calls) == 2
