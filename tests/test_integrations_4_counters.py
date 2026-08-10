"""
feat4: tests for GET /api/account/{idx}/counters_v2.

Мини-app (только роутер counters_v2) + TestClient + responses.
bot.account_states и OAuth-токен — monkeypatch.
"""

import pytest
import responses
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.instances import bot
from app.routes import counters_v2
from app.state import AccountState


ME_URL = "https://api.hh.ru/me"
COUNTERS_URL = "https://api.hh.ru/counters/user"

ME_BODY = {"id": "176187251"}
COUNTERS_BODY = {
    "unread_chats": 100,
    "unread_negotiations": 431,
    "new_resume_views": 938,
    "new_notifications": 0,
    "resumes_count": 2,
    "rejected_employer_reviews": 1,
}


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(counters_v2.router)
    return app


def _me_calls():
    return [c for c in responses.calls if c.request.url.split("?")[0] == ME_URL]


def _counters_calls():
    return [c for c in responses.calls if c.request.url.split("?")[0] == COUNTERS_URL]


@pytest.fixture()
def client(monkeypatch):
    counters_v2._uuid_cache.clear()
    monkeypatch.setattr(counters_v2, "_obtain_oauth_token", lambda acc: "test-oauth-token")
    acc = {
        "name": "Feat4 Acc",
        "short": "F4",
        "color": "cyan",
        "resume_hash": "rh_feat4_test",
        "urls": [],
        "cookies": {},
    }
    monkeypatch.setattr(bot, "account_states", [AccountState(acc)])
    return TestClient(_build_app())


@responses.activate
def test_counters_v2_happy_path(client):
    responses.add(responses.GET, ME_URL, json=ME_BODY, status=200)
    responses.add(responses.GET, COUNTERS_URL, json=COUNTERS_BODY, status=200)

    resp = client.get("/api/account/0/counters_v2")
    assert resp.status_code == 200
    j = resp.json()
    assert j["ok"] is True
    assert j["user_id"] == "176187251"
    assert j["counters"]["unread_chats"] == 100
    assert j["counters"]["unread_negotiations"] == 431
    assert j["counters"]["new_resume_views"] == 938
    assert j["counters"]["new_notifications"] == 0
    assert j["counters"]["resumes_count"] == 2
    assert j["counters"]["rejected_employer_reviews"] == 1

    # uuid проброшен в counters/user + правильные headers
    assert len(_me_calls()) == 1
    ctr = _counters_calls()
    assert len(ctr) == 1
    req = ctr[0].request
    assert "uuid=176187251" in req.url
    assert req.headers["Authorization"] == "Bearer test-oauth-token"
    assert req.headers["User-Agent"] == "ru.hh.android/26.28.1"
    assert req.headers["x-force-app-access"] == "true"


@responses.activate
def test_counters_v2_missing_keys_are_null(client):
    responses.add(responses.GET, ME_URL, json=ME_BODY, status=200)
    responses.add(responses.GET, COUNTERS_URL, json={"unread_chats": 5}, status=200)

    j = client.get("/api/account/0/counters_v2").json()
    assert j["ok"] is True
    assert j["counters"]["unread_chats"] == 5
    assert j["counters"]["unread_negotiations"] is None
    assert j["counters"]["new_resume_views"] is None
    assert j["counters"]["new_notifications"] is None


@responses.activate
def test_counters_v2_me_401_returns_502(client):
    responses.add(responses.GET, ME_URL, json={"error": "unauthorized"}, status=401)

    resp = client.get("/api/account/0/counters_v2")
    assert resp.status_code == 502
    assert resp.json() == {"ok": False, "error": "me_http_401"}
    assert len(_counters_calls()) == 0


@responses.activate
def test_counters_v2_counters_500_returns_502(client):
    responses.add(responses.GET, ME_URL, json=ME_BODY, status=200)
    responses.add(responses.GET, COUNTERS_URL, json={"oops": True}, status=500)

    resp = client.get("/api/account/0/counters_v2")
    assert resp.status_code == 502
    assert resp.json() == {"ok": False, "error": "counters_http_500"}


@responses.activate
def test_counters_v2_uuid_cache_skips_second_me(client):
    responses.add(responses.GET, ME_URL, json=ME_BODY, status=200)
    responses.add(responses.GET, COUNTERS_URL, json=COUNTERS_BODY, status=200)

    r1 = client.get("/api/account/0/counters_v2")
    r2 = client.get("/api/account/0/counters_v2")
    assert r1.status_code == 200
    assert r2.status_code == 200

    # /me вызван ровно 1 раз — второй запрос взял uuid из кэша
    assert len(_me_calls()) == 1
    # counters/user запрошен оба раза
    assert len(_counters_calls()) == 2


@responses.activate
def test_counters_v2_no_token_returns_400(client, monkeypatch):
    monkeypatch.setattr(counters_v2, "_obtain_oauth_token", lambda acc: "")

    resp = client.get("/api/account/0/counters_v2")
    assert resp.status_code == 400
    assert resp.json() == {"ok": False, "error": "no_oauth_token"}
    assert len(responses.calls) == 0


def test_counters_v2_invalid_idx_returns_404(client):
    resp = client.get("/api/account/99/counters_v2")
    assert resp.status_code == 404
    assert resp.json() == {"ok": False, "error": "invalid_idx"}
