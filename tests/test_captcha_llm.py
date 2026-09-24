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
    monkeypatch.setattr(CONFIG, 'captcha_llm_max_length', 8)
    monkeypatch.setattr(CONFIG, 'captcha_llm_enabled', True)
    monkeypatch.setattr(CONFIG, 'captcha_llm_solved', 0)
    monkeypatch.setattr(CONFIG, 'captcha_llm_forwarded', 0)
    client = Mock()
    client.with_options.return_value = client
    factory = Mock(return_value=client)
    monkeypatch.setattr(llm, '_make_openai_client', factory)
    return client, factory


@pytest.mark.parametrize('content,expected', [
    ('abc123', 'abc123'), ('unclear', None), ('UNCLEAR', None),
    ('The answer on the image is abc123', None), ('', None), (None, None),
    ('AbC', 'AbC'), ('12345678', '12345678'), ('ab', None),
    ('123456789', None), ('abc-12', None), ('абв', None), (' "Ab12" ', 'Ab12'),
])
def test_recognize(vision, content, expected):
    client, _ = vision
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    assert captcha_llm.recognize_captcha(b'png') == expected
    client.with_options.assert_called_once_with(timeout=15.0, max_retries=0)
    client.close.assert_called_once()


def test_openai_wire_response(vision, monkeypatch):
    import json
    def respond(request):
        body = json.loads(request.content)
        assert request.url.path == '/v1/chat/completions'
        assert body['model'] == 'gpt-4o-mini'
        assert body['max_tokens'] == 20
        assert body['messages'][0]['content'][1]['image_url']['url'] == 'data:image/png;base64,cG5n'
        return httpx.Response(200, json={'choices': [{'message': {'content': 'abc123'}}]})
    monkeypatch.setattr(llm, '_make_openai_client', lambda p: openai.OpenAI(
        api_key=p['api_key'], base_url=p['base_url'], http_client=httpx.Client(transport=httpx.MockTransport(respond))))
    assert captcha_llm.recognize_captcha(b'png') == 'abc123'


def test_empty_key(vision, monkeypatch):
    monkeypatch.setattr(CONFIG, 'llm_profiles', [{'api_key': ''}])
    assert captcha_llm.recognize_captcha(b'png') is None
    vision[1].assert_not_called()


def test_fallback_and_native_provider(vision, monkeypatch):
    monkeypatch.setattr(CONFIG, 'llm_profiles', [
        dict(api_key='test', base_url='https://api.anthropic.com/v1'),
        dict(api_key='test', model='first'), dict(api_key='test', model='second')])
    vision[0].chat.completions.create.side_effect = [RuntimeError('private'),
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='ABC123'))])]
    assert captcha_llm.recognize_captcha(b'png') == 'ABC123'
    assert vision[1].call_count == 2


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
        bot = Mock(push_challenge=AsyncMock(return_value=True), connected=False)
        coordinator = captcha_worker.CaptchaCoordinator(manager, bot)
        await coordinator.scan()
        await coordinator.scan()
        recognize.assert_called_once_with(b'png')
        if accepted:
            assert not captcha.current(acc)
            assert cid not in coordinator.pending
            bot.push_challenge.assert_not_called()
            bot.send_message.assert_not_called()
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
        await coordinator.scan()
        assert recognize.call_count == int(enabled)
        assert bot.push_challenge.await_count == 2
        assert CONFIG.captcha_llm_forwarded == 1
    asyncio.run(run())
