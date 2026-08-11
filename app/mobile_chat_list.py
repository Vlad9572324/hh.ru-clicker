"""Список чатов через mobile API api.hh.ru (Phase 2).

Mobile-аналог web-функции `_fetch_chat_list` из app/hh_chat.py: ходит в
`GET https://api.hh.ru/chats` (OAuth Bearer, заголовки APK) через общий
транспорт app.hh_mobile_transport и возвращает tuple того же формата —
(items_by_id, display_info, current_participant_id), чтобы вызывающий код
мог взаимозаменять web и mobile реализации.

Политика ошибок: MobileAPIError (не-2xx, сеть) НЕ глотается — поднимается
выше, где fallback-логика по is_fallback_status решает, повторять ли запрос
через web-flow (chatik.hh.ru).

Контракт ручки (scratchpad/apidocs/apidocs_group_1.yaml, GET /chats):
- query: page (0-based), per_page (МАКСИМУМ 20), filter_unread=true,
  id (повторяемый), type — сервер ИГНОРИРУЕТ, фильтрация по типу
  выполняется клиентской стороной по item["type"];
- ответ: {chats: {items[], found, pages, page, per_page, has_next_page},
  participants: map participant_id -> {..., is_current_user}, ...}.
"""

from app.hh_mobile_transport import MobileAPIError, mobile_request
from app.logging_utils import log_debug

_CHATS_PER_PAGE = 20          # серверный максимум: per_page>20 -> 400 bad_argument
_APPLICANT_SUFFIX = "-APPLICANT_USER"


def _extract_current_participant(participants: dict) -> str:
    """Определить participant_id текущего пользователя из top-level
    participants ответа GET /chats.

    Приоритет: участник с is_current_user=True; если такого нет —
    participant_id с суффиксом -APPLICANT_USER; иначе пустая строка.
    """
    applicant_fallback = ""
    for pid, info in (participants or {}).items():
        pid = str(pid)
        if isinstance(info, dict) and info.get("is_current_user") is True:
            return pid
        if not applicant_fallback and pid.endswith(_APPLICANT_SUFFIX):
            applicant_fallback = pid
    return applicant_fallback


def fetch_chat_list(acc: dict, max_pages: int = 5,
                    chat_type: str | None = None,
                    filter_unread: bool = False) -> tuple:
    """Пагинированно получить список чатов аккаунта с api.hh.ru.

    Возвращает (items_by_id, display_info, current_participant_id) —
    формат, совместимый с web `_fetch_chat_list` (app/hh_chat.py):
    - items_by_id: {str(chat_id): item} — мобильный item как есть
      (id, type, subtype, unread_count, messages.last, participants.ids,
      write_possibility, operations, ...);
    - display_info: {str(chat_id): {"title", "subtitle", "icon_url"}} —
      из item["display"];
    - current_participant_id: str — участник с is_current_user=True из
      top-level participants (fallback: id c -APPLICANT_USER, иначе "").

    chat_type (например "NEGOTIATION") передаётся серверу для паритета
    с APK, но сервер его игнорирует — реальная фильтрация клиентская,
    по item["type"]. filter_unread=True добавляет filter_unread=true
    (сервер вернёт только чаты с unread>=1).

    Остановка: has_next_page == False либо пустая страница либо исчерпан
    max_pages. Дедупликация чатов по id.

    MobileAPIError не глотается (fallback-логика выше по стеку); прочие
    (не HTTP) ошибки парсинга — возвращаем пустой tuple.
    """
    items_by_id: dict = {}
    display_info: dict = {}
    current_participant_id: str = ""

    for page_num in range(max(0, max_pages)):
        params: dict = {"page": page_num, "per_page": _CHATS_PER_PAGE}
        if chat_type:
            params["type"] = chat_type
        if filter_unread:
            params["filter_unread"] = "true"

        try:
            data = mobile_request(acc, "GET", "/chats", params=params)
        except MobileAPIError:
            # Не глотаем: 401/403/5xx/сеть — fallback на web-flow выше.
            raise
        except Exception as e:
            # Не-HTTP сбой (например, неожиданный тип данных) — парсить
            # нечего, отдаём пустой результат.
            log_debug(f"mobile fetch_chat_list page={page_num}: error {e}")
            return {}, {}, ""

        if not isinstance(data, dict):
            log_debug(f"mobile fetch_chat_list page={page_num}: empty body")
            break

        chats_obj = data.get("chats") or {}
        items = chats_obj.get("items") or []

        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id", ""))
            if not item_id or item_id in items_by_id:
                continue  # дедуп по id (страницы могут пересекаться)
            if chat_type and item.get("type") != chat_type:
                # Сервер параметр type игнорирует — фильтруем на клиенте.
                continue
            # Mobile API отдаёт snake_case (`unread_count`, `messages.last`,
            # `write_possibility`, `participant_id`), а manager.py + hh_chat.py
            # ждут web-схему camelCase (`unreadCount`, `lastMessage`,
            # `participantId`, `writePossibility`). Без нормализации все чаты
            # попадали в skipped_read → бот молча игнорировал новых HR.
            last_msg_raw = (item.get("messages") or {}).get("last") or {}
            body = (last_msg_raw.get("body") or {})
            text_obj = body.get("text") or {}
            last_msg_camel = {
                "id": last_msg_raw.get("id", ""),
                "participantId": last_msg_raw.get("participant_id", ""),
                "text": text_obj.get("content", "") if isinstance(text_obj, dict) else "",
                "workflowTransition": last_msg_raw.get("workflow_transition") or {},
                "createdAt": last_msg_raw.get("created_at", ""),
                "type": last_msg_raw.get("type", ""),
            }
            item.setdefault("unreadCount", item.get("unread_count", 0))
            item.setdefault("lastMessage", last_msg_camel)
            item.setdefault("writePossibility", item.get("write_possibility") or {})
            items_by_id[item_id] = item
            display = item.get("display") or {}
            icon = display.get("icon") or {}
            display_info[item_id] = {
                "title": display.get("title", ""),
                "subtitle": display.get("subtitle", ""),
                "icon_url": icon.get("url", "") if isinstance(icon, dict) else "",
            }

        if not current_participant_id:
            current_participant_id = _extract_current_participant(
                data.get("participants") or {})

        if not items:
            break  # пустая страница — дальше нет смысла
        if chats_obj.get("has_next_page") is False:
            break  # сервер явно сказал, что страниц больше нет

    log_debug(
        f"mobile fetch_chat_list: {len(items_by_id)} chats"
        + (f" (type={chat_type})" if chat_type else "")
        + (f", current={current_participant_id}" if current_participant_id else "")
    )
    return items_by_id, display_info, current_participant_id
