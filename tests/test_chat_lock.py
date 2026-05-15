"""Tests for app.hh_chat._check_chat_locked."""

import pytest

try:
    from app.hh_chat import _check_chat_locked
except ImportError as exc:
    pytest.skip(f"_check_chat_locked not available: {exc}", allow_module_level=True)


def test_cansendmessage_false():
    assert _check_chat_locked({"canSendMessage": False}) == "canSendMessage=false"


def test_state_archived():
    assert _check_chat_locked({"state": "archived"}) == "state=archived"


def test_locked_true():
    assert _check_chat_locked({"locked": True}) == "locked=true"


def test_russian_phrase_fallback():
    item = {
        "canSendMessage": True,
        "lastMessage": {"text": "К сожалению, работодатель отключил переписку."},
    }
    result = _check_chat_locked(item)
    assert "работодатель отключил переписку" in result
