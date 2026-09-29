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


@pytest.mark.parametrize('action', ['open', 'resume'])
def test_manual_callback_is_shared_by_subscribers_and_acknowledged_once(bot, monkeypatch, action):
    bot.chat_id = '123'
    flow = SimpleNamespace(open=AsyncMock(), resume=AsyncMock())
    monkeypatch.setattr(bot, 'manual_flow', lambda: flow)
    asyncio.run(bot.on_callback(query('mc_' + action + ':synthetic')))
    getattr(flow, action).assert_awaited_once_with(123, 'synthetic')
    assert [c.args[0] for c in bot._call.call_args_list].count('answerCallbackQuery') == 1
    getattr(flow, action).reset_mock()
    bot.chat_id = 'different-operator'
    asyncio.run(bot.on_callback(query('mc_' + action + ':synthetic')))
    getattr(flow, action).assert_awaited_once_with(123, 'synthetic')
    getattr(flow, action).reset_mock()
    unknown = query('mc_' + action + ':synthetic')
    unknown['message']['chat']['id'] = 999
    asyncio.run(bot.on_callback(unknown))
    getattr(flow, action).assert_not_called()


@pytest.mark.parametrize('failed_method', ['editMessageReplyMarkup', 'answerCallbackQuery'])
def test_cosmetic_failure_does_not_drop_captcha_action(bot, monkeypatch, failed_method):
    monkeypatch.setattr(telegram_menu, 'handle_callback', AsyncMock(return_value=(
        'Проверка', {'inline_keyboard': []})))
    async def call(method, fields):
        if method == failed_method:
            raise RuntimeError('message is not modified')
        return True
    bot._call.side_effect = call
    bot.on_message = AsyncMock()
    asyncio.run(bot.on_callback(query('captcha')))
    bot.on_message.assert_awaited_once_with('/captcha', 123, None)


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
    commands = json.loads(calls[3].args[1]['commands'])
    assert len(commands) == 7
    assert any(command['command'] == 'captcha' for command in commands)


def test_public_start_grants_shared_access_and_menu(bot, monkeypatch):
    add = Mock(return_value=True)
    monkeypatch.setattr(telegram_subscribers, 'add', add)
    asyncio.run(bot.on_message('/start', 999, None))
    add.assert_called_once_with('999')
    assert bot._call.await_count == 2
    assert 'Общий доступ' in bot._call.call_args_list[0].args[1]['text']
    fields = bot._call.call_args_list[1].args[1]
    assert 'reply_markup' in fields
    assert 'Открыть дашборд' in str(json.loads(fields['reply_markup']))


def test_non_admin_subscriber_gets_manual_menu_and_answer_routing(bot, monkeypatch):
    bot.chat_id = 'different-admin'
    flow = SimpleNamespace(menu=AsyncMock(), answer=AsyncMock(return_value=True))
    bot._manual_flow = flow
    asyncio.run(bot.on_message('/captcha', 123, None))
    flow.menu.assert_awaited_once_with('123')
    asyncio.run(bot.on_message('human answer', 123, 77))
    flow.answer.assert_awaited_once_with('123', 77, 'human answer')


def test_start_and_stop_change_only_this_members_telegram_access(monkeypatch):
    monkeypatch.setattr(telegram_subscribers, '_admin_chat_id', lambda: '123')
    shared_bot = TelegramCaptchaBot()
    shared_bot.chat_id = '123'
    shared_bot._call = AsyncMock()
    flow = SimpleNamespace(menu=AsyncMock(), open=AsyncMock(), answer=AsyncMock(return_value=True))
    shared_bot._manual_flow = flow
    async def run():
        await shared_bot.on_message('/start', 456, None)
        await shared_bot.on_message('/start', 999, None)
        assert telegram_subscribers.is_known('456')
        assert telegram_subscribers.is_known('999')
        await shared_bot.on_message('/captcha', 456, None)
        flow.menu.assert_awaited_once_with('456')
        await shared_bot.on_message('/stop', 456, None)
        assert not telegram_subscribers.is_known('456')
        assert telegram_subscribers.is_known('999')
        old_button = query('mc_open:shared')
        old_button['message']['chat']['id'] = 456
        await shared_bot.on_callback(old_button)
        await shared_bot.on_message('human answer', 456, 7)
        flow.open.assert_not_called()
        flow.answer.assert_not_called()
        old_button['message']['chat']['id'] = 999
        await shared_bot.on_callback(old_button)
        flow.open.assert_awaited_once_with(999, 'shared')
    asyncio.run(run())


@pytest.mark.parametrize('action', ['open', 'resume'])
def test_manual_action_survives_expired_callback_ack(bot, monkeypatch, action):
    bot.chat_id = '123'
    flow = SimpleNamespace(open=AsyncMock(), resume=AsyncMock())
    monkeypatch.setattr(bot, 'manual_flow', lambda: flow)
    async def call(method, fields):
        if method == 'answerCallbackQuery':
            raise RuntimeError('query too old')
    bot._call.side_effect = call
    asyncio.run(bot.on_callback(query('mc_' + action + ':test')))
    getattr(flow, action).assert_awaited_once_with(123, 'test')
    assert bot._call.await_count == 1


def test_manual_action_failure_after_ack_reports_to_user(bot, monkeypatch):
    bot.chat_id = '123'
    flow = SimpleNamespace(open=AsyncMock(side_effect=RuntimeError()))
    monkeypatch.setattr(bot, 'manual_flow', lambda: flow)
    asyncio.run(bot.on_callback(query('mc_open:test')))
    assert bot._call.call_args.args[0] == 'sendMessage'
    assert '/captcha' in bot._call.call_args.args[1]['text']


def test_delivery_exceptions_do_not_log_telegram_token(bot, monkeypatch, caplog):
    import logging
    monkeypatch.setattr(bot, '_chat_targets', lambda: ['123'])
    bot._call.side_effect = RuntimeError('https://api.telegram.org/botPRIVATE_TOKEN/sendMessage')
    async def run():
        await bot.send_message('private message')
        await bot.push_challenge('test', 'test', b'image')
    with caplog.at_level(logging.INFO, logger='app.telegram_bot'):
        asyncio.run(run())
    assert 'PRIVATE_TOKEN' not in caplog.text
    assert 'delivery failed' in caplog.text


def test_browser_solved_button_requires_subscriber(bot, monkeypatch):
    confirm = AsyncMock()
    monkeypatch.setattr(bot, '_confirm_browser_solved', confirm)
    asyncio.run(bot.on_callback(query('bc_done:cid-1')))
    confirm.assert_awaited_once_with(123, 'cid-1')
    confirm.reset_mock()
    stranger = {'id': 'q2', 'data': 'bc_done:cid-1',
                'message': {'chat': {'id': 999}, 'message_id': 7}}
    asyncio.run(bot.on_callback(stranger))
    confirm.assert_not_awaited()


def test_browser_solved_uses_human_confirmation_route(bot, monkeypatch):
    from app import captcha
    from app.routes import accounts
    state = SimpleNamespace(acc={'user_id': 'u1'})
    monkeypatch.setattr(instances.bot, 'account_states', [state], raising=False)
    monkeypatch.setattr(instances.bot, 'temp_states', {}, raising=False)
    monkeypatch.setattr(captcha, 'current', lambda acc: {'id': 'cid-1'})
    seen = {}
    async def fake_continue(idx, request):
        seen['idx'], seen['body'] = idx, await request.json()
        return {'ok': True}
    monkeypatch.setattr(accounts, 'api_account_captcha_continue', fake_continue)
    asyncio.run(bot._confirm_browser_solved(123, 'cid-1'))
    assert seen == {'idx': 0, 'body': {'confirmed': True, 'id': 'cid-1'}}
    bot._call.assert_not_awaited()
    asyncio.run(bot._confirm_browser_solved(123, 'stale-cid'))
    assert 'закрыта' in bot._call.call_args.args[1]['text']
