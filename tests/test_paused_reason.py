"""Tests for AccountState.paused_reason semantics."""
from app.state import AccountState
from app.manager import BotManager


def test_default_paused_reason_empty():
    state = AccountState({"name": "A", "short": "a", "color": "#fff", "urls": []})
    assert state.paused_reason == ""


def test_auto_pause_sets_reason(monkeypatch):
    monkeypatch.setattr("app.manager.CONFIG.auto_pause_errors", 3)
    mgr = BotManager()
    state = AccountState({"name": "A", "short": "a", "color": "#fff", "urls": []})
    state.consecutive_errors = 5
    mgr._check_auto_pause(state)
    assert state.paused is True
    assert state.paused_reason == "auto_errors"


def test_toggle_account_pause_sets_and_clears_manual_reason(monkeypatch):
    """toggle не требует полной инициализации manager: проверяем его контракт
    на минимальном объекте и изолируем лог/WS как внешние побочные эффекты."""
    state = AccountState({"name": "A", "short": "a", "color": "#fff", "urls": []})
    mgr = BotManager.__new__(BotManager)
    mgr.account_states = [state]
    mgr.temp_states = {}
    mgr._add_log = lambda *args, **kwargs: None

    monkeypatch.setattr("app.ws_manager.ws_manager.suspend_account", lambda idx: None)
    monkeypatch.setattr("app.ws_manager.ws_manager.resume_account", lambda idx: None)

    mgr.toggle_account_pause(0)
    assert state.paused is True
    assert state.paused_reason == "manual"

    state.hard_stopped = True
    state.limit_exceeded = True
    state.consecutive_errors = 4
    mgr.toggle_account_pause(0)
    assert state.paused is False
    assert state.paused_reason == ""
    assert state.hard_stopped is False
    assert state.limit_exceeded is False
    assert state.consecutive_errors == 0
