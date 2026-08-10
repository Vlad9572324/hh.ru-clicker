"""Integration-тесты HTTP-роутов WS-toggle (Feature 8, subagent_8).

Роуты app/routes/ws.py менять нельзя — тестируем их как есть через мини-app:
FastAPI() + include_router(router) + TestClient.

Модель подмены (ничего сетевого/потокового не стартует):
- bot.account_states (app.instances) — список из одного fake-объекта с .acc = {};
  роуты и ws_manager трогают у состояния только поле .acc;
- CONFIG.use_websocket_realtime — monkeypatch (восстанавливается автоматически);
- CONFIG.use_websocket_realtime=True кейс идёт с заглушкой WsManager._start
  (иначе полезут daemon-треды слушателей); флаг off — с РЕАЛЬНЫМ ws_manager:
  это честный интеграционный тест без потоков (при flag off _start не вызывается).

После каждого теста singleton ws_manager приводится в чистое состояние,
чтобы entry не перетекали в соседние тесты.
"""

import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import CONFIG
from app.instances import bot
from app.routes.ws import router as ws_router
from app.ws_manager import ws_manager


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(ws_router)
    return app


@pytest.fixture()
def fake_account(monkeypatch):
    """Один fake-аккаунт (idx=0): роуты/ws_manager читают только state.acc."""
    acc: dict = {}
    monkeypatch.setattr(bot, "account_states", [types.SimpleNamespace(acc=acc)])
    yield acc
    # Чистим singleton ws_manager: entry/паузы не должны перетекать между тестами.
    with ws_manager._lock:
        ws_manager._entries.clear()
        ws_manager._acc_suspended.clear()
    ws_manager._suspended = False


@pytest.fixture()
def client(fake_account):
    """TestClient мини-app'а; fake_account гарантированно активен на запросах."""
    with TestClient(_build_app()) as c:
        yield c


@pytest.fixture()
def global_flag(monkeypatch):
    """Выставить CONFIG.use_websocket_realtime (автовосстановление monkeypatch'ем)."""
    def _set(value: bool):
        monkeypatch.setattr(CONFIG, "use_websocket_realtime", value)
    return _set


# ── валидация idx ──────────────────────────────────────────────────────────

def test_enable_invalid_idx_returns_404(client):
    """idx вне диапазона аккаунтов → 404 {"ok": false, ...}."""
    resp = client.post("/api/ws/99/enable")
    assert resp.status_code == 404
    assert resp.json()["ok"] is False
    assert "error" in resp.json()


def test_disable_invalid_idx_returns_404(client):
    resp = client.post("/api/ws/5/disable")
    assert resp.status_code == 404
    assert resp.json()["ok"] is False


# ── enable/disable при глобальном флаге OFF (реальный ws_manager, без потоков) ──

def test_enable_with_global_flag_off_returns_disabled_global(client, fake_account, global_flag):
    global_flag(False)
    resp = client.post("/api/ws/0/enable")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "enabled": True, "status": "disabled_global"}
    # намерение включиться запомнено в acc
    assert fake_account["ws_realtime"] is True
    # тред слушателя НЕ стартовал — entry в статусе disabled_global без thread
    with ws_manager._lock:
        entry = ws_manager._entries.get(0)
    assert entry is not None
    assert entry.status == "disabled_global"
    assert entry.thread is None


def test_disable_after_enable_resets_flag(client, fake_account, global_flag):
    global_flag(False)
    pre = client.post("/api/ws/0/enable")
    assert pre.json()["status"] == "disabled_global"

    resp = client.post("/api/ws/0/disable")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "enabled": False, "status": "disabled"}
    assert fake_account["ws_realtime"] is False


# ── GET /api/ws/status: структура ──────────────────────────────────────────

def test_status_structure_fresh(client, fake_account, global_flag):
    """До enable: аккаунт в статусе disabled, enabled=False."""
    global_flag(False)
    resp = client.get("/api/ws/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["use_websocket_realtime"] is False
    assert "accounts" in body
    # JSON сериализует int-ключи dict'а в строки
    assert body["accounts"]["0"] == {
        "enabled": False,
        "status": "disabled",
        "events_total": 0,
        "last_event_type": None,
        "last_event_at": None,
    }


def test_status_after_enable_reflects_disabled_global(client, fake_account, global_flag):
    global_flag(False)
    assert client.post("/api/ws/0/enable").json()["ok"] is True

    body = client.get("/api/ws/status").json()
    assert body["ok"] is True
    assert body["use_websocket_realtime"] is False
    assert body["accounts"]["0"] == {
        "enabled": True,
        "status": "disabled_global",
        "events_total": 0,
        "last_event_type": None,
        "last_event_at": None,
    }


# ── enable при глобальном флаге ON: только со stub'ом _start ──────────────

def test_enable_with_global_flag_on_calls_start(client, fake_account, global_flag, monkeypatch):
    """CONFIG.use_websocket_realtime=True + WsManager._start заменён заглушкой,
    чтобы не поднимать треды слушателей."""
    global_flag(True)
    started = []

    def fake_start(idx, acc):
        started.append((idx, acc))
        with ws_manager._lock:
            ws_manager._ensure_entry(idx).status = "connecting"

    monkeypatch.setattr(ws_manager, "_start", fake_start)

    resp = client.post("/api/ws/0/enable")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "enabled": True, "status": "connecting"}
    assert started == [(0, fake_account)]
    assert fake_account["ws_realtime"] is True

    # статус отдаёт глобальный флаг True
    body = client.get("/api/ws/status").json()
    assert body["use_websocket_realtime"] is True
    assert body["accounts"]["0"]["enabled"] is True

    # disable гасит флаг аккаунта
    resp = client.post("/api/ws/0/disable")
    assert resp.json() == {"ok": True, "enabled": False, "status": "disabled"}
    assert fake_account["ws_realtime"] is False
