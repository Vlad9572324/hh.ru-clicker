"""Офлайн unit-тесты парсера событий push-канала websocket.hh.ru (app/ws_events.py).

Проверяют parse_event / WsEvent / is_chat_event против формата кадра из
реверса APK: {"type": <eventType>, "data": {"eventType": str, "time": str,
"fromCurrentDevice": bool, "eventData": {...}}}.

Никакой сети и никакого asyncio — чистый pytest.
"""
import json

from app.ws_events import KNOWN_EVENT_TYPES, WsEvent, is_chat_event, parse_event

# 11 типов из реестра converters APK (apidocs_group_8.yaml, секция WEBSOCKET).
PROTOCOL_EVENT_TYPES = [
    "chat_message_create",
    "chat_message_edited",
    "chat_message_deleted",
    "chat_state_changed",
    "last_viewed_message_change",
    "chat_participant_action",
    "unread_chats_count_change",
    "bell_notification_created_event",
    "bell_notification_deleted_event",
    "bell_notification_read_event",
    "electronic_work_book_card_status",
]


def _frame(event_type="chat_message_create", **data_overrides):
    """Собрать валидный кадр протокола как dict."""
    data = {
        "eventType": event_type,
        "time": "2026-08-10T12:00:00.000+0300",
        "fromCurrentDevice": False,
        "eventData": {"chatId": "negotiations_123"},
    }
    data.update(data_overrides)
    return {"type": event_type, "data": data}


# ── parse_event: валидные кадры ─────────────────────────────────────────────


def test_valid_chat_message_create_full_fields():
    """Полный валидный кадр: все поля WsEvent заполнены корректно."""
    frame = _frame(eventData={"chatId": "c42", "messageId": "m1"})
    event = parse_event(json.dumps(frame))
    assert event is not None
    assert event.type == "chat_message_create"
    assert event.chat_id == "c42"
    assert event.timestamp == "2026-08-10T12:00:00.000+0300"
    assert event.from_current_device is False
    assert event.event_data == {"chatId": "c42", "messageId": "m1"}
    assert event.raw == frame


def test_valid_frame_accepts_dict_input():
    """parse_event принимает и уже распарсенный dict, не только строку."""
    frame = _frame(eventType="chat_message_edited",
                   eventData={"chatId": "c7"},
                   fromCurrentDevice=True)
    frame["type"] = "chat_message_edited"
    event = parse_event(frame)
    assert event is not None
    assert event.type == "chat_message_edited"
    assert event.chat_id == "c7"
    assert event.from_current_device is True


def test_valid_frame_accepts_bytes_input():
    """WS-клиент может отдать кадр как bytes — парсер должен их декодировать."""
    frame = _frame()
    event = parse_event(json.dumps(frame).encode("utf-8"))
    assert event is not None
    assert event.type == "chat_message_create"
    # невалидный utf-8 — не кадр
    assert parse_event(b"\xff\xfe{") is None


def test_unknown_event_type_not_dropped():
    """Неизвестный eventType возвращается как есть — фильтрация за менеджером."""
    event = parse_event(_frame(eventType="some_future_event_type"))
    assert event is not None
    assert event.type == "some_future_event_type"


def test_eventtype_from_data_takes_priority_over_envelope():
    """data.eventType главнее envelope.type."""
    frame = {"type": "stale_envelope", "data": {"eventType": "real_type"}}
    event = parse_event(frame)
    assert event is not None
    assert event.type == "real_type"


def test_fallback_type_from_envelope_when_eventtype_missing():
    """Нет eventType в data — type берётся из envelope."""
    frame = {"type": "chat_state_changed", "data": {"eventData": {"chatId": "c1"}}}
    event = parse_event(frame)
    assert event is not None
    assert event.type == "chat_state_changed"
    assert event.chat_id == "c1"


def test_frame_without_data_defaults():
    """Кадр только с envelope.type допустим: остальные поля по дефолтам."""
    event = parse_event('{"type": "unread_chats_count_change"}')
    assert event is not None
    assert event.type == "unread_chats_count_change"
    assert event.chat_id is None
    assert event.timestamp is None
    assert event.from_current_device is False
    assert event.event_data == {}
    assert event.raw == {"type": "unread_chats_count_change"}


def test_from_current_device_true():
    """fromCurrentDevice=true пробрасывается в from_current_device."""
    event = parse_event(_frame(fromCurrentDevice=True))
    assert event is not None
    assert event.from_current_device is True


# ── parse_event: мусор и деградации ─────────────────────────────────────────


def test_non_json_string_returns_none():
    """Не-JSON строка → None, без исключений."""
    assert parse_event("это не json") is None
    assert parse_event("") is None
    assert parse_event("<xml/>") is None


def test_json_scalar_and_array_return_none():
    """JSON-скаляр/массив вместо объекта — не кадр событий."""
    assert parse_event("42") is None
    assert parse_event('"chat_message_create"') is None
    assert parse_event("null") is None
    assert parse_event("true") is None
    assert parse_event("[1, 2, 3]") is None


def test_non_string_non_dict_input_returns_none():
    """None/число/список на входе → None."""
    assert parse_event(None) is None
    assert parse_event(42) is None
    assert parse_event(["type"]) is None
    assert parse_event(object()) is None


def test_empty_skeleton_returns_none():
    """Полностью пустой каркас (ни типа, ни data) → None."""
    assert parse_event("{}") is None
    assert parse_event({}) is None
    assert parse_event({"foo": "bar"}) is None
    assert parse_event({"data": {}}) is None
    assert parse_event({"data": None}) is None
    assert parse_event({"type": ""}) is None


def test_data_not_dict_is_tolerated():
    """Мусор в data не роняет парсер: envelope.type спасает каркас."""
    event = parse_event({"type": "chat_message_create", "data": "garbage"})
    assert event is not None
    assert event.type == "chat_message_create"
    assert event.event_data == {}
    assert event.timestamp is None
    # без envelope.type идентифицировать нечего → None
    assert parse_event({"data": "garbage"}) is None


def test_event_type_non_string_falls_back():
    """eventType не строка — fallback на envelope; без него type=''."""
    event = parse_event({"type": "t", "data": {"eventType": 123}})
    assert event is not None
    assert event.type == "t"

    event = parse_event({"data": {"eventType": 123, "eventData": {"chatId": "c1"}}})
    assert event is not None
    assert event.type == ""
    assert event.chat_id == "c1"


def test_envelope_type_non_string_yields_empty_type():
    """Не-строковый envelope.type не ломает парсер."""
    event = parse_event({"type": 5, "data": {"eventData": {"chatId": "c9"}}})
    assert event is not None
    assert event.type == ""
    assert event.chat_id == "c9"


def test_event_data_non_dict_defaults_to_empty():
    """eventData не объект (список/строка/число) → {}."""
    for bad in ([1, 2], "oops", 7, None):
        event = parse_event(_frame(eventData=bad))
        assert event is not None
        assert event.event_data == {}
        assert event.chat_id is None


def test_timestamp_non_string_or_missing_is_none():
    """time не строка или отсутствует → timestamp=None."""
    assert parse_event(_frame(time=1754823600)).timestamp is None
    assert parse_event(_frame(time="")).timestamp is None
    data = _frame()["data"]
    del data["time"]
    assert parse_event({"type": "x", "data": data}).timestamp is None


# ── chat_id: только строки, приоритет ключей ────────────────────────────────


def test_chat_id_taken_only_from_string_values():
    """Числовые/прочие не-строковые id игнорируются."""
    assert parse_event(_frame(eventData={"chatId": 12345})).chat_id is None
    assert parse_event(_frame(eventData={"chatId": None})).chat_id is None
    assert parse_event(_frame(eventData={"chatId": ["c1"]})).chat_id is None
    assert parse_event(_frame(eventData={})).chat_id is None
    assert parse_event(_frame(eventData={"chatId": "0"})).chat_id == "0"


def test_chat_id_key_priority_and_empty_skip():
    """Приоритет chatId > chat_id > id; пустая строка пропускается."""
    ev = parse_event(_frame(eventData={"chat_id": "low", "id": "lowest", "chatId": "top"}))
    assert ev.chat_id == "top"
    ev = parse_event(_frame(eventData={"chatId": "", "chat_id": "mid", "id": "lowest"}))
    assert ev.chat_id == "mid"
    ev = parse_event(_frame(eventData={"id": "lowest"}))
    assert ev.chat_id == "lowest"


# ── is_chat_event ────────────────────────────────────────────────────────────


def test_is_chat_event_true_for_all_chat_types():
    """Все чат-события протокола распознаются: префикс chat_* + просмотр."""
    for t in ("chat_message_create", "chat_message_edited", "chat_message_deleted",
              "chat_state_changed", "chat_participant_action",
              "last_viewed_message_change"):
        assert is_chat_event(WsEvent(type=t, chat_id=None, timestamp=None,
                                     from_current_device=False, event_data={}, raw={})) is True


def test_is_chat_event_false_for_non_chat_types():
    """Не-чат события (счётчики, bell, трудовая, пустой/неизвестный тип) → False."""
    for t in ("unread_chats_count_change", "bell_notification_created_event",
              "bell_notification_deleted_event", "bell_notification_read_event",
              "electronic_work_book_card_status", "user_activity_score_change",
              "", "unknown", "chatbot"):  # "chatbot" без подчёркивания — не chat_*
        assert is_chat_event(WsEvent(type=t, chat_id=None, timestamp=None,
                                     from_current_device=False, event_data={}, raw={})) is False


# ── реестр известных типов ───────────────────────────────────────────────────


def test_known_event_types_covers_protocol_registry():
    """KNOWN_EVENT_TYPES покрывает все 11 типов из реестра converters APK."""
    for t in PROTOCOL_EVENT_TYPES:
        assert t in KNOWN_EVENT_TYPES
        assert isinstance(KNOWN_EVENT_TYPES[t], str) and KNOWN_EVENT_TYPES[t]
