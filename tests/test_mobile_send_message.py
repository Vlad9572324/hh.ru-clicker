"""Тесты mobile-отправки сообщения в чат (app/mobile_send_message.py)."""
import json
import uuid

import pytest
import responses

from app import oauth
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError
from app.mobile_send_message import send_message

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
URL = MOBILE_BASE + "/chats/777/messages"


@responses.activate
def test_200_returns_true_and_body_contract(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL,
                  json={"message": {"id": "42", "text": "hi"}}, status=200)
    assert send_message(ACC, "777", "hi", idempotency_key="key-1") is True
    sent = json.loads(responses.calls[0].request.body)
    assert sent == {"text": "hi", "idempotency_key": "key-1"}


@responses.activate
def test_201_also_returns_true(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"message": {"id": "43"}}, status=201)
    assert send_message(ACC, "777", "hello") is True


@responses.activate
def test_idempotency_key_generated_when_empty(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"message": {}}, status=200)
    send_message(ACC, "777", "hi")
    sent = json.loads(responses.calls[0].request.body)
    key = sent["idempotency_key"]
    assert key  # непустой
    uuid.UUID(key)  # валидный UUID-формат (иначе ValueError)


@responses.activate
def test_explicit_idempotency_key_used_verbatim(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"message": {}}, status=200)
    send_message(ACC, "777", "hi", idempotency_key="my-key-123")
    sent = json.loads(responses.calls[0].request.body)
    assert sent["idempotency_key"] == "my-key-123"


@responses.activate
def test_404_returns_chat_not_found(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL,
                  json={"errors": [{"type": "not_found"}]}, status=404)
    assert send_message(ACC, "777", "hi") == "chat_not_found"


@responses.activate
def test_400_returns_false(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL,
                  json={"errors": [{"type": "bad_request"}]}, status=400)
    assert send_message(ACC, "777", "hi") is False


@responses.activate
def test_401_raises_mobile_api_error_for_fallback(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"errors": []}, status=401)
    with pytest.raises(MobileAPIError) as ei:
        send_message(ACC, "777", "hi")
    assert ei.value.status_code == 401


@responses.activate
def test_500_raises_mobile_api_error_for_fallback(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, body="internal error", status=500)
    with pytest.raises(MobileAPIError) as ei:
        send_message(ACC, "777", "hi")
    assert ei.value.status_code == 500
