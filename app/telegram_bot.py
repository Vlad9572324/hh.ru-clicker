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
        # Требуется только token; chat_id (для admin-специфичных вызовов)
        # проверяется вызывающим кодом. Broadcasts используют fields['chat_id']
        # напрямую (может быть любой подписчик), не self.chat_id.
        if not self.token:
            logger.info('TG bot disabled (no token)')
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

    def _chat_targets(self):
        """Broadcast targets: admin + все /start-подписчики (multi-user)."""
        try:
            from app.telegram_subscribers import list_all as _sub_list
            targets = _sub_list()
        except Exception:
            targets = []
        if not targets and self.chat_id:
            targets = [self.chat_id]
        return targets

    async def push_challenge(self, challenge_id, acc_short, image_bytes):
        """Рассылка капчи ВСЕМ подписчикам. Хранит message_id per (chat, cid)."""
        caption = f'🔐 Капча для {acc_short}. Ответьте текстом с картинки'
        # pending структура: {message_id: (chat_id, challenge_id)}
        if not hasattr(self, 'pending_chats'):
            self.pending_chats = {}  # {(chat_id, cid): message_id}
        first_result = None
        for chat_id in self._chat_targets():
            previous = self.pending_chats.get((str(chat_id), challenge_id))
            if previous is not None:
                try:
                    fields = {'chat_id': chat_id, 'message_id': previous,
                              'media': json.dumps({'type': 'photo', 'media': 'attach://photo',
                                                   'caption': caption}, ensure_ascii=False)}
                    r = await self._call('editMessageMedia', fields, image_bytes)
                    if r:
                        self.pending_chats[(str(chat_id), challenge_id)] = r['message_id']
                        self.pending[r['message_id']] = challenge_id
                        first_result = first_result or r
                        continue
                except Exception as exc:
                    logger.info('editMessageMedia(%s) failed (%s) → fallback sendPhoto', chat_id, exc)
                    self.pending_chats.pop((str(chat_id), challenge_id), None)
            fields = {'chat_id': chat_id, 'caption': caption,
                      'reply_markup': json.dumps({'force_reply': True})}
            try:
                r = await self._call('sendPhoto', fields, image_bytes)
                if r:
                    self.pending_chats[(str(chat_id), challenge_id)] = r['message_id']
                    self.pending[r['message_id']] = challenge_id
                    first_result = first_result or r
            except Exception as exc:
                logger.warning('sendPhoto to %s failed: %s', chat_id, exc)
        return first_result

    def forget(self, challenge_id):
        self.pending = {mid: cid for mid, cid in self.pending.items() if cid != challenge_id}
        if hasattr(self, 'pending_chats'):
            self.pending_chats = {k: v for k, v in self.pending_chats.items() if k[1] != challenge_id}

    async def send_message(self, text):
        """Broadcast plain-text message ВСЕМ подписчикам."""
        first = None
        for chat_id in self._chat_targets():
            try:
                r = await self._call('sendMessage', {'chat_id': chat_id, 'text': text})
                first = first or r
            except Exception as exc:
                logger.info('sendMessage to %s failed: %s', chat_id, exc)
        return first

    async def on_message(self, text, chat_id, reply_to_message_id):
        # Broadcast-режим: принимаем сообщения от ЛЮБОГО подписанного chat_id,
        # плюс commands /start /stop для управления подпиской.
        if not isinstance(text, str) or not text.strip():
            return
        text = text.strip()
        cid_s = str(chat_id)
        # Commands /start /stop доступны кому угодно (bot API уже filter'ит по botToken)
        if text.lower() in ('/start', '/start@' + (self.chat_id or '')):
            from app.telegram_subscribers import add as _sub_add
            added = _sub_add(cid_s)
            reply = ('✅ Подписка активна! Вы будете получать уведомления и капчи.'
                     if added else 'ℹ️ Вы уже подписаны.')
            try:
                await self._call('sendMessage', {'chat_id': cid_s, 'text': reply})
            except Exception:
                pass
            return
        if text.lower() == '/stop':
            from app.telegram_subscribers import remove as _sub_remove
            removed = _sub_remove(cid_s)
            reply = '👋 Отписка. Сообщения больше не будут приходить.' if removed else 'ℹ️ Вы и так не подписаны (или админ — админа удалить нельзя).'
            try:
                await self._call('sendMessage', {'chat_id': cid_s, 'text': reply})
            except Exception:
                pass
            return
        # Проверяем что chat_id — подписчик или админ.
        try:
            from app.telegram_subscribers import is_known
            if not is_known(cid_s):
                return  # неизвестный юзер — игнор
        except Exception:
            if cid_s != self.chat_id:
                return
        # Reply to captcha challenge — только явный reply_to (без single-pending
        # fallback, чтобы обычные сообщения между challenges не резолвили captcha).
        challenge_id = self.pending.get(reply_to_message_id)
        if challenge_id and self.resolver:
            await self.resolver(challenge_id, text)

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
