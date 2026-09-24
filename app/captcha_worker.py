"""Watch persisted HH challenges, deliver images to Telegram, and resume after human success."""
import asyncio
import logging
from urllib.parse import parse_qs, urlsplit

from app import captcha
from app.config import CONFIG
from app.captcha_llm import recognize_captcha
from app.captcha_solver import fetch_captcha_image, submit_captcha
from app.telegram_bot import TelegramCaptchaBot

logger = logging.getLogger(__name__)


class CaptchaCoordinator:
    def __init__(self, bot_manager, bot):
        self.manager = bot_manager
        self.bot = bot
        self.pending = {}
        bot_manager.telegram_captcha_coordinator = self
        self._seen = set()
        self._lock = asyncio.Lock()
        bot.resolver = self.resolve

    def account(self, key):
        for state in list(self.manager.account_states) + list(self.manager.temp_states.values()):
            if key in (str(state.acc.get('user_id', '')), str(state.acc.get('resume_hash', ''))):
                return state.acc
        return None

    async def scan(self):
        async with self._lock:
            with captcha.LOCK:
                records = captcha._read()
            active = {record.get('id') for record in records.values()}
            self._seen.intersection_update(active)
            for cid in list(self.pending):
                if cid not in active:
                    self.pending.pop(cid, None)
                    self.bot.forget(cid)
            for key, record in records.items():
                cid = record.get('id')
                acc = self.account(key)
                if cid in self.pending and acc is not None and not self.pending[cid]['captcha_key']:
                    try:
                        await self.photo(cid, self.pending[cid], acc)
                        self._seen.add(cid)
                    except Exception:
                        logger.warning('HH captcha refresh failed; will retry')
                    continue
                if not cid or cid in self._seen or acc is None:
                    continue
                query = parse_qs(urlsplit(captcha.browser_url(record)).query)
                if not query.get('state'):
                    await self.bot.send_message('Капчу HH нужно решить вручную: ' + captcha.browser_url(record))
                    self._seen.add(cid)
                    continue
                item = dict(acc_key=key, captcha_state=query['state'][0],
                            backurl='https://hh.ru/', failurl=query.get('failurl', ['https://hh.ru/'])[0],
                            url=captcha.browser_url(record), fails=0,
                            captcha_key=None, session=None,
                            challenge_url=record.get('captcha_url', ''))
                self.pending[cid] = item
                try:
                    await self.photo(cid, item, acc)
                except Exception:
                    logger.warning('HH captcha delivery failed; will retry')
                    continue
                self._seen.add(cid)

    async def photo(self, cid, item, acc):
        self._close_session(item.get('session'))
        item['captcha_key'] = None
        item['session'] = None
        session, key, image, state, backurl = await asyncio.to_thread(
            fetch_captcha_image, acc, item['challenge_url'])
        item['captcha_state'] = state or item['captcha_state']
        item['backurl'] = backurl or item['backurl']
        if CONFIG.captcha_llm_enabled and item.get('llm_attempted') is not True:
            item['llm_attempted'] = True
            try:
                answer = await asyncio.to_thread(recognize_captcha, image)
            except Exception:
                answer = None
            if answer:
                try:
                    ok, _ = await asyncio.to_thread(
                        submit_captcha, session, answer, key, item['captcha_state'],
                        item['backurl'], item['failurl'])
                except Exception:
                    ok = False
                if ok:
                    captcha.clear(acc, cid)
                    CONFIG.captcha_llm_solved += 1
                    self.pending.pop(cid, None)
                    self.bot.forget(cid)
                    gui = getattr(self, 'gui_pending', None)
                    if gui and cid in gui:
                        self._close_session(gui.pop(cid).get('session'))
                    self._close_session(session)
                    try:
                        await asyncio.to_thread(self.manager.resume_challenge_account, item['acc_key'])
                    except Exception:
                        pass
                    self._log(acc, '🤖 Капча решена LLM — отклики возобновлены', 'success')
                    if getattr(self.bot, 'connected', False) is True:
                        try:
                            await self.bot.send_message('🤖 Капча решена автоматически (LLM)')
                        except Exception:
                            pass
                    return
                self._log(acc, '🤖 LLM: ответ отклонён HH → передаю юзеру', 'info')
                self._close_session(session)
                # Rejected submissions can invalidate the old image/key.
                session, key, image, state, backurl = await asyncio.to_thread(
                    fetch_captcha_image, acc, item['challenge_url'])
                item['captcha_state'] = state or item['captcha_state']
                item['backurl'] = backurl or item['backurl']
        try:
            result = await self.bot.push_challenge(cid, acc.get('short') or acc.get('name') or 'HH', image)
        except Exception:
            self._close_session(session)
            raise
        if not result:
            self._close_session(session)
            raise RuntimeError('TG bot disabled')
        if not item.get('forwarded'):
            CONFIG.captcha_llm_forwarded += 1
            item['forwarded'] = True
        item['captcha_key'] = key
        item['session'] = session
        try:
            self.manager._add_log(acc.get('short', ''), acc.get('color', 'yellow'),
                                  '📱 Капча отправлена в Telegram — жду ответа', 'info')
        except Exception:
            pass

    @staticmethod
    def _close_session(session):
        try:
            session.close()
        except Exception:
            pass

    def _log(self, acc, message, level):
        try:
            self.manager._add_log(acc.get('short', ''), acc.get('color', 'yellow'), message, level)
        except Exception:
            pass

    async def resolve(self, cid, text):
        async with self._lock:
            item = self.pending.get(cid)
            if item is None:
                return
            acc = self.account(item['acc_key'])
            if acc is None or captcha.current(acc).get('id') != cid:
                self.pending.pop(cid, None)
                self.bot.forget(cid)
                return
            if not item['captcha_key']:
                await self.photo(cid, item, acc)
                return
            if item.get('session') is None:
                # session потерялась (например worker перезапустился) — грузим свежую.
                await self.photo(cid, item, acc)
                return
            ok, reason = await asyncio.to_thread(
                submit_captcha, item['session'], text, item['captcha_key'], item['captcha_state'],
                item['backurl'], item['failurl'])
            if ok:
                # HH подтвердил через 302 на backurl → снимаем challenge и
                # будим worker'а. GUI-panel скроется через syncAccountCard.
                captcha.clear(acc, cid)
                try:
                    await asyncio.to_thread(self.manager.resume_challenge_account, item['acc_key'])
                except Exception:
                    pass
                self.pending.pop(cid, None)
                # Чистим и GUI-сессию если была параллельно открыта — картинка/session там stale.
                gui = getattr(self, 'gui_pending', None)
                if gui and cid in gui:
                    try:
                        s = gui[cid].get('session')
                        if s is not None:
                            s.close()
                    except Exception:
                        pass
                    gui.pop(cid, None)
                self.bot.forget(cid)
                try:
                    self.manager._add_log(acc.get('short', ''), acc.get('color', 'yellow'),
                                          '✅ Капча пройдена (Telegram) — отклики возобновлены', 'success')
                except Exception:
                    pass
                await self.bot.send_message('✅ Капча HH решена, отклики возобновлены')
                return
            item['fails'] += 1
            try:
                self.manager._add_log(acc.get('short', ''), acc.get('color', 'yellow'),
                                      f'❌ Капча не принята HH (попытка {item["fails"]}/3, reason={reason})', 'warning')
            except Exception:
                pass
            # Сообщение в TG что ответ отклонён — иначе юзер видит только
            # новую картинку (editMessageMedia) без объяснения почему.
            try:
                await self.bot.send_message(
                    f'❌ Ответ неверный (попытка {item["fails"]}/3). '
                    f'HH прислал новую капчу — введите ответ ниже.'
                )
            except Exception:
                pass
            if reason == 'recaptcha' or item['fails'] >= 3:
                logger.warning('HH captcha requires manual resolution')
                self.pending.pop(cid, None)
                self.bot.forget(cid)
                try:
                    self.manager._add_log(acc.get('short', ''), acc.get('color', 'yellow'),
                                          '⚠ Капча усложнилась (reCAPTCHA/3 попытки) — решите вручную по ссылке', 'error')
                except Exception:
                    pass
                await self.bot.send_message('капча HH усложнилась (возможно reCAPTCHA), решите вручную по ссылке: ' + item['url'])
                return
            await self.photo(cid, item, acc)


async def captcha_orchestrator(bot_manager):
    """Reconfigure polling on settings changes; cancel and close HTTP on shutdown."""
    bot = None
    signature = None
    try:
        while True:
            current = (CONFIG.telegram_bot_token, CONFIG.telegram_chat_id, CONFIG.telegram_captcha_enabled)
            if current != signature:
                if bot:
                    await bot.stop()
                bot = TelegramCaptchaBot()
                bot_manager.telegram_captcha_bot = bot
                coordinator = CaptchaCoordinator(bot_manager, bot)
                signature = current
                if current[2]:
                    await bot.start()
            if CONFIG.captcha_llm_enabled or (current[2] and bot._task):
                try:
                    await coordinator.scan()
                except Exception:
                    logger.warning('HH captcha scan failed; will retry')
            await asyncio.sleep(3)
    finally:
        if bot:
            await bot.stop()
        bot_manager.telegram_captcha_bot = None
        bot_manager.telegram_captcha_coordinator = None
