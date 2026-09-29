import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
from app import captcha, captcha_solver, telegram_notify
from app.routes import accounts


@pytest.mark.parametrize('status,location,expected', [(302, 'https://hh.ru/account/login', False),
                                          (303, 'https://hh.ru/account/captcha?failed=1', False)])
def test_unconfirmed_response_never_success(status, location, expected):
    response = Mock(status_code=status, headers={'Location': location})
    response.json.side_effect = ValueError('HTML')
    session = Mock()
    session.post.return_value = response
    assert captcha_solver.submit_captcha(session, 'human', 'key', 'state')[0] is expected


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


@pytest.fixture
def gui_flow(monkeypatch):
    from urllib.parse import urlsplit, parse_qs
    acc = {'user_id': 'gui-manual'}
    state = SimpleNamespace(acc=acc, _deleted=False, paused=True, paused_reason='challenge')
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test'})
    cid = captcha.current(acc)['id']
    session = Mock()
    def fetch(acc, url):
        return session, 'key', b'png', 'state', parse_qs(urlsplit(url).query)['backurl'][0]
    monkeypatch.setattr(captcha_solver, 'fetch_captcha_image', Mock(side_effect=fetch))
    monkeypatch.setattr(captcha_solver, 'verify_manual_completion', Mock(return_value=(False, 'unconfirmed_verification')))
    monkeypatch.setattr(accounts.bot, '_get_apply_state', lambda idx: state)
    resume = Mock()
    monkeypatch.setattr(accounts.bot, 'resume_challenge_account', resume)
    coord = SimpleNamespace(_lock=asyncio.Lock(), gui_pending={}, pending={})
    monkeypatch.setattr(accounts.bot, 'telegram_captcha_coordinator', coord, raising=False)
    request = SimpleNamespace(json=AsyncMock(return_value={'text': 'human', 'id': cid, 'key': 'key'}))
    return acc, cid, state, coord, request, session, resume


@pytest.mark.parametrize('result', [(True, ''), (False, 'unconfirmed_response'),
                                   (False, 'isBot'), (False, 'http_429')])
def test_gui_single_submission_never_auto_resumes(gui_flow, monkeypatch, result):
    acc, cid, state, coord, request, session, resume = gui_flow
    submit = Mock(return_value=result)
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    async def run():
        await accounts.api_account_captcha_image(0)
        first = await accounts.api_account_captcha_solve(0, request)
        second = await accounts.api_account_captcha_solve(0, request)
        assert first['ok'] is result[0]
        assert not second['ok']
        if result[0]:
            assert first['requires_confirmation'] and first['id'] == cid
    asyncio.run(run())
    submit.assert_called_once()
    assert submit.call_args.kwargs['require_confirmation'] is True
    assert 'manual_captcha_return=' in submit.call_args.args[4]
    resume.assert_not_called()
    assert captcha.current(acc)['manual_only']
    assert state.paused and state.paused_reason == 'challenge'
    if result[1] == 'http_429':
        captcha_solver.verify_manual_completion.assert_not_called()


def test_gui_timeout_never_replays(gui_flow, monkeypatch):
    acc, cid, state, coord, request, session, resume = gui_flow
    submit = Mock(side_effect=TimeoutError())
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    async def run():
        await accounts.api_account_captcha_image(0)
        assert (await accounts.api_account_captcha_solve(0, request))['unconfirmed']
        assert not (await accounts.api_account_captcha_solve(0, request))['ok']
    asyncio.run(run())
    submit.assert_called_once()
    resume.assert_not_called()


def test_gui_expired_image_is_not_submitted(gui_flow, monkeypatch):
    acc, cid, state, coord, request, session, resume = gui_flow
    submit = Mock()
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    async def run():
        await accounts.api_account_captcha_image(0)
        coord.gui_pending[cid]['created'] -= 601
        assert not (await accounts.api_account_captcha_solve(0, request))['ok']
    asyncio.run(run())
    submit.assert_not_called()


def test_gui_confirmation_uses_guarded_continue_and_preserves_global_pause(gui_flow, monkeypatch):
    import threading
    acc, cid, state, coord, request, session, resume = gui_flow
    state._state_lock = threading.RLock()
    state.pending_apply = None
    state.pending_applies = {}
    state.hard_stopped = state.limit_exceeded = state.cookies_expired = False
    state.consecutive_errors = 1
    monkeypatch.setattr(accounts.bot, 'paused', True)
    persist = Mock()
    monkeypatch.setattr(accounts.bot, '_persist_pauses', persist)
    monkeypatch.setattr(captcha_solver, 'submit_captcha', Mock(return_value=(True, '')))
    async def run():
        await accounts.api_account_captcha_image(0)
        assert (await accounts.api_account_captcha_solve(0, request))['requires_confirmation']
        assert state.paused
        confirmation = SimpleNamespace(json=AsyncMock(return_value={'id': cid, 'confirmed': True}))
        assert (await accounts.api_account_captcha_continue(0, confirmation))['ok']
    asyncio.run(run())
    assert not state.paused and not captcha.current(acc)
    assert accounts.bot.paused
    persist.assert_called_once_with(wait=True)
    resume.assert_not_called()


def test_gui_failed_refresh_keeps_previous_session(gui_flow, monkeypatch):
    acc, cid, state, coord, request, session, resume = gui_flow
    async def run():
        await accounts.api_account_captcha_image(0)
        previous = coord.gui_pending[cid]
        monkeypatch.setattr(captcha_solver, 'fetch_captcha_image', Mock(side_effect=TimeoutError()))
        assert not (await accounts.api_account_captcha_image(0))['ok']
        assert coord.gui_pending[cid] is previous
        session.close.assert_not_called()
    asyncio.run(run())


def test_gui_stale_success_does_not_confirm_replacement(gui_flow, monkeypatch):
    acc, cid, state, coord, request, session, resume = gui_flow
    def submit(*args, **kwargs):
        captcha.clear(acc, cid)
        captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=new'})
        return True, ''
    monkeypatch.setattr(captcha_solver, 'submit_captcha', submit)
    async def run():
        await accounts.api_account_captcha_image(0)
        result = await accounts.api_account_captcha_solve(0, request)
        assert not result['ok'] and 'изменилась' in result['error']
    asyncio.run(run())
    assert captcha.current(acc)['id'] != cid
    resume.assert_not_called()


@pytest.mark.parametrize('stage', ['fetch', 'submit'])
def test_cancelled_gui_request_closes_session_after_thread_finishes(gui_flow, monkeypatch, stage):
    import threading
    acc, cid, state, coord, request, session, resume = gui_flow
    release = threading.Event()
    async def run():
        started, closed = asyncio.Event(), asyncio.Event()
        loop = asyncio.get_running_loop()
        session.close.side_effect = lambda: loop.call_soon_threadsafe(closed.set)
        def operation(*args, **kwargs):
            loop.call_soon_threadsafe(started.set)
            assert release.wait(2)
            return ((session, 'key', b'png', 'state', 'https://hh.ru/')
                    if stage == 'fetch' else (True, ''))
        if stage == 'submit':
            await accounts.api_account_captcha_image(0)
            monkeypatch.setattr(captcha_solver, 'submit_captcha', operation)
            work = asyncio.create_task(accounts.api_account_captcha_solve(0, request))
        else:
            monkeypatch.setattr(captcha_solver, 'fetch_captcha_image', operation)
            work = asyncio.create_task(accounts.api_account_captcha_image(0))
        await asyncio.wait_for(started.wait(), 1)
        work.cancel()
        with pytest.raises(asyncio.CancelledError):
            await work
        session.close.assert_not_called()
        assert cid not in coord.gui_pending
        release.set()
        await asyncio.wait_for(closed.wait(), 1)
        assert captcha.current(acc)['id'] == cid
    try:
        asyncio.run(run())
    finally:
        release.set()
    session.close.assert_called_once()
    resume.assert_not_called()


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
