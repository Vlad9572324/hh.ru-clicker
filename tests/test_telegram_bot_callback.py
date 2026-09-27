"""Callback acknowledgements, polling dispatch, and private command replies."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from app import instances, telegram_menu, telegram_subscribers
from app.telegram_bot import TelegramCaptchaBot


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(telegram_subscribers, 'is_known', lambda cid: cid == '123')
    bot = TelegramCaptchaBot()
    bot._call = AsyncMock()
    return bot


def query(data):
    return {'id': 'query-id', 'data': data,
            'message': {'chat': {'id': 123}, 'message_id': 7}}


def test_callback_dispatch(bot, monkeypatch):
    keyboard = {'inline_keyboard': [[{'text': 'Назад', 'callback_data': 'back'}]]}
    handler = AsyncMock(return_value=('', keyboard))
    monkeypatch.setattr(telegram_menu, 'handle_callback', handler)
    asyncio.run(bot.on_callback(query('notif')))
    handler.assert_awaited_once_with(instances.bot, 'notif', 123, 7)
    assert [c.args[0] for c in bot._call.call_args_list] == ['answerCallbackQuery', 'editMessageReplyMarkup']
    assert json.loads(bot._call.call_args.args[1]['reply_markup']) == keyboard


@pytest.mark.parametrize('kind', ['unknown', 'exception', 'timeout', 'unsubscribed', 'missing_message'])
def test_always_acknowledges(bot, monkeypatch, kind):
    callback = query('unknown')
    if kind in ('exception', 'timeout'):
        monkeypatch.setattr(telegram_menu, 'handle_callback', AsyncMock(
            side_effect=RuntimeError() if kind == 'exception' else asyncio.TimeoutError()))
    if kind == 'unsubscribed':
        callback['message']['chat']['id'] = 999
    if kind == 'missing_message':
        callback.pop('message')
    asyncio.run(bot.on_callback(callback))
    bot._call.assert_awaited_once()
    method, fields = bot._call.call_args.args
    assert method == 'answerCallbackQuery'
    assert fields['callback_query_id'] == 'query-id'
    assert fields['text'] and fields['show_alert'] == 'false'


def test_poll_callbacks(bot):
    bot.on_callback = AsyncMock()
    bot._call.side_effect = [[{'update_id': 10, 'callback_query': query('back')}], asyncio.CancelledError()]
    async def run():
        with pytest.raises(asyncio.CancelledError):
            await bot._poll()
    asyncio.run(run())
    bot.on_callback.assert_awaited_once_with(query('back'))
    assert bot._offset == 11
    assert json.loads(bot._call.call_args_list[0].args[1]['allowed_updates']) == ['message', 'callback_query']


def test_status_private_and_no_dedup(bot, monkeypatch):
    monkeypatch.setattr(telegram_menu, 'handle_callback', AsyncMock(return_value=('Сводка', None)))
    status = AsyncMock(return_value='<b>Live</b>')
    monkeypatch.setattr(telegram_menu, 'live_status', status)
    async def run():
        await bot.on_callback(query('status'))
        await bot.on_message('/status', 123, None)
    asyncio.run(run())
    assert status.await_count == 2
    messages = [c.args[1] for c in bot._call.call_args_list if c.args[0] == 'sendMessage']
    assert len(messages) == 2
    assert all(str(m['chat_id']) == '123' and m['parse_mode'] == 'HTML' for m in messages)


def test_commands_idempotent(bot, monkeypatch):
    manager = SimpleNamespace(paused=False)
    manager.toggle_pause = Mock(side_effect=lambda: setattr(manager, 'paused', not manager.paused))
    monkeypatch.setattr(instances, 'bot', manager)
    async def run():
        for command in ('/pause', '/pause', '/resume', '/resume'):
            await bot.on_message(command, 123, None)
        await bot.on_message('/pause', 999, None)
    asyncio.run(run())
    assert manager.toggle_pause.call_count == 2
    assert manager.paused is False


def test_start_menu_and_registration(bot, monkeypatch):
    add = Mock(return_value=True)
    monkeypatch.setattr(telegram_subscribers, 'add', add)
    async def run():
        await bot.on_message('/start@Hhhg43bot payload', 123, None)
        await bot.on_message('/menu', 123, None)
        await bot._set_commands(telegram_menu.BOT_COMMANDS)
    asyncio.run(run())
    add.assert_called_once_with('123')
    calls = bot._call.call_args_list
    assert 'reply_markup' in calls[1].args[1] and 'reply_markup' in calls[2].args[1]
    assert calls[3].args[0] == 'setMyCommands'
    assert len(json.loads(calls[3].args[1]['commands'])) == 6
