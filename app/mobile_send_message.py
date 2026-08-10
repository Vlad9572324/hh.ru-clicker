"""Mobile-версия отправки сообщения в чат hh.ru (Phase 2).

POST https://api.hh.ru/chats/{chat_id}/messages — единый mobile-контракт
отправки сообщений (APK SendMessageBodyNetwork, см.
scratchpad/apidocs/apidocs_group_1.yaml и apk_writes_group_1.yaml):
тело {"text", "idempotency_key"} + опциональные upload_id/metadata;
idempotency_key = UUID.randomUUID().toString(). Ответ 2xx — {"message": {...}}.

Транспорт — app.hh_mobile_transport.mobile_request (Bearer + mobile UA +
x-force-app-access). Fallback-политика: статусы 0 (сеть) / 401 / 403 / 5xx
НЕ глотаются — MobileAPIError перекидывается наверх, чтобы fallback-обёртка
повторила запрос через web-flow; 404 → "chat_not_found", прочие 4xx → False.
"""

import uuid

from app.hh_mobile_transport import (
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug


def send_message(acc: dict, chat_id: str, text: str,
                 idempotency_key: str = "") -> bool | str:
    """Отправить сообщение в чат через mobile-контракт api.hh.ru.

    acc — словарь аккаунта (токен добывает mobile_request сам).
    Если idempotency_key не задан — генерируется новый UUID4.

    Возвращает True при 2xx, "chat_not_found" при 404, False при прочих 4xx.
    На fallback-статусах (0 сеть / 401 / 403 / 5xx) перекидывает
    MobileAPIError наверх — для повтора через web-flow.
    """
    if not idempotency_key:
        idempotency_key = str(uuid.uuid4())
    body = {"text": text, "idempotency_key": idempotency_key}
    try:
        data = mobile_request(acc, "POST", f"/chats/{chat_id}/messages",
                              json_body=body)
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            # Не глотим: fallback-обёртка повторит отправку через web-flow.
            raise
        if e.status_code == 404:
            log_debug(f"mobile send_message chat={chat_id}: 404 chat_not_found")
            return "chat_not_found"
        log_debug(f"mobile send_message chat={chat_id}: HTTP {e.status_code} | {e.payload}")
        return False
    # 2xx: опционально парсим response["message"] (SentMessageNetwork).
    message = data.get("message") if isinstance(data, dict) else None
    msg_id = message.get("id") if isinstance(message, dict) else None
    log_debug(f"mobile send_message chat={chat_id}: ok, message_id={msg_id}")
    return True
