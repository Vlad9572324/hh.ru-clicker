"""Тесты mobile-действий в чате (app/mobile_chat_actions.py).

Все HTTP через `responses` (конвенция test_hh_mobile_transport),
Bearer-токен — monkeypatch oauth._obtain_oauth_token → "t".
"""
import json
from urllib.parse import parse_qs

import pytest
import responses

from app import oauth
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError
from app.mobile_chat_actions import (
    fetch_quick_replies,
    mark_chat_read,
    send_participant_action,
)

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}


def _body_str(request) -> str:
    """Тело запроса как str (requests сериализует form в bytes)."""
    body = request.body
    if isinstance(body, bytes):
        return body.decode("utf-8")
    return body or ""


# ── fetch_quick_replies ───────────────────────────────────────────────

@responses.activate
def test_fetch_quick_replies_200_text_and_label(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(
        responses.PUT,
        MOBILE_BASE + "/chats/5512844915/suggestions/quick_replies",
        json={"quick_replies": [{"text": "Привет"}, {"label": "Здравствуйте"}],
              "show_limit": False},
        status=200,
    )
    out = fetch_quick_replies(ACC, "5512844915", "15047614423")
    assert out == ["Привет", "Здравствуйте"]
    req = responses.calls[0].request
    assert "message_id=15047614423" in req.url
    assert not _body_str(req)  # PUT без тела (контракт APK)


@responses.activate
def test_fetch_quick_replies_200_no_key_empty_list(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(
        responses.PUT,
        MOBILE_BASE + "/chats/5512844915/suggestions/quick_replies",
        json={}, status=200,
    )
    assert fetch_quick_replies(ACC, "5512844915", "1") == []


@responses.activate
def test_fetch_quick_replies_404_returns_empty_no_raise(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(
        responses.PUT,
        MOBILE_BASE + "/chats/5512844915/suggestions/quick_replies",
        json={"errors": [{"value": "not_found"}]}, status=404,
    )
    assert fetch_quick_replies(ACC, "5512844915", "1") == []


@responses.activate
def test_fetch_quick_replies_401_raises_fallback(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(
        responses.PUT,
        MOBILE_BASE + "/chats/5512844915/suggestions/quick_replies",
        json={}, status=401,
    )
    with pytest.raises(MobileAPIError) as ei:
        fetch_quick_replies(ACC, "5512844915", "1")
    assert ei.value.status_code == 401


# ── mark_chat_read ────────────────────────────────────────────────────

@responses.activate
def test_mark_chat_read_non_numeric_message_id_no_http(monkeypatch):
    """hash-fallback из _build_thread — запрос даже не уходит."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    assert mark_chat_read(ACC, "5512844915", "abc123hash") is False
    assert len(responses.calls) == 0


@responses.activate
def test_mark_chat_read_204_true_and_form_body(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(
        responses.PUT,
        MOBILE_BASE + "/chats/5512844915/messages/last_viewed_id",
        status=204,
    )
    assert mark_chat_read(ACC, "5512844915", "15047614423") is True
    req = responses.calls[0].request
    form = parse_qs(_body_str(req))
    assert form == {"message_id": ["15047614423"]}


@responses.activate
def test_mark_chat_read_422_false_no_raise(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(
        responses.PUT,
        MOBILE_BASE + "/chats/5512844915/messages/last_viewed_id",
        json={"errors": [{"value": "bad"}]}, status=422,
    )
    assert mark_chat_read(ACC, "5512844915", "15047614423") is False


# ── send_participant_action ───────────────────────────────────────────

@responses.activate
def test_send_participant_action_200_true_lowercase_body(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(
        responses.PUT,
        MOBILE_BASE + "/chats/5512844915/participants/action",
        status=200,
    )
    assert send_participant_action(ACC, "5512844915") is True
    req = responses.calls[0].request
    assert json.loads(_body_str(req)) == {"action_type": "typing"}


@responses.activate
def test_send_participant_action_none_normalized(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(
        responses.PUT,
        MOBILE_BASE + "/chats/5512844915/participants/action",
        status=200,
    )
    assert send_participant_action(ACC, "5512844915", "NONE") is True
    req = responses.calls[0].request
    assert json.loads(_body_str(req))["action_type"] == "none"


@responses.activate
def test_send_participant_action_500_raises_fallback(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(
        responses.PUT,
        MOBILE_BASE + "/chats/5512844915/participants/action",
        json={"errors": [{"value": "oops"}]}, status=500,
    )
    with pytest.raises(MobileAPIError) as ei:
        send_participant_action(ACC, "5512844915")
    assert ei.value.status_code == 500
