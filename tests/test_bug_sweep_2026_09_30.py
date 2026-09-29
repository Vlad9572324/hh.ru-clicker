"""Regressions from the multi-model bug sweep (2026-09-30)."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

import app.manager as manager_mod
from app import hh_http, oauth
from app.hh_mobile_transport import mobile_headers, token_headers
from app.hr_rejection import is_stop_request
from app.user_agent import login_device_identity, mobile_user_agent, _default_mobile_user_agent


def _client_with_failing_cffi(exc_text):
    client = hh_http.HHClient()
    cffi = Mock(request=Mock(side_effect=RuntimeError(exc_text)))
    req = Mock(request=Mock(return_value=Mock(status_code=200, content=b"", headers={})))
    client._get_session = lambda key: (cffi, req)
    return client, req


def test_post_is_not_replayed_after_possible_dispatch(monkeypatch):
    monkeypatch.setattr(hh_http, "_record_diag", lambda *a, **k: None)
    client, req = _client_with_failing_cffi("curl: (28) Operation timed out after 15000 ms with 0 bytes received")
    with pytest.raises(requests.ConnectionError):
        client.request("POST", "https://api.hh.ru/negotiations", data={})
    req.request.assert_not_called()


@pytest.mark.parametrize("method,text", [
    ("POST", "curl: (6) Could not resolve host: api.hh.ru"),
    ("POST", "curl: (7) Failed to connect to api.hh.ru port 443"),
    ("GET", "curl: (28) Operation timed out after 15000 ms with 0 bytes received"),
])
def test_safe_fallbacks_still_happen(monkeypatch, method, text):
    monkeypatch.setattr(hh_http, "_record_diag", lambda *a, **k: None)
    client, req = _client_with_failing_cffi(text)
    client.request(method, "https://api.hh.ru/x")
    req.request.assert_called_once()


def test_chat_daily_cap_counts_persisted_sends(tmp_path, monkeypatch):
    log = tmp_path / "llm_log.jsonl"
    monkeypatch.setattr(manager_mod, "LLM_LOG_FILE", log)
    monkeypatch.setattr(manager_mod, "_today_msk", lambda: "2026-09-30")
    log.write_text("\n".join(json.dumps(e) for e in [
        {"time": "2026-09-30T08:00:00+03:00", "acc": "A", "neg_id": "1", "send_ok": True},
        {"time": "2026-09-30T09:00:00+03:00", "acc": "A", "neg_id": "1", "send_ok": True},
        {"time": "2026-09-30T09:30:00+03:00", "acc": "A", "neg_id": "1", "send_ok": False},
        {"time": "2026-09-29T20:00:00+03:00", "acc": "A", "neg_id": "1", "send_ok": True},
    ]) + "\n")
    bot = SimpleNamespace()
    count = manager_mod.BotManager._chat_sends_today
    assert count(bot, "A", "1") == 2
    assert count(bot, "A", "1", add=True) == 3
    assert count(bot, "B", "1") == 0


def test_stop_requests():
    assert is_stop_request("Хватит")
    assert is_stop_request("пожалуйста, не пишите мне больше")
    assert not is_stop_request("Хватает ли у вас опыта с Kafka?")


def test_login_identity_reproduces_login_user_agent():
    identity = login_device_identity()
    assert mobile_user_agent({"device_identity": identity}) == _default_mobile_user_agent()


def test_token_headers_use_owner_device(monkeypatch):
    acc = {"resume_hash": "rh1", "device_identity": {
        "device_uuid": "11111111-2222-3333-4444-555555555555", "model": "Pixel 8",
        "android_release": "15", "app_version_name": "26.32.11480"}}
    monkeypatch.setattr(oauth, "_oauth_tokens", {"rh1::": {"access_token": "tok"}})
    from app import instances
    monkeypatch.setattr(instances.bot, "account_states", [SimpleNamespace(acc=acc)], raising=False)
    monkeypatch.setattr(instances.bot, "temp_states", {}, raising=False)
    assert token_headers("tok") == mobile_headers(acc, "tok")
    unknown = token_headers("other")
    assert unknown["User-Agent"] == _default_mobile_user_agent()


def test_manual_resume_allowed_during_429_throttle():
    state = SimpleNamespace(paused=True, paused_reason="manual", pending_applies=[], hard_stopped=False,
                            limit_exceeded=True, cookies_expired=False, _limit_is_throttle=True)
    assert manager_mod.BotManager._resume_manual(state)
    state.paused, state.paused_reason, state._limit_is_throttle = True, "manual", False
    assert not manager_mod.BotManager._resume_manual(state)
