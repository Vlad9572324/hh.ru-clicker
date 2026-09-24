import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app import captcha, captcha_solver, telegram_notify
from app.routes import accounts


@pytest.mark.parametrize('status,location', [(200, ''), (302, 'https://hh.ru/account/login'),
                                          (303, 'https://hh.ru/account/captcha?failed=1')])
def test_unconfirmed_response_never_success(status, location):
    response = Mock(status_code=status, headers={'Location': location})
    response.json.side_effect = ValueError('HTML')
    session = Mock()
    session.post.return_value = response
    assert captcha_solver.submit_captcha(session, 'human', 'key', 'state')[0] is False


def test_telegram_exception_cannot_log_token(monkeypatch):
    logs = []
    monkeypatch.setattr(telegram_notify, '_credentials', lambda: ('synthetic-secret', '123'))
    monkeypatch.setattr(telegram_notify, '_load_sent_events', lambda: {})
    monkeypatch.setattr(telegram_notify, 'log_debug', logs.append)
    monkeypatch.setattr(telegram_notify.requests, 'post', Mock(side_effect=RuntimeError(
        'https://api.telegram.org/botsynthetic-secret/sendMessage')))
    assert not telegram_notify.send_once('test', 'test')
    assert logs and all('synthetic-secret' not in line for line in logs)


@pytest.mark.parametrize('body', [[], {'text': 42}, {'text': 'human', 'id': 'stale', 'key': 'old'}])
def test_invalid_or_stale_ui_answer_never_submitted(monkeypatch, body):
    acc = {'user_id': 'synthetic-route'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test'})
    cid = captcha.current(acc)['id']
    submit = Mock()
    fetch = Mock()
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    monkeypatch.setattr(captcha_solver, 'fetch_captcha_image', fetch)
    monkeypatch.setattr(accounts.bot, '_get_apply_state', lambda idx: SimpleNamespace(acc=acc))
    async def run():
        coord = SimpleNamespace(_lock=asyncio.Lock(), gui_pending={cid: {
            'session': Mock(), 'captcha_key': 'current'}})
        monkeypatch.setattr(accounts.bot, 'telegram_captcha_coordinator', coord, raising=False)
        class Request:
            async def json(self): return body
        result = await accounts.api_account_captcha_solve(0, Request())
        assert result['ok'] is False
    asyncio.run(run())
    submit.assert_not_called()
    fetch.assert_not_called()
    assert captcha.current(acc)['id'] == cid


def test_gui_refresh_replaces_key_without_changing_telegram(monkeypatch):
    acc = {'user_id': 'gui-refresh'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test'})
    cid = captcha.current(acc)['id']
    sessions = [Mock(), Mock()]
    fetch = Mock(side_effect=[(sessions[0], 'key-1', b'png1', 'state', 'https://hh.ru/'),
                              (sessions[1], 'key-2', b'png2', 'state', 'https://hh.ru/')])
    monkeypatch.setattr(captcha_solver, 'fetch_captcha_image', fetch)
    monkeypatch.setattr(accounts.bot, '_get_apply_state', lambda idx: SimpleNamespace(acc=acc))
    async def run():
        tg = {'captcha_key': 'tg-key', 'session': Mock()}
        coord = SimpleNamespace(_lock=asyncio.Lock(), pending={cid: tg})
        monkeypatch.setattr(accounts.bot, 'telegram_captcha_coordinator', coord, raising=False)
        first = await accounts.api_account_captcha_image(0)
        second = await accounts.api_account_captcha_image(0)
        assert first.headers['X-Captcha-Key'] == 'key-1'
        assert second.headers['X-Captcha-Key'] == 'key-2'
        assert coord.gui_pending[cid]['backurl'] == 'https://hh.ru/'
        assert coord.gui_pending[cid]['failurl'] != coord.gui_pending[cid]['backurl']
        sessions[0].close.assert_called_once()
        assert coord.pending[cid] is tg and tg['captcha_key'] == 'tg-key'
    asyncio.run(run())
