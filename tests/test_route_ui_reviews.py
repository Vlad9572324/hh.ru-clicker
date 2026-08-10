"""Route-тесты GET /api/account/{idx}/reviews_to_rate (employer reviews badge).

Паттерн — tests/test_route_hedi.py: TestClient(app) без lifespan (bot не
запускается), bot._get_apply_acc и fetch-функция подменяются monkeypatch'ем.
fetch_employers_to_rate подменяется ЦЕЛИКОМ на уровне роута — сетевых
запросов нет вообще, responses-моки не нужны.
"""
from fastapi.testclient import TestClient

import app.routes.ui_reviews as route
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError
from app.instances import bot
from app.routes import app

SAMPLE = {
    "ok": True,
    "count": 1,
    "status": "EMPLOYERS_CAN_BE_REVIEWED",
    "items": [{"employer_id": 118368,
               "employer_name": "НПА Вира Реалтайм",
               "position": "Инженер-программист",
               "target": "PREVIOUS_EMPLOYER"}],
}

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}


def _setup(monkeypatch, fetch_result=None, fetch_exc=None):
    """bot._get_apply_acc: idx 0 → ACC, остальное → None;
    fetch_employers_to_rate — шпион с фиксированным результатом/исключением."""
    monkeypatch.setattr(bot, "_get_apply_acc",
                        lambda idx: dict(ACC) if idx == 0 else None)
    calls = []

    def fake_fetch(acc):
        calls.append(acc)
        if fetch_exc is not None:
            raise fetch_exc
        return fetch_result

    monkeypatch.setattr(route, "fetch_employers_to_rate", fake_fetch)
    return TestClient(app), calls


def test_reviews_to_rate_success(monkeypatch):
    client, calls = _setup(monkeypatch, fetch_result=SAMPLE)
    resp = client.get("/api/account/0/reviews_to_rate")
    assert resp.status_code == 200
    assert resp.json() == SAMPLE
    # fetch получил acc аккаунта, ровно один вызов
    assert calls == [ACC]


def test_reviews_to_rate_empty_result_passthrough(monkeypatch):
    empty = {"ok": True, "count": 0, "items": [], "status": ""}
    client, _ = _setup(monkeypatch, fetch_result=empty)
    resp = client.get("/api/account/0/reviews_to_rate")
    assert resp.status_code == 200
    assert resp.json() == empty


def test_reviews_to_rate_account_not_found(monkeypatch):
    client, calls = _setup(monkeypatch, fetch_result=SAMPLE)
    resp = client.get("/api/account/99/reviews_to_rate")
    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "error": "Аккаунт не найден"}
    # без аккаунта в сеть не идём
    assert calls == []


def test_reviews_to_rate_mobile_api_error(monkeypatch):
    """MobileAPIError (fallback-статус) из модуля → {"ok": False, error: str(e)}."""
    exc = MobileAPIError(
        401, payload="token_expired",
        url=MOBILE_BASE + "/employer_reviews/employers_to_rate")
    client, _ = _setup(monkeypatch, fetch_exc=exc)
    resp = client.get("/api/account/0/reviews_to_rate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "401" in body["error"]
    assert "employer_reviews/employers_to_rate" in body["error"]
