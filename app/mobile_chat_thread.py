"""Чтение треда/истории одного чата через mobile API api.hh.ru (Phase 2).

Mobile-аналоги web-функций `fetch_negotiation_thread` и
`_fetch_chat_history` из app/hh_chat.py: обе ходят в
`GET https://api.hh.ru/chats/{chat_id}` (OAuth Bearer, заголовки APK)
через общий транспорт app.hh_mobile_transport.mobile_request.

Контракт ручки (scratchpad/apidocs/apidocs_group_1.yaml, GET /chats/{chat_id}):
- query: limit (ОБЯЗАТЕЛЕН — без query-параметров 400 bad_request),
  order=next|prev, start_message_id (инклюзивно);
- ответ-конверт: {chat, participants, resources, chat_states};
  сообщения в chat.messages.items[] (без start_message_id — последние
  limit штук, по возрастанию id = oldest first);
- текст сообщения в body.text.content (верхнеуровневого text НЕТ);
- автор в participant_id вида '<id>-BOT' | '<id>-EMPLOYER_USER' |
  '<id>-APPLICANT_USER'; статус переговоров в workflow_transition +
  resources.negotiations; гейт «можно ли писать» —
  chat_states.write_message_state.allowed.

Маппинг полей mobile -> web-совместимый результат:
- chat.display.subtitle        -> employer_name;
- chat.display.title           -> vacancy_title;
- chat.resources.negotiations[0] -> topic_id;
- chat.unread_count + автор последнего сообщения -> needs_reply;
- participant_id оканчивается на -APPLICANT_USER -> sender "applicant",
  иначе -> "employer".

Политика ошибок: fallback-статусы (0/401/403/5xx, см.
is_fallback_status) НЕ глотаются — MobileAPIError поднимается выше, где
fallback-логика решает, повторять ли запрос через web-flow (chatik.hh.ru).
Прочие HTTP-ошибки (400, 404, ...) — fetch_thread возвращает dict
с заполненным error, fetch_chat_history — пустой список.
"""

from app.hh_mobile_transport import (
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug

_APPLICANT_SUFFIX = "-APPLICANT_USER"
_BOT_SUFFIX = "-BOT"


def _message_text(msg: dict) -> str:
    """Текст сообщения из body.text.content (НЕ верхнеуровневый text)."""
    if not isinstance(msg, dict):
        return ""
    body = msg.get("body")
    if not isinstance(body, dict):
        return ""
    text_obj = body.get("text")
    if not isinstance(text_obj, dict):
        return ""
    return str(text_obj.get("content") or "").strip()


def _sender_of(msg: dict) -> str:
    """Отправитель по participant_id: суффикс -APPLICANT_USER -> "applicant",
    всё остальное (-EMPLOYER_USER, -BOT, ...) -> "employer"."""
    pid = str(msg.get("participant_id") or "")
    return "applicant" if pid.endswith(_APPLICANT_SUFFIX) else "employer"


def _is_bot(msg: dict) -> bool:
    """Бот ли автор: participant_display.is_bot либо суффикс -BOT."""
    pd = msg.get("participant_display")
    if isinstance(pd, dict) and pd.get("is_bot"):
        return True
    return str(msg.get("participant_id") or "").endswith(_BOT_SUFFIX)


def _parse_simple_message(msg: dict) -> dict | None:
    """Нормализовать сообщение из chat.messages.items.

    Возвращает {sender, text, msg_id, is_bot, actions} для SIMPLE-сообщений
    с непустым body.text.content; workflow-события без текста и не-SIMPLE
    типы — None (пропускаются).
    """
    if not isinstance(msg, dict) or msg.get("type") != "SIMPLE":
        return None
    text = _message_text(msg)
    if not text:
        return None
    body = msg.get("body") or {}
    return {
        "sender": _sender_of(msg),
        "text": text,
        "msg_id": str(msg.get("id", "")),
        "is_bot": _is_bot(msg),
        "actions": body.get("actions") or {},
    }


def _empty_thread_result(neg_id: str) -> dict:
    """Каркас результата, совместимый по ключам с web
    fetch_negotiation_thread (app/hh_chat.py)."""
    return {"neg_id": neg_id, "employer_name": "Работодатель", "vacancy_title": "",
            "messages": [], "needs_reply": False, "last_msg_id": "", "last_employer_msg": "",
            "topic_id": "", "error": ""}


def fetch_thread(acc: dict, neg_id: str, limit: int = 50) -> dict:
    """Прочитать тред переговоров через mobile API `GET /chats/{neg_id}`.

    Возвращает dict, совместимый по ключам с web fetch_negotiation_thread:
    {neg_id, employer_name, vacancy_title, messages, needs_reply,
     last_msg_id, last_employer_msg, topic_id, error}, где messages —
    список {sender, text, msg_id, is_bot} (SIMPLE-сообщения с текстом,
    oldest first).

    needs_reply: unread_count > 0 И последнее сообщение от employer
    (не от applicant) И это не workflow-событие без текста.

    На fallback-статусах (401/403/5xx/сеть) кидает MobileAPIError —
    fallback на web-flow решается выше; на прочих HTTP-ошибках
    (400/404/...) возвращает dict с заполненным error.
    """
    result = _empty_thread_result(neg_id)
    try:
        data = mobile_request(acc, "GET", f"/chats/{neg_id}",
                              params={"limit": limit, "order": "next"})
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            raise  # 401/403/5xx/сеть — fallback на web-flow выше по стеку
        result["error"] = f"HTTP {e.status_code}"
        log_debug(f"mobile fetch_thread {neg_id}: HTTP {e.status_code} — {e.payload}")
        return result

    chat = (data or {}).get("chat") if isinstance(data, dict) else None
    if not isinstance(chat, dict):
        result["error"] = "чат не найден"
        log_debug(f"mobile fetch_thread {neg_id}: нет chat в ответе")
        return result

    # employer_name / vacancy_title — из display (если есть)
    display = chat.get("display")
    if isinstance(display, dict):
        subtitle = str(display.get("subtitle") or "").strip(" ,")
        if subtitle:
            result["employer_name"] = subtitle
        title = str(display.get("title") or "").strip()
        if title:
            result["vacancy_title"] = title

    # topic_id — первый id из chat.resources.negotiations (если есть)
    resources = chat.get("resources") or {}
    neg_topics = resources.get("negotiations") or []
    if neg_topics:
        result["topic_id"] = str(neg_topics[0])

    items = (chat.get("messages") or {}).get("items") or []

    messages = []
    last_employer_msg = ""
    for msg in items:
        parsed = _parse_simple_message(msg)
        if parsed is None:
            continue  # workflow-события без текста / не-SIMPLE пропускаем
        messages.append({
            "sender": parsed["sender"],
            "text": parsed["text"],
            "msg_id": parsed["msg_id"],
            "is_bot": parsed["is_bot"],
        })
        if parsed["sender"] == "employer":
            last_employer_msg = parsed["text"]
    result["messages"] = messages
    result["last_employer_msg"] = last_employer_msg

    # last_msg_id / needs_reply — по последнему сообщению (любого типа)
    last = items[-1] if items and isinstance(items[-1], dict) else None
    if last is not None:
        result["last_msg_id"] = str(last.get("id", ""))
        unread = chat.get("unread_count") or 0
        from_applicant = _sender_of(last) == "applicant"
        # workflow-событие без текста (смена статуса) — отвечать не на что
        is_workflow_event = bool(last.get("workflow_transition")) and not _message_text(last)
        result["needs_reply"] = bool(
            unread > 0 and not from_applicant and not is_workflow_event)

    return result


def fetch_chat_history(acc: dict, chat_id: str, max_messages: int = 20) -> list:
    """История сообщений чата через mobile API `GET /chats/{chat_id}`.

    Возвращает список dict'ов {sender, text, msg_id, actions, is_bot} —
    oldest first, только SIMPLE-сообщения с текстом, последние
    max_messages штук. actions — body.actions (кнопки бота) или {}.

    На не-fallback HTTP-ошибках (400/404/...) возвращает []; на
    fallback-статусах (401/403/5xx/сеть) кидает MobileAPIError —
    fallback на web-flow решается выше.
    """
    try:
        data = mobile_request(acc, "GET", f"/chats/{chat_id}",
                              params={"limit": max_messages, "order": "next"})
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            raise  # 401/403/5xx/сеть — fallback на web-flow выше по стеку
        log_debug(f"mobile fetch_chat_history {chat_id}: HTTP {e.status_code}")
        return []

    chat = (data or {}).get("chat") if isinstance(data, dict) else None
    if not isinstance(chat, dict):
        log_debug(f"mobile fetch_chat_history {chat_id}: нет chat в ответе")
        return []
    items = (chat.get("messages") or {}).get("items") or []

    conversation = []
    for msg in items:
        parsed = _parse_simple_message(msg)
        if parsed is None:
            continue
        conversation.append({
            "sender": parsed["sender"],
            "text": parsed["text"],
            "msg_id": parsed["msg_id"],
            "actions": parsed["actions"],
            "is_bot": parsed["is_bot"],
        })
    # Последние max_messages записей (самый свежий контекст)
    return conversation[-max_messages:]
