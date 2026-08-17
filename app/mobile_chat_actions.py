"""Mobile-версии «действий в чате» hh.ru через api.hh.ru (OAuth Bearer).

Phase 2, три операции с точными контрактами из APK
(scratchpad/apk_writes/apk_writes_group_1.yaml, Retrofit-интерфейс
ru.hh.android/26.28.1 ChatApi = SM/b.java):

- quick replies:  PUT /chats/{chat_id}/suggestions/quick_replies?message_id=
                  БЕЗ тела; ответ 200 = {"quick_replies": [{id, type, text,
                  label, metadata}], "show_limit": bool?};
- mark read:      PUT /chats/{chat_id}/messages/last_viewed_id,
                  FormUrlEncoded поле message_id (long); ответ 200 пустой;
- typing:         PUT /chats/{chat_id}/participants/action,
                  body {"action_type": "typing"|"none"}; ответ 200 пустой.

ВАЖНО: в apidocs у quick_replies и participants/action указан POST, но
APK-контракт (реальный Retrofit-интерфейс приложения — источник истины
для writes) — PUT. Здесь используется PUT.

HTTP идёт через app.hh_mobile_transport.mobile_request, который сам
подставляет Bearer-токен / UA / x-force-app-access и кидает
MobileAPIError(status_code) на не-2xx (0 = сетевая ошибка).

Поведение на ошибках (как у остальных mobile-модулей): fallback-статусы
(0 сеть, 401, 403, 5xx — см. is_fallback_status) перекидываются наверх —
фабрика клиентов повторит запрос через web-flow; нефоллбек-статусы
(404/405/409/422...) тихо деградируют до пустого результата, не ломая
flow.
"""

from app.hh_mobile_transport import (
    MOBILE_BASE,
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug


def fetch_quick_replies(acc: dict, chat_id: str, message_id: str) -> list:
    """`PUT /chats/{chat_id}/suggestions/quick_replies?message_id=` — готовые
    варианты ответов HH на сообщение HR (доменная модель с контекстом
    переписки), аналог web-версии hh_chat.fetch_quick_replies.

    Контракт APK: PUT без тела, message_id — nullable query-параметр.
    Ответ: {"quick_replies": [{id, type, text, label, metadata}], show_limit?}.
    Возвращает список строк: для каждого элемента берётся непустое из
    `text` / `label`. Пустой ответ или нет ключа → [].
    Не-2xx: fallback-статусы перекидываются (MobileAPIError), остальные → [].
    """
    url = f"{MOBILE_BASE}/chats/{chat_id}/suggestions/quick_replies"
    try:
        data = mobile_request(acc, "PUT", url, params={"message_id": message_id})
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            raise
        log_debug(f"mobile fetch_quick_replies chat={chat_id} msg={message_id}: HTTP {e.status_code}")
        return []
    if not isinstance(data, dict):
        return []
    replies = data.get("quick_replies")
    if not isinstance(replies, list):
        return []
    out: list = []
    for item in replies:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("label") or "").strip()
        if text:
            out.append(text)
    return out


def mark_chat_read(acc: dict, chat_id: str, message_id: str) -> bool:
    """`PUT /chats/{chat_id}/messages/last_viewed_id` — write-маркер
    «прочитано до…» (read-receipt), аналог web-версии hh_chat.mark_chat_read.
    HR видит галочку — часто триггер для follow-up с их стороны.

    Контракт APK: FormUrlEncoded поле message_id (long), ответ 200 пустой.
    Защита от hash-fallback: нечисловой message_id (hash из
    _build_thread_from_chat_item для сообщений без реального id) HH не
    примет (400/422), поэтому запрос не отправляется вообще.
    2xx → True. Не-2xx: fallback-статусы перекидываются, остальные → False.
    """
    if not str(message_id).isdigit():
        log_debug(f"mobile mark_chat_read chat={chat_id}: нечисловой message_id {message_id!r} — пропуск")
        return False
    url = f"{MOBILE_BASE}/chats/{chat_id}/messages/last_viewed_id"
    try:
        mobile_request(acc, "PUT", url, form={"message_id": str(message_id)})
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            raise
        log_debug(f"mobile mark_chat_read chat={chat_id} msg={message_id}: HTTP {e.status_code}")
        return False
    return True


def send_participant_action(acc: dict, chat_id: str, action_type: str = "TYPING") -> bool:
    """`PUT /chats/{chat_id}/participants/action` — эмуляция typing indicator,
    аналог web-версии hh_chat.send_participant_action.

    Контракт APK: JSON-тело {"action_type": <string>}, enum
    ChatParticipantAction = "typing" | "none": `TYPING` показывает HR что мы
    печатаем, `NONE` снимает. Приходит action_type в верхнем регистре
    (web-конвенция) — нормализуем к нижнему.
    2xx → True. Не-2xx: fallback-статусы перекидываются, остальные → False.
    """
    normalized = str(action_type).lower()
    url = f"{MOBILE_BASE}/chats/{chat_id}/participants/action"
    try:
        mobile_request(acc, "PUT", url, json_body={"action_type": normalized})
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            raise
        log_debug(f"mobile send_participant_action chat={chat_id} action={normalized}: HTTP {e.status_code}")
        return False
    return True


def send_event(acc: dict, chat_id: str, event_type: str, event_params: dict | None = None) -> bool:
    """Отправить workflow-событие кнопки робота-рекрутера.

    APK-контракт: ``POST /chats/{chat_id}/event`` с JSON-телом
    ``{event_type, event_params}``.  Авторизация и mobile-заголовки
    добавляются общим transport-слоем.
    """
    normalized_type = str(event_type or "").strip()
    if not normalized_type:
        return False
    params = event_params if isinstance(event_params, dict) else {}
    url = f"{MOBILE_BASE}/chats/{chat_id}/event"
    try:
        mobile_request(
            acc,
            "POST",
            url,
            json_body={"event_type": normalized_type, "event_params": params},
        )
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            raise
        log_debug(f"mobile send_event chat={chat_id} event={normalized_type}: HTTP {e.status_code}")
        return False
    return True
