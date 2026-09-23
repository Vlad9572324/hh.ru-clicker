"""Exercise Telegram HTTP payloads, polling, flood retries, and authorized reply routing."""
import asyncio
from unittest.mock import AsyncMock, Mock
import pytest
from app.config import CONFIG
from app.telegram_bot import TelegramCaptchaBot


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(CONFIG, 'telegram_bot_token', 'test-placeholder')
    monkeypatch.setattr(CONFIG, 'telegram_chat_id', '-123')
    return TelegramCaptchaBot(AsyncMock())


def test_photo_and_reply(bot):
    async def run():
        bot._call = AsyncMock(return_value={'message_id': 7})
        await bot.push_challenge('cid', 'test', b'png')
        method, fields, image = bot._call.call_args.args
        assert method == 'sendPhoto' and image == b'png'
        assert fields['chat_id'] == '-123' and 'test' in fields['caption']
        await bot.on_message('text', 999, 7)  # wrong chat_id → ignore
        bot.resolver.assert_not_called()
        # Fallback: если pending содержит ровно 1 challenge, любое сообщение
        # (даже без reply_to) → resolver вызван (UX: юзеру не нужно жать "Ответить").
        await bot.on_message('text', -123, 8)
        bot.resolver.assert_awaited_once_with('cid', 'text')
        bot.resolver.reset_mock()
        await bot.on_message(' text ', -123, 7)
        bot.resolver.assert_awaited_once_with('cid', 'text')
        await bot.push_challenge('cid', 'test', b'new')
        assert bot._call.call_args.args[0] == 'editMessageMedia'
        bot.forget('cid')
        assert not bot.pending
    asyncio.run(asyncio.wait_for(run(), 5))


def test_http_flood(bot, monkeypatch):
    async def run():
        response = AsyncMock()
        response.status = 200
        response.json.side_effect = [dict(ok=False, error_code=429, parameters={'retry_after': 1}),
                                     dict(ok=True, result={'message_id': 5})]
        context = AsyncMock()
        context.__aenter__.return_value = response
        bot._session = Mock()
        bot._session.post.return_value = context
        sleep = AsyncMock()
        monkeypatch.setattr('app.telegram_bot.asyncio.sleep', sleep)
        assert await bot.push_challenge('cid', 'test', b'image') == {'message_id': 5}
        sleep.assert_awaited_once_with(1)
        data = bot._session.post.call_args.kwargs['data']
        fields = {field[0]['name']: field[2] for field in data._fields}
        assert fields['photo'] == b'image' and fields['chat_id'] == '-123'
    asyncio.run(asyncio.wait_for(run(), 5))


def test_poll(bot):
    async def run():
        bot.pending[7] = 'cid'
        bot._call = AsyncMock(side_effect=[[
            {'update_id': 100, 'message': {'text': 'answer', 'chat': {'id': -123},
                                         'reply_to_message': {'message_id': 7}}}], asyncio.CancelledError()])
        with pytest.raises(asyncio.CancelledError):
            await bot._poll()
        assert bot._offset == 101
        bot.resolver.assert_awaited_once_with('cid', 'answer')
    asyncio.run(asyncio.wait_for(run(), 5))


def test_disabled(monkeypatch):
    monkeypatch.setattr(CONFIG, 'telegram_bot_token', '')
    async def run():
        bot = TelegramCaptchaBot()
        await bot.start()
        assert await bot.push_challenge('cid', 'test', b'image') is None
        await bot.stop()
    asyncio.run(asyncio.wait_for(run(), 5))
