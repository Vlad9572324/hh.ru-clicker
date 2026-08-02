"""Tests for websocket_endpoint message handling (does-not-crash assertions)."""
import pytest
from fastapi.testclient import TestClient
from app.routes import app

client = TestClient(app)


def test_unknown_cmd_does_not_crash():
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "unknown"})


def test_account_pause_with_string_idx_does_not_crash():
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "account_pause", "idx": "abc"})


def test_set_config_unknown_key_ignored():
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "set_config", "key": "nonexistent", "value": 1})


def test_set_config_wrong_type_does_not_crash():
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "set_config", "key": "pages_per_url", "value": "bad"})


def test_empty_payload_does_not_crash():
    with client.websocket_connect("/ws") as ws:
        ws.send_json({})


def test_chat_message_edited_invalidates_llm_drafts():
    from app.manager import _handle_edited_event
    from app.state import AccountState

    state = AccountState({"name": "Test", "short": "T", "color": "red", "urls": []})
    state._llm_drafts = {("c1", "m1"): "draft1", ("c2", "m2"): "keep"}
    _handle_edited_event(state, {"chatId": "c1"})
    # draft по отредактированному чату сброшен, чужой — на месте
    assert state._llm_drafts == {("c2", "m2"): "keep"}
