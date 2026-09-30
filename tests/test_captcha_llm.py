"""Vision validation, provider fallback, and coordinator auto-submit regressions."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import openai
import pytest

from app import captcha, captcha_llm, captcha_worker, llm
from app.config import CONFIG


@pytest.fixture
def vision(monkeypatch):
    monkeypatch.setattr(CONFIG, 'llm_profiles', [dict(api_key='test', base_url='https://api.openai.com/v1')])
    monkeypatch.setattr(CONFIG, 'llm_api_key', '')
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', True)
    monkeypatch.setattr(CONFIG, 'captcha_llm_solved', 0)
    monkeypatch.setattr(CONFIG, 'captcha_llm_forwarded', 0)
    client = Mock()
    client.with_options.return_value = client
    factory = Mock(return_value=client)
    monkeypatch.setattr(llm, '_make_openai_client', factory)
    return client, factory


def reply(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.mark.parametrize('content,expected', [
    ('клюёшь лунную', 'клюёшь лунную'), (' "Тернисто  Синтез" ', 'тернисто синтез'),
    ('abc123', None), ('одно', None), ('Извините, я не могу помочь с этим изображением.', None),
    ('', None), (None, None),
])
def test_unanimous_readings(vision, content, expected):
    client, _ = vision
    client.chat.completions.create.return_value = reply(content)
    assert captcha_llm.recognize_captcha(b'png') == expected


def test_submits_only_on_consensus(vision):
    client, _ = vision
    # 3 of 8 readings agree: below the 4-vote threshold -> leave it to a human.
    client.chat.completions.create.side_effect = [reply(t) for t in
        ['выеду отпряжена'] * 3 + ['выду отпряжена', 'вылду отпряжена', 'выдаю отпрыжена', 'вчера отпряжена', 'выдача отпечатана']]
    assert captcha_llm.recognize_captcha(b'png') is None
    client.chat.completions.create.side_effect = [reply(t) for t in
        ['сваже мазанные'] * 5 + ['сваже мазанье', 'свахе мазанные', 'сваже магазинные']]
    assert captcha_llm.recognize_captcha(b'png') == 'сваже мазанные'


def test_yo_and_ye_vote_together_and_keep_yo(vision):
    client, _ = vision
    client.chat.completions.create.side_effect = [reply(t) for t in
        ['клюешь лунную', 'клюёшь лунную', 'клюёшь лунную', 'клюешь лунную', 'клюёшь лунную', 'x', 'y', 'z']]
    assert captcha_llm.recognize_captcha(b'png') == 'клюёшь лунную'


def test_openai_wire_request(vision, monkeypatch):
    import json
    seen = []
    def respond(request):
        body = json.loads(request.content)
        seen.append(body['model'])
        assert request.url.path == '/v1/chat/completions'
        assert body['messages'][0]['content'][1]['image_url']['url'] == 'data:image/png;base64,cG5n'
        return httpx.Response(200, json={'choices': [{'message': {'content': 'возл насеваться'}}]})
    monkeypatch.setattr(llm, '_make_openai_client', lambda p: openai.OpenAI(
        api_key=p['api_key'], base_url=p['base_url'], http_client=httpx.Client(transport=httpx.MockTransport(respond))))
    assert captcha_llm.recognize_captcha(b'png') == 'возл насеваться'
    assert sorted(set(seen)) == sorted(captcha_llm._OPENAI_MODELS) and len(seen) == 8


def test_empty_key(vision, monkeypatch):
    monkeypatch.setattr(CONFIG, 'llm_profiles', [{'api_key': ''}])
    assert captcha_llm.recognize_captcha(b'png') is None
    vision[1].assert_not_called()


def test_down_provider_falls_back_and_skips_native_anthropic(vision, monkeypatch):
    monkeypatch.setattr(CONFIG, 'llm_profiles', [
        dict(api_key='test', base_url='https://api.anthropic.com/v1'),
        dict(api_key='test', base_url='https://down.example/v1', model='first'),
        dict(api_key='test', base_url='https://up.example/v1', model='second')])
    calls = []
    def create(**kw):
        calls.append(kw['model'])
        if kw['model'] == 'first':
            raise RuntimeError('private')
        return reply('откаткой ангелу')
    vision[0].chat.completions.create.side_effect = create
    assert captcha_llm.recognize_captcha(b'png') == 'откаткой ангелу'
    assert calls.count('first') == 3 and calls.count('second') == 3


@pytest.mark.parametrize('answer,accepted', [('Ab123', True), ('Ab123', False), (None, False)])
def test_coordinator(vision, monkeypatch, answer, accepted):
    acc = {'user_id': 'vision-account'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test'})
    cid = captcha.current(acc)['id']
    manager = SimpleNamespace(account_states=[SimpleNamespace(acc=acc)], temp_states={},
                              resume_challenge_account=Mock(), _add_log=Mock())
    session = Mock()
    fetch = Mock(return_value=(session, 'key', b'png', 'test', 'https://hh.ru/'))
    recognize = Mock(return_value=answer)
    submit = Mock(return_value=(accepted, 'isBot'))
    monkeypatch.setattr(captcha_worker, 'fetch_captcha_image', fetch)
    monkeypatch.setattr(captcha_worker, 'recognize_captcha', recognize)
    monkeypatch.setattr(captcha_worker, 'submit_captcha', submit)
    async def run():
        bot = Mock(push_challenge=AsyncMock(return_value=True),
                   send_message=AsyncMock(return_value=None), connected=False)
        coordinator = captcha_worker.CaptchaCoordinator(manager, bot)
        await coordinator.scan()
        await coordinator.scan()
        recognize.assert_called_once_with(b'png')
        if accepted:
            assert not captcha.current(acc)
            assert cid not in coordinator.pending
            bot.push_challenge.assert_not_called()
            bot.send_message.assert_awaited_once()
            manager.resume_challenge_account.assert_called_once_with('vision-account')
            assert CONFIG.captcha_llm_solved == 1
        else:
            assert cid in coordinator.pending
            assert CONFIG.captcha_llm_forwarded == 1
            bot.push_challenge.assert_awaited_once()
            assert fetch.call_count == (2 if answer else 1)
        if answer:
            submit.assert_called_once_with(session, answer, 'key', 'test', 'https://hh.ru/', 'https://hh.ru/')
        else:
            submit.assert_not_called()
    asyncio.run(run())


@pytest.mark.parametrize('enabled', [False, True])
def test_delivery_retry_does_not_repeat_llm(vision, monkeypatch, enabled):
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', enabled)
    acc = {'user_id': 'retry-account'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test'})
    manager = SimpleNamespace(account_states=[SimpleNamespace(acc=acc)], temp_states={})
    recognize = Mock(side_effect=RuntimeError('provider unavailable'))
    monkeypatch.setattr(captcha_worker, 'recognize_captcha', recognize)
    monkeypatch.setattr(captcha_worker, 'fetch_captcha_image', Mock(
        return_value=(Mock(), 'key', b'png', 'test', 'https://hh.ru/')))
    async def run():
        bot = Mock(push_challenge=AsyncMock(side_effect=[RuntimeError('offline'), True]))
        coordinator = captcha_worker.CaptchaCoordinator(manager, bot)
        await coordinator.scan()
        await coordinator.scan()
        assert bot.push_challenge.await_count == 1  # backoff: no hammering HH
        for item in coordinator.pending.values():
            assert item['retry_delay'] == 30
            item['retry_at'] = 0
        await coordinator.scan()
        assert recognize.call_count == int(enabled)
        assert bot.push_challenge.await_count == 2
        assert CONFIG.captcha_llm_forwarded == 1
    asyncio.run(run())


def test_coordinator_exposes_llm_outcome_for_the_card(vision, monkeypatch):
    acc = {'user_id': 'card-account'}
    captcha.hold(acc, {'captcha_url': 'https://hh.ru/account/captcha?state=test'})
    cid = captcha.current(acc)['id']
    manager = SimpleNamespace(account_states=[SimpleNamespace(acc=acc)], temp_states={},
                              resume_challenge_account=Mock(), _add_log=Mock())
    monkeypatch.setattr(captcha_worker, 'fetch_captcha_image', Mock(
        return_value=(Mock(), 'key', b'png', 'test', 'https://hh.ru/')))
    monkeypatch.setattr(captcha_worker, 'recognize_captcha', Mock(return_value=None))
    async def run():
        bot = Mock(push_challenge=AsyncMock(return_value=True), send_browser_option=AsyncMock())
        coordinator = captcha_worker.CaptchaCoordinator(manager, bot)
        await coordinator.scan()
        assert coordinator.pending[cid]['llm_result'] == {'status': 'unsure'}
        assert 'не уверена' in bot.push_challenge.await_args.kwargs['note']
    asyncio.run(run())
