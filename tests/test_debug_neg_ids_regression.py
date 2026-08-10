"""Регрессия /api/debug/neg_ids/{idx} (app.routes.debug.api_debug_neg_ids).

P1-дефект из code review Phase 0: при default mode "auto" и живом OAuth-токене
get_client() возвращала MobileHHClient, чей fetch_negotiations() кидает
NotImplementedError("phase 2: ...") — endpoint возвращал ok:false для нормальных
аккаунтов. После фикса "auto" и аккаунты без поля mode должны ВСЕГДА резолвиться
в WebHHClient (Phase 0); явный mode="mobile" по-прежнему даёт MobileHHClient
(ok:false с "phase 2" — задокументированное ограничение skeleton'а до Phase 2).

pytest-asyncio в проекте нет — async handler вызывается через asyncio.run()
(хелпер _run устойчив к уже запущенному в потоке event loop — см. ниже).
"""

import asyncio
import threading
import time
import types

import pytest

from app import hh_negotiations, oauth
from app.config import CONFIG
from app.instances import bot
from app.routes.debug import api_debug_neg_ids


def _run(coro):
    """Исполнить корутину через asyncio.run, устойчиво к занятому потоку.

    Полный прогон pytest оставляет после e2e (pytest-playwright / session-scoped
    aiohttp-сервер в tests/e2e/conftest.py) запущенный event loop в текущем
    потоке, и прямой asyncio.run() падает с
    "RuntimeError: asyncio.run() cannot be called from a running event loop".
    Если loop в текущем потоке есть — исполняем корутину в свежем потоке.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict = {}

    def _target():
        try:
            box["result"] = asyncio.run(coro)
        except BaseException as exc:  # перебрасываем в основной поток
            box["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


@pytest.fixture
def fake_state(monkeypatch):
    """Подменить состояние bot одним аккаунтом (idx=0), temp_states пуст.

    Handler трогает у state только поле .acc (см. api_debug_neg_ids),
    поэтому достаточно SimpleNamespace(acc=...).
    """
    def _install(acc: dict):
        state = types.SimpleNamespace(acc=acc)
        monkeypatch.setattr(bot, "account_states", [state])
        monkeypatch.setattr(bot, "temp_states", {})
        return state
    return _install


@pytest.fixture
def live_oauth(monkeypatch):
    """Живой OAuth-токен для resume_hash rh1.

    Патчим и сырой кэш _oauth_tokens, и get_oauth_status — чтобы предусловие
    «токен жив» выполнялось при любой реализации factory (до/после P1-фикса).
    """
    monkeypatch.setattr(
        oauth,
        "_oauth_tokens",
        {"rh1": {"access_token": "t", "expires_at": time.time() + 3600}},
    )
    monkeypatch.setattr(oauth, "get_oauth_status", lambda rh: {"has_token": True})


def _mock_web_negotiations(monkeypatch, payload):
    """WebHHClient.fetch_negotiations делегирует в атрибут модуля
    hh_negotiations.fetch_hh_negotiations_stats — мокаем именно его."""
    monkeypatch.setattr(
        hh_negotiations,
        "fetch_hh_negotiations_stats",
        lambda acc, max_pages=20: payload,
    )


def test_neg_ids_account_without_mode_auto_uses_web_client(
    monkeypatch, tmp_data_dir, fake_state, live_oauth
):
    """P1-регрессия: типичный существующий аккаунт БЕЗ поля mode + живой
    OAuth-токен. До фикса factory в auto-ветке видела токен и возвращала
    MobileHHClient → NotImplementedError("phase 2") → ok:false.
    После фикса auto → всегда WebHHClient (Phase 0) → ok:true."""
    monkeypatch.setattr(CONFIG, "default_client_mode", "auto")
    acc = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}  # без "mode"
    fake_state(acc)
    _mock_web_negotiations(monkeypatch, {"items": [1, 2, 3]})

    result = _run(api_debug_neg_ids(0))

    assert result["ok"] is True, f"P1: auto не должен падать в phase 2: {result}"
    assert result["account"] == "a1"
    assert result["mode"] == ""  # поля mode на аккаунте нет
    assert result["negotiations"] == {"items": [1, 2, 3]}


def test_neg_ids_explicit_mobile_mode_phase2_limitation(
    monkeypatch, tmp_data_dir, fake_state, live_oauth
):
    """Явный mode="mobile" → MobileHHClient, чей fetch_negotiations() кидает
    NotImplementedError. ok:false с "phase 2" — задокументированное ограничение
    skeleton'а до Phase 2 (не баг)."""
    monkeypatch.setattr(CONFIG, "default_client_mode", "auto")
    acc = {"name": "a1", "cookies": {}, "resume_hash": "rh1", "mode": "mobile"}
    fake_state(acc)
    _mock_web_negotiations(monkeypatch, {"items": [1, 2, 3]})

    result = _run(api_debug_neg_ids(0))

    assert result["ok"] is False
    # handler обрезает str(e)[:100]; "phase 2" стоит в начале сообщения
    # NotImplementedError("phase 2: TODO mobile fetch_negotiations") — 39 симв.,
    # так что начало строки гарантированно попадает в обрезанный error.
    assert "phase 2" in result["error"]
    assert len(result["error"]) <= 100


def test_neg_ids_out_of_range(monkeypatch, tmp_data_dir, fake_state):
    """idx вне диапазона (аккаунт один, temp_states пуст) → account not found."""
    acc = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
    fake_state(acc)

    result = _run(api_debug_neg_ids(99))

    assert result == {"ok": False, "error": "account not found"}
