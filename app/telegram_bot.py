"""Telegram HTTP long polling: send captcha photos and route human replies to a resolver."""
import asyncio
import contextlib
import json
import logging

import aiohttp
from app.config import CONFIG

logger = logging.getLogger(__name__)


class TelegramCaptchaBot:
    def __init__(self, resolver=None):
        self.token = str(CONFIG.telegram_bot_token).strip()
        self.chat_id = str(CONFIG.telegram_chat_id).strip()
        self.resolver = resolver
        self.pending = {}
        self.connected = False
        self._task = None
        self._session = None
        self._offset = 0

    async def start(self):
        if not self.token or not self.chat_id:
            logger.info('TG bot disabled')
            return
        if self._task is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
            self._task = asyncio.create_task(self._poll())

    async def stop(self):
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._session:
            await self._session.close()
            self._session = None
        self.connected = False

    async def _call(self, method, fields, image=None):
        if not self.token or not self.chat_id:
            logger.info('TG bot disabled')
            return None
        if self._session is None:
            raise RuntimeError('TG bot offline')
        for attempt in range(4):
            data = aiohttp.FormData()
            for key, value in fields.items():
                data.add_field(key, str(value))
            if image is not None:
                data.add_field('photo', image, filename='captcha.png', content_type='image/png')
            async with self._session.post(
                    f'https://api.telegram.org/bot{self.token}/{method}', data=data) as response:
                body = await response.json()
                if response.status == 429 or body.get('error_code') == 429:
                    self.connected = False
                    if attempt < 3:
                        await asyncio.sleep(max(1, int(body.get('parameters', {}).get('retry_after', 1))))
                        continue
                if not body.get('ok'):
                    self.connected = False
                    # Полный лог ответа TG чтобы понять причину (Bad Request / message can't be edited / etc)
                    logger.warning('Telegram API %s failed: %s', method, body)
                    raise RuntimeError(f'Telegram API {method} failed: {body.get("description", body)}')
                self.connected = True
                return body.get('result')
        raise RuntimeError('Telegram flood limit')

    async def push_challenge(self, challenge_id, acc_short, image_bytes):
        caption = f'🔐 Капча для {acc_short}. Ответьте текстом с картинки'
        previous = next((mid for mid, cid in self.pending.items() if cid == challenge_id), None)
        # editMessageMedia может фейлить (message старее 48ч, удалён юзером,
        # 'photo is not modified' и т.д.) — тогда fallback на новое sendPhoto.
        if previous is not None:
            try:
                fields = {'chat_id': self.chat_id, 'message_id': previous,
                          'media': json.dumps({'type': 'photo', 'media': 'attach://photo',
                                               'caption': caption}, ensure_ascii=False)}
                result = await self._call('editMessageMedia', fields, image_bytes)
                if result:
                    self.pending[result['message_id']] = challenge_id
                return result
            except Exception as exc:
                logger.info('editMessageMedia failed (%s) → fallback to sendPhoto', exc)
                # Забываем старую привязку — новое sendPhoto ниже
                self.pending = {mid: cid for mid, cid in self.pending.items() if cid != challenge_id}
        # Свежее фото: previous не было или edit провалился → sendPhoto.
        fields = {'chat_id': self.chat_id,
                  'caption': caption,
                  'reply_markup': json.dumps({'force_reply': True})}
        result = await self._call('sendPhoto', fields, image_bytes)
        if result:
            self.pending[result['message_id']] = challenge_id
        return result

    def forget(self, challenge_id):
        self.pending = {mid: cid for mid, cid in self.pending.items() if cid != challenge_id}

    async def send_message(self, text):
        return await self._call('sendMessage', {'chat_id': self.chat_id, 'text': text})

    async def on_message(self, text, chat_id, reply_to_message_id):
        if str(chat_id) != self.chat_id or not isinstance(text, str) or not text.strip():
            return
        challenge_id = self.pending.get(reply_to_message_id)
        # Only an explicit reply to the current challenge is an answer.
        if challenge_id and self.resolver:
            await self.resolver(challenge_id, text.strip())

    async def _poll(self):
        while True:
            try:
                updates = await self._call('getUpdates', {
                    'offset': self._offset, 'timeout': 5, 'allowed_updates': '["message"]'})
                for update in updates or []:
                    # Consume once: replaying a human answer against a refreshed image is unsafe.
                    self._offset = update['update_id'] + 1
                    message = update.get('message', {})
                    try:
                        await self.on_message(message.get('text'), message.get('chat', {}).get('id'),
                                              message.get('reply_to_message', {}).get('message_id'))
                    except Exception:
                        logger.warning('TG answer processing failed; waiting for another human reply')
            except asyncio.CancelledError:
                raise
            except Exception:
                self.connected = False
                logger.warning('TG polling or answer processing failed')
                await asyncio.sleep(3)
