"""
Парсер событий push-канала websocket.hh.ru.

Формат кадра (text, JSON), реверс APK + подтверждено live:
    {"type": <eventType>,
     "data": {"eventType": str, "time": datetime-str,
              "fromCurrentDevice": bool, "eventData": {...}}}

Канал строго read-only: в APK единственный держатель WebSocket реализует
только close(1000), subscribe-фреймов нет — сервер сам шлёт всё по
пользователю, мутации только через REST.

Модуль чисто парсит кадры в WsEvent, без побочных эффектов (без логирования,
файлов и сети). Неизвестные eventType НЕ дропаются — парсер возвращает
WsEvent с любым type, а решение о фильтрации принимает ws_manager.

Список известных event types — реестр converters из APK
(apidocs_group_8.yaml, секция WEBSOCKET).
"""

import json
from dataclasses import dataclass

# Известные event types: wire-имя → русское описание.
# Не используется для фильтрации — только как справочник для логов/UI.
KNOWN_EVENT_TYPES: dict[str, str] = {
    "chat_message_create": "Новое сообщение в чате (ответ работодателя)",
    "chat_message_edited": "Сообщение в чате отредактировано",
    "chat_message_deleted": "Сообщение в чате удалено",
    "chat_state_changed": "Изменилось состояние чата (RELOAD_CHAT)",
    "last_viewed_message_change": "Работодатель просмотрел сообщения (MESSAGE_VIEWED)",
    "chat_participant_action": "Действие участника чата (typing и т.п.)",
    "unread_chats_count_change": "Изменился счётчик непрочитанных чатов",
    "bell_notification_created_event": "Создано bell-уведомление",
    "bell_notification_deleted_event": "Удалено bell-уведомление",
    "bell_notification_read_event": "Прочитано bell-уведомление",
    "electronic_work_book_card_status": "Изменился статус карточки электронной трудовой книжки",
    "user_activity_score_change": "Изменился счётчик активности пользователя",
}

# Чат-события вне префикса chat_* (сам префикс ловится в is_chat_event).
_CHAT_EXTRA_TYPES = frozenset({"last_viewed_message_change"})

# Ключи chat id в eventData, в порядке приоритета. Значения — только строки:
# числовые id (легаси/ошибки сериализации) намеренно игнорируем.
_CHAT_ID_KEYS = ("chatId", "chat_id", "id")


@dataclass
class WsEvent:
    """Нормализованное событие push-канала HH."""

    type: str                    # data["eventType"], fallback envelope["type"], иначе ""
    chat_id: str | None          # из eventData: "chatId"/"chat_id"/"id" (только строки)
    timestamp: str | None        # data["time"] (может отсутствовать)
    from_current_device: bool    # data["fromCurrentDevice"], дефолт False
    event_data: dict             # data["eventData"], дефолт {}
    raw: dict                    # весь кадр целиком


def _first_str(d: dict, keys: tuple[str, ...]) -> str | None:
    """Первое непустое строковое значение по списку ключей, иначе None."""
    for key in keys:
        value = d.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def parse_event(raw: str | dict) -> WsEvent | None:
    """Разобрать кадр push-канала в WsEvent.

    raw — JSON-строка (допустимы и bytes — некоторые WS-клиенты отдают
    кадры как bytes) или уже распарсенный dict. Возвращает None для
    невалидного/пустого каркаса: не-JSON строка, не-dict кадр, либо кадр
    без типа и без непустого "data". Неизвестный eventType не дропается —
    возвращается WsEvent с этим type. Кадр без "data" допустим: type
    берётся из envelope, остальные поля по дефолтам.

    Функция без побочных эффектов: не логирует и ничего не пишет.
    """
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = bytes(raw).decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(raw, str):
        try:
            frame = json.loads(raw)
        except ValueError:  # JSONDecodeError — подкласс ValueError
            return None
    elif isinstance(raw, dict):
        frame = raw
    else:
        return None

    if not isinstance(frame, dict):
        # JSON-скаляр/массив вместо объекта — не кадр событий.
        return None

    data = frame.get("data")
    if not isinstance(data, dict):
        # Кадры без "data" (или с мусором) допустимы — поля по дефолтам.
        data = {}

    # type: data["eventType"] → envelope["type"] → "".
    event_type = data.get("eventType")
    if not isinstance(event_type, str) or not event_type:
        envelope_type = frame.get("type")
        event_type = envelope_type if isinstance(envelope_type, str) else ""

    event_data = data.get("eventData")
    if not isinstance(event_data, dict):
        event_data = {}

    if not event_type and not data:
        # Пустой каркас: ни типа, ни data — идентифицировать нечего.
        return None

    timestamp = data.get("time")
    if not isinstance(timestamp, str) or not timestamp:
        timestamp = None

    return WsEvent(
        type=event_type,
        chat_id=_first_str(event_data, _CHAT_ID_KEYS),
        timestamp=timestamp,
        from_current_device=bool(data.get("fromCurrentDevice", False)),
        event_data=event_data,
        raw=frame,
    )


def is_chat_event(event: WsEvent) -> bool:
    """True, если событие относится к чатам.

    Чат-события: все типы с префиксом chat_* (включая chat_participant_action)
    плюс last_viewed_message_change (просмотр сообщений работодателем).
    """
    return event.type.startswith("chat_") or event.type in _CHAT_EXTRA_TYPES
