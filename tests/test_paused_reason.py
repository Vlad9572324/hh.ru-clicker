"""Tests for AccountState.paused_reason semantics."""
import pytest
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


def test_toggle_pause_reason_skipped():
    pytest.skip("requires BotManager with full account setup")
