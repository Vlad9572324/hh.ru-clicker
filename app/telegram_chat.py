"""Read and answer HH chats from Telegram.

HR alerts carry two buttons: "cv:<account>:<chat>" shows the recent messages,
"cr:<account>:<chat>" asks for a reply (force_reply) that the bot then sends to
HH on behalf of that account. The HH link in alerts often fails to open in the
mobile app, so this keeps the whole conversation in Telegram.
"""
import asyncio
import json
import time
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from app.logging_utils import log_debug

_MSK = ZoneInfo("Europe/Moscow")
_REPLY_TTL = 3600


def find_state(ref):
    from app.instances import bot as manager
    for state in list(manager.account_states) + list(manager.temp_states.values()):
        if getattr(state, "_deleted", False):
            continue
        if ref in (str(state.acc.get("user_id") or ""), str(state.acc.get("resume_hash") or "")):
            return state
    return None


def _when(raw):
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(_MSK).strftime("%d.%m %H:%M")
    except (ValueError, TypeError):
        return ""


def format_history(messages) -> str:
    lines = []
    for m in messages[-12:]:
        who = "🙋 Вы" if m.get("sender") == "applicant" else ("🤖 Бот HH" if m.get("is_bot") else "👤 HR")
        text = escape((m.get("text") or "").strip())[:700] or "<i>(без текста)</i>"
        lines.append(f"<b>{who}</b> <i>{_when(m.get('timestamp'))}</i>\n{text}")
    return "\n\n".join(lines)


class TelegramChatBridge:
    def __init__(self, bot):
        self.bot = bot
        self.replies = {}  # (chat_id, prompt message_id) -> (account ref, neg_id, created)

    def _buttons(self, ref, neg_id):
        return json.dumps({"inline_keyboard": [[
            {"text": "✍ Ответить HR", "callback_data": f"cr:{ref}:{neg_id}"},
            {"text": "🔄 Обновить", "callback_data": f"cv:{ref}:{neg_id}"},
            {"text": "🔗 HH", "url": f"https://hh.ru/chat/{neg_id}"}]]}, ensure_ascii=False)

    async def show(self, chat_id, ref, neg_id):
        state = find_state(ref)
        if state is None:
            return await self.bot._call("sendMessage", {"chat_id": str(chat_id), "text": "Аккаунт не найден."})
        from app.hh_client_factory import get_client
        try:
            history = await asyncio.to_thread(get_client(state.acc).fetch_chat_history, neg_id, 12)
        except Exception as exc:
            log_debug(f"tg chat view {neg_id}: {type(exc).__name__}")
            history = []
        text = format_history(history) if history else "<i>Не удалось загрузить переписку или она пуста.</i>"
        header = f"💬 <b>Переписка</b> · {escape(state.short)}\n\n"
        await self.bot._call("sendMessage", {"chat_id": str(chat_id), "text": (header + text)[:4000],
                                             "parse_mode": "HTML", "reply_markup": self._buttons(ref, neg_id)})

    async def ask_reply(self, chat_id, ref, neg_id):
        state = find_state(ref)
        if state is None:
            return await self.bot._call("sendMessage", {"chat_id": str(chat_id), "text": "Аккаунт не найден."})
        prompt = await self.bot._call("sendMessage", {
            "chat_id": str(chat_id),
            "text": f"✍ Напишите ответ HR ответом («Ответить») на это сообщение — "
                    f"он уйдёт в HH от имени {state.short}.",
            "reply_markup": json.dumps({"force_reply": True, "input_field_placeholder": "Ответ HR"})})
        if prompt:
            self._prune()
            self.replies[(str(chat_id), prompt["message_id"])] = (ref, str(neg_id), time.monotonic())

    def _prune(self):
        now = time.monotonic()
        self.replies = {k: v for k, v in self.replies.items() if now - v[2] < _REPLY_TTL}

    async def answer(self, chat_id, reply_to_message_id, text) -> bool:
        """True if this message was a reply to one of our prompts (handled here)."""
        self._prune()
        key = (str(chat_id), reply_to_message_id)
        if key not in self.replies:
            return False
        ref, neg_id, _ = self.replies.pop(key)  # one prompt = one message, never replayed
        state = find_state(ref)
        if state is None:
            await self.bot._call("sendMessage", {"chat_id": str(chat_id), "text": "Аккаунт не найден — не отправлено."})
            return True
        from app.hh_client_factory import get_client
        # A human's explicit answer is not blocked by the bot's own pauses.
        acc = {**state.acc, "_mutation_guard": lambda: not state._deleted}
        try:
            result = await asyncio.to_thread(get_client(acc).send_message, neg_id, text.strip())
        except Exception as exc:
            log_debug(f"tg chat reply {neg_id}: {type(exc).__name__}")
            result = "unknown"
        reply = ("✅ Отправлено в HH." if result is True else
                 "⚠️ Результат неизвестен — проверьте чат перед повтором." if result == "unknown" else
                 "❌ Чат закрыт для сообщений." if result == "chat_not_found" else
                 "❌ HH не принял сообщение.")
        await self.bot._call("sendMessage", {"chat_id": str(chat_id), "text": reply,
                                             "reply_markup": self._buttons(ref, neg_id)})
        return True
