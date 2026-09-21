"""Telegram manager hooks must stay read-only with respect to HH."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import app.manager as manager_mod


def _state():
    return SimpleNamespace(
        acc={"name": "synthetic"}, short="S", color="blue",
        _telegram_notify_lock=threading.Lock(),
    )


def test_message_alert_reads_current_client_and_includes_context(monkeypatch):
    client = SimpleNamespace(fetch_chat_list=Mock(return_value=({"n1": {"type": "NEGOTIATION"}}, {}, "applicant")))
    thread = {
        "needs_reply": True, "last_msg_id": "m1", "last_employer_msg": "Can we talk?",
        "vacancy_title": "Backend Engineer", "employer_name": "Example LLC",
    }
    delivered = Mock(return_value=True)
    monkeypatch.setattr(manager_mod, "get_client", lambda acc: client)
    monkeypatch.setattr(manager_mod, "telegram_is_configured", lambda: True)
    monkeypatch.setattr(manager_mod, "telegram_send_once", delivered)
    monkeypatch.setattr(manager_mod, "_build_thread_from_chat_item", lambda *args: thread)
    bot = manager_mod.BotManager.__new__(manager_mod.BotManager)

    bot._notify_employer_messages(_state())

    client.fetch_chat_list.assert_called_once_with(max_pages=3)
    delivered.assert_called_once()
    event_id, message = delivered.call_args.args
    assert event_id == "message:S:n1:m1"
    assert "Backend Engineer" in message and "Can we talk?" in message


def test_interview_alert_uses_stable_negotiation_id(monkeypatch):
    delivered = Mock(return_value=True)
    monkeypatch.setattr(manager_mod, "telegram_is_configured", lambda: True)
    monkeypatch.setattr(manager_mod, "telegram_send_once", delivered)
    bot = manager_mod.BotManager.__new__(manager_mod.BotManager)

    bot._notify_new_interviews(_state(), [{"neg_id": "n1", "text": "Backend Engineer", "date": "today"}])

    delivered.assert_called_once()
    assert delivered.call_args.args[0] == "interview:S:n1"
