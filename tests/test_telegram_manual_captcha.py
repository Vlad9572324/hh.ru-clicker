import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from app import captcha, telegram_manual_captcha as manual


@pytest.fixture
def fixture(monkeypatch):
    acc = {'user_id': 'manual-test'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test'})
    cid = captcha.current(acc)['id']
    state = SimpleNamespace(acc=acc)
    bot = SimpleNamespace(_call=AsyncMock(return_value={'message_id': 7}))
    manager = SimpleNamespace(account_states=[state], temp_states={}, paused=False)
    flow = manual.ManualCaptchaFlow(manager, bot)
    session = Mock()
    monkeypatch.setattr(manual, 'fetch_captcha_image', Mock(return_value=(session, 'key', b'png', 'state', 'https://hh.ru/')))
    monkeypatch.setattr(manual, 'verify_manual_completion', Mock(return_value=(False, 'unconfirmed_verification')))
    return flow, bot, acc, cid, session


@pytest.mark.parametrize('ok,reason', [(True, ''), (False, 'isBot'), (False, 'unconfirmed_response')])
def test_manual_answer_never_auto_resumes(fixture, monkeypatch, ok, reason):
    flow, bot, acc, cid, session = fixture
    submit = Mock(return_value=(ok, reason))
    monkeypatch.setattr(manual, 'submit_captcha', submit)
    async def run():
        await flow.open('123', cid)
        assert await flow.answer('123', 7, 'human')
        assert await flow.answer('123', 7, 'human')
    asyncio.run(run())
    submit.assert_called_once()
    assert submit.call_args.kwargs['require_confirmation'] is True
    assert captcha.current(acc)['id'] == cid
    assert captcha.current(acc)['manual_only'] is True
    assert next(iter(flow.items.values()))['status'] == ('confirmed' if ok else 'submitted')


def test_repeated_open_does_not_refetch(fixture):
    flow, bot, acc, cid, session = fixture
    async def run():
        await flow.open('123', cid)
        await flow.open('123', cid)
    asyncio.run(run())
    manual.fetch_captcha_image.assert_called_once()
    fields = bot._call.call_args.args[1]
    assert fields['reply_to_message_id'] == 7
    assert 'не блокировка HH' in fields['text']
    assert 'через минуту' not in fields['text']


def test_old_message_and_other_chat_cannot_answer(fixture, monkeypatch):
    flow, bot, acc, cid, session = fixture
    submit = Mock()
    monkeypatch.setattr(manual, 'submit_captcha', submit)
    async def run():
        await flow.open('123', cid)
        assert not await flow.answer('456', 7, 'human')
        assert not await flow.answer('123', 6, 'human')
        captcha.clear(acc, cid)
        assert await flow.answer('123', 7, 'human')
    asyncio.run(run())
    submit.assert_not_called()


def test_explicit_resume_uses_existing_guarded_route(fixture, monkeypatch):
    from app.routes import accounts
    flow, bot, acc, cid, session = fixture
    monkeypatch.setattr(manual, 'submit_captcha', Mock(return_value=(True, '')))
    route = AsyncMock(return_value={'ok': False, 'error': 'Есть другая защитная пауза'})
    monkeypatch.setattr(accounts, 'api_account_captcha_continue', route)
    async def run():
        await flow.open('123', cid)
        await flow.answer('123', 7, 'human')
        token = next(iter(flow.items))
        await flow.resume('456', token)
        route.assert_awaited_once()
        assert await route.call_args.args[1].json() == {'confirmed': True, 'id': cid}
    asyncio.run(run())
    assert captcha.current(acc)


def test_other_member_can_continue_shared_confirmation_without_new_image(fixture, monkeypatch):
    from app.routes import accounts
    flow, bot, acc, cid, session = fixture
    monkeypatch.setattr(manual, 'submit_captcha', Mock(return_value=(True, '')))
    route = AsyncMock(return_value={'ok': True, 'message': 'Продолжение разрешено'})
    monkeypatch.setattr(accounts, 'api_account_captcha_continue', route)
    async def run():
        await flow.open('123', cid)
        await flow.answer('123', 7, 'human')
        token = next(iter(flow.items))
        await flow.menu('456')
        assert 'mc_resume:' + token in bot._call.call_args.args[1]['reply_markup']
        await flow.open('456', cid)
        assert 'mc_resume:' + token in bot._call.call_args.args[1]['reply_markup']
        await flow.resume('456', token)
        await flow.resume('123', token)
    asyncio.run(run())
    manual.fetch_captcha_image.assert_called_once()
    route.assert_awaited_once()


def test_submission_timeout_is_not_retried(fixture, monkeypatch):
    flow, bot, acc, cid, session = fixture
    submit = Mock(side_effect=TimeoutError())
    monkeypatch.setattr(manual, 'submit_captcha', submit)
    async def run():
        await flow.open('123', cid)
        await flow.answer('123', 7, 'human')
        await flow.answer('123', 7, 'human')
    asyncio.run(run())
    submit.assert_called_once()
    assert captcha.current(acc)


@pytest.mark.parametrize('reason', ['http_429', 'http_500', 'unconfirmed_response'])
def test_transport_errors_are_not_wrong_answers(fixture, monkeypatch, reason):
    flow, bot, acc, cid, session = fixture
    monkeypatch.setattr(manual, 'submit_captcha', Mock(return_value=(False, reason)))
    async def run():
        await flow.open('123', cid)
        await flow.answer('123', 7, 'human')
    asyncio.run(run())
    assert 'не принял ответ' not in bot._call.call_args.args[1]['text']
    assert captcha.current(acc)
    if reason.startswith('http_'):
        manual.verify_manual_completion.assert_not_called()


def test_unknown_post_can_be_confirmed_by_same_session_get(fixture, monkeypatch):
    flow, bot, acc, cid, session = fixture
    submit = Mock(return_value=(False, 'unconfirmed_response'))
    verify = Mock(return_value=(True, ''))
    monkeypatch.setattr(manual, 'submit_captcha', submit)
    monkeypatch.setattr(manual, 'verify_manual_completion', verify)
    async def run():
        await flow.open('123', cid)
        await flow.answer('123', 7, 'human')
    asyncio.run(run())
    submit.assert_called_once()
    verify.assert_called_once()
    assert verify.call_args.args[0] is session
    assert 'manual_captcha_return=' in verify.call_args.args[2]
    assert next(iter(flow.items.values()))['status'] == 'confirmed'
    assert captcha.current(acc)


def test_success_requires_a_separate_confirmation_and_cannot_repeat(fixture, monkeypatch):
    from app.routes import accounts
    flow, bot, acc, cid, session = fixture
    monkeypatch.setattr(manual, 'submit_captcha', Mock(return_value=(True, '')))
    route = AsyncMock(return_value={'ok': True, 'message': 'Продолжение разрешено'})
    monkeypatch.setattr(accounts, 'api_account_captcha_continue', route)
    async def run():
        await flow.open('123', cid)
        await flow.answer('123', 7, 'human')
        route.assert_not_called()
        await flow.menu('123')
        assert 'mc_resume:' in bot._call.call_args.args[1]['reply_markup']
        token = next(iter(flow.items))
        await flow.resume('123', token)
        await flow.resume('123', token)
    asyncio.run(run())
    route.assert_awaited_once()


@pytest.mark.parametrize('status,location,expected', [
    (200, '', False), (302, '', True), (302, '/', True), (303, '', False),
    (302, '/account/login', False), (302, 'https://example.org/', False)])
def test_manual_mode_requires_specific_success_signal(status, location, expected):
    from app.captcha_solver import submit_captcha
    session = Mock()
    session.cookies.get.return_value = 'test'
    session.post.return_value = Mock(status_code=status, headers={'Location': location}, json=lambda: {})
    assert submit_captcha(session, 'human', 'key', 'state', 'https://hh.ru/',
                          'https://hh.ru/account/captcha?state=test', require_confirmation=True)[0] is expected


def test_hh_xhr_302_offers_confirmation_instead_of_unknown_and_cooldown(fixture, monkeypatch):
    from app.captcha_solver import submit_captcha
    flow, bot, acc, cid, session = fixture
    monkeypatch.setattr(manual, 'submit_captcha', submit_captcha)
    session.cookies.get.return_value = 'test'
    response = Mock(status_code=302, headers={})
    response.json.side_effect = ValueError('empty XHR response')
    session.post.return_value = response
    async def run():
        await flow.open('123', cid)
        await flow.answer('123', 7, 'human answer')
        assert next(iter(flow.items.values()))['status'] == 'confirmed'
        assert 'mc_resume:' in bot._call.call_args.args[1]['reply_markup']
        await flow.open('123', cid)
        assert 'mc_resume:' in bot._call.call_args.args[1]['reply_markup']
        assert 'через' not in bot._call.call_args.args[1]['text']
    asyncio.run(run())
    session.post.assert_called_once()
    manual.verify_manual_completion.assert_not_called()
    manual.fetch_captcha_image.assert_called_once()
    assert captcha.current(acc)['id'] == cid


def test_delivered_photo_survives_optional_instruction_failure(fixture, monkeypatch):
    flow, bot, acc, cid, session = fixture
    bot._call.side_effect = [{}, {'message_id': 7}, RuntimeError('Telegram unavailable'), {}]
    submit = Mock(return_value=(True, ''))
    monkeypatch.setattr(manual, 'submit_captcha', submit)
    async def run():
        await flow.open('123', cid)
        session.close.assert_not_called()
        assert await flow.answer('123', 7, 'human')
    asyncio.run(run())
    submit.assert_called_once()
    assert next(iter(flow.items.values()))['status'] == 'confirmed'


def test_menu_returns_user_to_waiting_photo_without_loading_new_one(fixture):
    flow, bot, acc, cid, session = fixture
    async def run():
        await flow.open('123', cid)
        bot._call.reset_mock()
        await flow.menu('123')
    asyncio.run(run())
    manual.fetch_captcha_image.assert_called_once()
    reminder = bot._call.call_args_list[0].args[1]
    assert reminder['reply_to_message_id'] == 7
    assert 'Загружать заново не нужно' in reminder['text']
    assert next(iter(flow.items.values()))['status'] == 'waiting'


def test_replaced_photo_reply_does_not_fall_through_to_legacy_flow(fixture, monkeypatch):
    flow, bot, acc, cid, session = fixture
    submit = Mock()
    monkeypatch.setattr(manual, 'submit_captcha', submit)
    async def run():
        await flow.open('123', cid)
        flow.cooldown.clear()
        bot._call.return_value = {'message_id': 8}
        await flow.open('123', cid)
        assert await flow.answer('123', 7, 'human')
        assert not await flow.answer('456', 7, 'human')
    asyncio.run(run())
    submit.assert_not_called()
    assert next(iter(flow.items.values()))['mid'] == 8


def test_expired_photo_is_closed_and_answer_rejected(fixture, monkeypatch):
    flow, bot, acc, cid, session = fixture
    submit = Mock()
    monkeypatch.setattr(manual, 'submit_captcha', submit)
    async def run():
        await flow.open('123', cid)
        next(iter(flow.items.values()))['created'] -= 601
        assert await flow.answer('123', 7, 'human')
    asyncio.run(run())
    submit.assert_not_called()
    session.close.assert_called_once()
    assert not flow.items


@pytest.mark.parametrize('answer', ['', '  ', None, 'x' * 201])
def test_invalid_answer_does_not_consume_photo(fixture, monkeypatch, answer):
    flow, bot, acc, cid, session = fixture
    submit = Mock()
    monkeypatch.setattr(manual, 'submit_captcha', submit)
    async def run():
        await flow.open('123', cid)
        assert await flow.answer('123', 7, answer)
    asyncio.run(run())
    submit.assert_not_called()
    assert next(iter(flow.items.values()))['status'] == 'waiting'


def test_late_success_for_replaced_challenge_never_offers_resume(fixture, monkeypatch):
    flow, bot, acc, cid, session = fixture
    def submit(*args, **kwargs):
        captcha.clear(acc, cid)
        captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=replaced'})
        return True, ''
    monkeypatch.setattr(manual, 'submit_captcha', submit)
    async def run():
        await flow.open('123', cid)
        assert await flow.answer('123', 7, 'human')
    asyncio.run(run())
    assert captcha.current(acc)['id'] != cid
    assert not flow.items
    fields = bot._call.call_args.args[1]
    assert 'изменилась' in fields['text']
    assert 'reply_markup' not in fields
    session.close.assert_called_once()


def test_close_defers_session_cleanup_until_cancelled_submit_finishes(fixture, monkeypatch):
    import threading
    flow, bot, acc, cid, session = fixture
    release = threading.Event()
    async def run():
        started = asyncio.Event()
        loop = asyncio.get_running_loop()
        def submit(*args, **kwargs):
            loop.call_soon_threadsafe(started.set)
            assert release.wait(2)
            return True, ''
        monkeypatch.setattr(manual, 'submit_captcha', submit)
        await flow.open('123', cid)
        answer = asyncio.create_task(flow.answer('123', 7, 'human'))
        await asyncio.wait_for(started.wait(), 1)
        item = next(iter(flow.items.values()))
        request = item['in_flight']
        answer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await answer
        flow.close()
        session.close.assert_not_called()
        release.set()
        await request
        await asyncio.sleep(0)
        session.close.assert_called_once()
        assert not flow.items
        assert await flow.answer('123', 7, 'human')
    try:
        asyncio.run(run())
    finally:
        release.set()


def test_cancelled_fetch_closes_late_session(fixture, monkeypatch):
    import threading
    flow, bot, acc, cid, session = fixture
    release = threading.Event()
    async def run():
        started, closed = asyncio.Event(), asyncio.Event()
        loop = asyncio.get_running_loop()
        session.close.side_effect = lambda: loop.call_soon_threadsafe(closed.set)
        def fetch(*args):
            loop.call_soon_threadsafe(started.set)
            assert release.wait(2)
            return session, 'key', b'png', 'state', 'https://hh.ru/'
        monkeypatch.setattr(manual, 'fetch_captcha_image', fetch)
        opening = asyncio.create_task(flow.open('123', cid))
        await asyncio.wait_for(started.wait(), 1)
        opening.cancel()
        with pytest.raises(asyncio.CancelledError):
            await opening
        release.set()
        await asyncio.wait_for(closed.wait(), 1)
        assert not flow.items
    try:
        asyncio.run(run())
    finally:
        release.set()
    session.close.assert_called_once()
