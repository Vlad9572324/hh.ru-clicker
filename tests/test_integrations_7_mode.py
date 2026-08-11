"""Integration tests: per-account mode selector (feat7).

PUT/GET /api/account/{idx}/mode — валидация, нормализация, сохранение в
accounts_data + save_accounts(). Мини-app (только роутер feat7) + TestClient;
глобальный accounts_data / bot.account_states подменяются monkeypatch'ем
(monkeypatch сам возвращает оригиналы после теста).
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.config as config
from app.instances import bot
from app.routes.account_mode import router
from app.state import AccountState


def _make_acc(name, **extra):
    acc = {
        "name": name,
        "short": name[:3],
        "color": "yellow",
        "urls": [],
        "cookies": {},
    }
    acc.update(extra)
    return acc


@pytest.fixture
def client(monkeypatch):
    acc0 = _make_acc("Main One")                    # без поля mode
    acc1 = _make_acc("Main Two", mode="mobile")     # явный mobile
    states = [AccountState(acc0), AccountState(acc1)]

    monkeypatch.setattr(bot, "account_states", states)
    monkeypatch.setattr(bot, "temp_sessions", [])
    monkeypatch.setattr(bot, "temp_states", {})
    monkeypatch.setattr(config, "accounts_data", [acc0, acc1])

    save_calls = []
    monkeypatch.setattr(config, "save_accounts", lambda: save_calls.append(1))

    app = FastAPI()
    app.include_router(router)
    tc = TestClient(app)
    tc.save_calls = save_calls  # удобный доступ из тестов
    tc.accs = [acc0, acc1]
    return tc


# ── PUT ──────────────────────────────────────────────────────────────

def test_put_mode_mobile(client):
    res = client.put("/api/account/0/mode", json={"mode": "mobile"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["mode"] == "mobile"
    assert data["effective_client"] == "MobileHHClient"
    # сохранено в acc-dict (accounts_data и AccountState.acc — один dict)
    assert client.accs[0]["mode"] == "mobile"
    assert bot.account_states[0].acc["mode"] == "mobile"
    assert bot.account_states[0].acc is client.accs[0]
    # save_accounts() вызван ровно раз
    assert len(client.save_calls) == 1


def test_put_mode_normalizes_whitespace_and_case(client):
    res = client.put("/api/account/0/mode", json={"mode": " WEB "})
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "web"
    assert data["effective_client"] == "WebHHClient"
    assert client.accs[0]["mode"] == "web"
    assert len(client.save_calls) == 1


def test_put_mode_auto(client):
    res = client.put("/api/account/1/mode", json={"mode": "auto"})
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "auto"
    # Phase 0: auto → WebHHClient (mobile только при явном mode="mobile")
    assert data["effective_client"] == "WebHHClient"
    assert client.accs[1]["mode"] == "auto"


@pytest.mark.parametrize("bad_mode", ["desktop", "Desktop", "", "webby", 123, None])
def test_put_invalid_mode_rejected(client, bad_mode):
    res = client.put("/api/account/0/mode", json={"mode": bad_mode})
    assert res.status_code == 400
    data = res.json()
    assert data["ok"] is False
    assert data["error"] == "invalid_mode"
    assert data["allowed"] == ["auto", "web", "mobile"]
    # ничего не сохранено
    assert "mode" not in client.accs[0]
    assert len(client.save_calls) == 0


def test_put_invalid_idx_404(client):
    for idx in (99, 2, -1):
        res = client.put(f"/api/account/{idx}/mode", json={"mode": "web"})
        assert res.status_code == 404
        assert res.json()["ok"] is False
    assert len(client.save_calls) == 0


def test_put_invalid_json(client):
    res = client.put(
        "/api/account/0/mode",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 400
    assert res.json()["ok"] is False
    assert len(client.save_calls) == 0


# ── GET ──────────────────────────────────────────────────────────────

def test_get_mode_returns_current(client):
    # acc1: явный mobile
    res = client.get("/api/account/1/mode")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["mode"] == "mobile"
    assert data["effective_client"] == "MobileHHClient"


def test_get_mode_default_when_field_missing(client):
    # acc0: поля "mode" нет → дефолт CONFIG.default_client_mode ("web")
    res = client.get("/api/account/0/mode")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["mode"] == config.CONFIG.default_client_mode
    assert data["effective_client"] == "WebHHClient"


def test_get_mode_reflects_put(client):
    client.put("/api/account/0/mode", json={"mode": "mobile"})
    res = client.get("/api/account/0/mode")
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "mobile"
    assert data["effective_client"] == "MobileHHClient"


def test_get_mode_invalid_idx_404(client):
    for idx in (99, 2, -1):
        res = client.get(f"/api/account/{idx}/mode")
        assert res.status_code == 404
        assert res.json()["ok"] is False


def test_browser_session_mode_is_saved_and_updates_active_state(client, monkeypatch):
    session = _make_acc("OTP Session", mode="mobile")
    active = AccountState(dict(session))
    monkeypatch.setattr(bot, "temp_sessions", [session])
    monkeypatch.setattr(bot, "temp_states", {0: active})
    saved = []
    monkeypatch.setattr(
        "app.routes.account_mode.save_browser_sessions",
        lambda sessions: saved.append([dict(item) for item in sessions]),
    )
    global_idx = len(bot.account_states)

    get_res = client.get(f"/api/account/{global_idx}/mode")
    put_res = client.put(f"/api/account/{global_idx}/mode", json={"mode": "auto"})

    assert get_res.status_code == 200
    assert get_res.json()["mode"] == "mobile"
    assert put_res.status_code == 200
    assert session["mode"] == "auto"
    assert active.acc["mode"] == "auto"
    assert saved[-1][0]["mode"] == "auto"
    assert client.save_calls == []
