import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from app import captcha, telegram_subscribers, instances
from app.telegram_bot import TelegramCaptchaBot
from app.config import CONFIG


def test_recovery_uses_persisted_link_without_pending_message(monkeypatch):
    monkeypatch.setattr(CONFIG, 'telegram_chat_id', '123')
    monkeypatch.setattr(telegram_subscribers, 'is_known', lambda chat: chat == '123')
    acc = {'user_id': 'synthetic'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=synthetic'})
    monkeypatch.setattr(instances, 'bot', SimpleNamespace(
        account_states=[SimpleNamespace(acc=acc)], temp_states={}))
    bot = TelegramCaptchaBot(AsyncMock())
    bot._call = AsyncMock()
    asyncio.run(bot.on_message('/captcha', '123', None))
    fields = bot._call.call_args.args[1]
    assert fields['chat_id'] == '123'
    assert 'mc_open:' in fields['reply_markup']
    assert captcha.current(acc)
    bot.resolver.assert_not_called()


def test_recovery_denies_unknown_chat(monkeypatch):
    monkeypatch.setattr(telegram_subscribers, 'is_known', lambda chat: False)
    bot = TelegramCaptchaBot(AsyncMock())
    bot._call = AsyncMock()
    asyncio.run(bot.on_message('/captcha', 'unknown', None))
    bot._call.assert_not_called()


def test_reply_message_id_is_scoped_to_chat(monkeypatch):
    monkeypatch.setattr(telegram_subscribers, 'is_known', lambda chat: True)
    bot = TelegramCaptchaBot(AsyncMock())
    bot._call = AsyncMock()
    bot.pending_chats = {('123', 'first'): 7, ('456', 'second'): 7}
    bot.pending = {7: 'second'}
    asyncio.run(bot.on_message('human answer', '123', 7))
    bot.resolver.assert_awaited_once_with('first', 'human answer')
