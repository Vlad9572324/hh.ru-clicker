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
