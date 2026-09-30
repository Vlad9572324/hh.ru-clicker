import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import telegram_chat, telegram_subscribers
from app.telegram_bot import TelegramCaptchaBot


@pytest.fixture
def setup(monkeypatch):
    state = SimpleNamespace(acc={"user_id": "u1", "resume_hash": "rh"}, short="Мария", _deleted=False)
    monkeypatch.setattr(telegram_chat, "find_state", lambda ref: state if ref == "u1" else None)
    client = Mock(fetch_chat_history=Mock(return_value=[
        {"sender": "employer", "text": "Вам актуальна <вакансия>?", "timestamp": "2026-09-30T08:00:00+00:00"},
        {"sender": "applicant", "text": "Да", "timestamp": "2026-09-30T08:05:00+00:00"}]),
        send_message=Mock(return_value=True))
    monkeypatch.setattr("app.hh_client_factory.get_client", lambda acc: client)
    monkeypatch.setattr(telegram_subscribers, "is_known", lambda cid: cid == "123")
    bot = TelegramCaptchaBot()
    bot._call = AsyncMock(return_value={"message_id": 77})
    return bot, client, state


def cb(data, chat=123):
    return {"id": "q", "data": data, "message": {"chat": {"id": chat}, "message_id": 5}}


def test_show_history_escaped_with_times(setup):
    bot, client, _ = setup
    asyncio.run(bot.on_callback(cb("cv:u1:555")))
    sent = [c for c in bot._call.call_args_list if c.args[0] == "sendMessage"][-1].args[1]
    assert "👤 HR" in sent["text"] and "🙋 Вы" in sent["text"] and "11:00" in sent["text"]
    assert "&lt;вакансия&gt;" in sent["text"] and sent["parse_mode"] == "HTML"
    client.fetch_chat_history.assert_called_once_with("555", 12)


def test_reply_is_sent_once(setup):
    bot, client, _ = setup
    asyncio.run(bot.on_callback(cb("cr:u1:555")))
    asyncio.run(bot.on_message("Да, актуальна", 123, 77))
    client.send_message.assert_called_once_with("555", "Да, актуальна")
    asyncio.run(bot.on_message("Да, актуальна", 123, 77))
    client.send_message.assert_called_once()


def test_stranger_cannot_open_chat(setup):
    bot, client, _ = setup
    asyncio.run(bot.on_callback(cb("cv:u1:555", chat=999)))
    client.fetch_chat_history.assert_not_called()


def test_alert_buttons_fit_callback_limit():
    from app.telegram_alerts import chat_buttons
    kb = chat_buttons({"resume_hash": "4b08137aff0e8512b70039ed1f516f62495877"}, "5647803546")
    assert all(len(b["callback_data"].encode()) <= 64 for row in kb["inline_keyboard"] for b in row)
