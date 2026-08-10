"""Tests for Phase 0 HHClient abstraction: WebHHClient / MobileHHClient / get_client factory."""
import time

import pytest
import responses

from app import hh_chat, mobile_web_only, oauth
from app.config import CONFIG
from app.hh_client_fallback import FallbackHHClient
from app.hh_client_factory import get_client
from app.hh_client_mobile import MobileHHClient
from app.hh_client_web import WebHHClient


def test_web_client_delegates_fetch_thread(monkeypatch):
    acc = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
    calls = []

    def fake_fetch(account, neg_id):
        calls.append((account, neg_id))
        return {"ok": True, "messages": []}

    # WebHHClient делегирует в app.hh_chat.fetch_negotiation_thread (атрибут модуля)
    monkeypatch.setattr(hh_chat, "fetch_negotiation_thread", fake_fetch)

    c = WebHHClient(acc)
    res = c.fetch_thread("neg123")

    assert res["ok"] is True
    assert len(calls) == 1
    called_acc, called_neg_id = calls[0]
    assert called_acc is acc  # позиционно тот же объект, не копия
    assert called_neg_id == "neg123"


@responses.activate
def test_mobile_fetch_counters_hits_api_me(monkeypatch):
    acc = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}

    # Токен добывается через app.oauth._obtain_oauth_token — мок,
    # чтобы не полезть в cookies/authorize-flow.
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "test-token")
    responses.add(
        responses.GET,
        "https://api.hh.ru/me",
        json={"id": "123", "first_name": "Ivan"},
        status=200,
    )

    c = MobileHHClient(acc)
    res = c.fetch_counters()

    assert res["id"] == "123"
    req = responses.calls[0].request
    assert "with_user_statuses=true" in req.url
    assert req.headers["Authorization"] == "Bearer test-token"


def test_mobile_fetch_negotiations_delegates_to_mobile_module(monkeypatch):
    # Phase 2: fetch_negotiations реально реализован — MobileHHClient
    # делегирует в app.mobile_negotiations (модуль, не функция — патчим
    # атрибут модуля), подставляя self.acc первым аргументом.
    from app import mobile_negotiations

    acc = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
    calls = []

    def fake(account, *args, **kwargs):
        calls.append((account, args, kwargs))
        return {"neg_ids": ["n1"], "auth_error": False}

    monkeypatch.setattr(mobile_negotiations, "fetch_negotiations", fake)

    res = MobileHHClient(acc).fetch_negotiations()

    assert res == {"neg_ids": ["n1"], "auth_error": False}
    assert len(calls) == 1
    assert calls[0][0] is acc  # тот же объект, не копия


def test_mobile_auto_decline_discards_delegate(monkeypatch):
    acc = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
    monkeypatch.setattr(mobile_web_only, "auto_decline_discards", lambda account: 2)
    assert MobileHHClient(acc).auto_decline_discards() == 2


def test_factory_mode_selection(monkeypatch):
    # Изолируем CONFIG.default_client_mode, чтобы дефолт не влиял на явные mode.
    monkeypatch.setattr(CONFIG, "default_client_mode", "auto")

    mobile_acc = {"mode": "mobile", "resume_hash": "rh", "cookies": {}}
    web_acc = {"mode": "web", "resume_hash": "rh", "cookies": {}}

    # Phase 2: явный mobile → FallbackHHClient поверх MobileHHClient
    # (auto-fallback на web-flow при 0/401/403/5xx/NotImplementedError).
    mobile_client = get_client(mobile_acc)
    assert isinstance(mobile_client, FallbackHHClient)
    assert isinstance(mobile_client.mobile, MobileHHClient)
    assert isinstance(get_client(web_acc), WebHHClient)


def test_factory_auto_mode(monkeypatch):
    monkeypatch.setattr(CONFIG, "default_client_mode", "auto")
    acc = {"mode": "auto", "resume_hash": "rh1", "cookies": {}}

    # Решение Phase 0 (docs/PHASE_MATRIX.md): "auto" → всегда WebHHClient,
    # даже при живом OAuth-токене (mobile-клиент ещё не готов).
    monkeypatch.setattr(
        oauth,
        "_oauth_tokens",
        {"rh1": {"access_token": "t", "expires_at": time.time() + 3600}},
    )
    assert isinstance(get_client(acc), WebHHClient)

    # Токена нет → тоже web
    monkeypatch.setattr(oauth, "_oauth_tokens", {})
    assert isinstance(get_client(acc), WebHHClient)


def test_factory_missing_mode_uses_config_default(monkeypatch):
    monkeypatch.setattr(oauth, "_oauth_tokens", {})
    monkeypatch.setattr(CONFIG, "default_client_mode", "web")

    acc = {"resume_hash": "rh", "cookies": {}}  # без "mode"
    assert isinstance(get_client(acc), WebHHClient)
