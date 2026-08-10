"""Тесты mobile-получения списка чатов (app/mobile_chat_list.py).

Все запросы мок-ятся библиотекой `responses` (никаких живых HTTP),
OAuth-токен подменяется monkeypatch'ем app.oauth._obtain_oauth_token —
конвенция tests/test_hh_mobile_transport.py.
"""
import pytest
import responses

from app import oauth
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError
from app.mobile_chat_list import fetch_chat_list

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
CHATS_URL = MOBILE_BASE + "/chats"

# Реальные куски ответа GET /chats (scratchpad/deepdive/g7_raw/list_page20.json,
# list_unread.json), обрезанные до значимых полей.
ITEM_BOT = {
    "id": "5522666855",
    "unread_count": 5,
    "is_pinned": False,
    "type": "BOT",
    "subtype": "CAREER_ASSISTANT",
    "is_notification_enabled": True,
    "messages": {"last": {"id": 15047614423, "participant_id": "128627571-BOT"}},
    "display": {
        "title": "Карьерный помощник",
        "subtitle": "Бета-версия",
        "icon": {"url": "https://img.hhcdn.ru/file/18164151.png"},
    },
    "participants": {"ids": ["128627571-BOT", "153336782-APPLICANT_USER"]},
    "write_possibility": {"name": "ENABLED_FOR_ALL", "write_disabled_reasons": []},
    "operations": {"enabled": ["LEAVE_CHAT", "DISABLE_NOTIFICATIONS"]},
}
ITEM_NEGOTIATION = {
    "id": "5512844915",
    "unread_count": 1,
    "is_pinned": False,
    "type": "NEGOTIATION",
    "is_notification_enabled": True,
    "messages": {"last": {"id": 15030336814, "participant_id": "163778010-EMPLOYER_USER"}},
    "display": {
        "title": "Художник по окружению / Level artist (gamedev)",
        "subtitle": "Студия МГЛА",
        "icon": {"url": "https://img.hhcdn.ru/employer-logo/12255092.png"},
    },
    "participants": {"ids": ["163778010-EMPLOYER_USER", "153336782-APPLICANT_USER"]},
    "write_possibility": {
        "name": "DISABLED_FOR_APPLICANT",
        "write_disabled_reasons": ["WITHOUT_INVITATION"],
    },
    "operations": {"enabled": ["LEAVE_CHAT", "DISABLE_NOTIFICATIONS"]},
}

PARTICIPANTS = {
    "153336782-APPLICANT_USER": {
        "id": "153336782-APPLICANT_USER",
        "type": "applicant",
        "external_id": "153336782",
        "display": {"name": "Мария"},
        "is_current_user": True,
    },
    "163778010-EMPLOYER_USER": {
        "id": "163778010-EMPLOYER_USER",
        "type": "employer_manager",
        "external_id": "163778010",
        "display": {"name": "Анна"},
        "is_current_user": False,
    },
}


def _chats_response(items: list, *, page: int = 0, has_next_page: bool = False,
                    participants: dict | None = None) -> dict:
    """Собрать ответ GET /chats по схеме реального API."""
    return {
        "chats": {
            "items": items,
            "found": len(items),
            "pages": 1,
            "page": page,
            "per_page": 20,
            "has_next_page": has_next_page,
        },
        "participants": PARTICIPANTS if participants is None else participants,
        "resources": {},
        "missing_resources": {},
    }


def _patch_token(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")


@responses.activate
def test_single_page_returns_compatible_tuple(monkeypatch):
    """200, одна страница: tuple из 3 элементов с правильным содержимым."""
    _patch_token(monkeypatch)
    responses.add(responses.GET, CHATS_URL,
                  json=_chats_response([ITEM_BOT, ITEM_NEGOTIATION]), status=200)

    items_by_id, display_info, current_participant_id = fetch_chat_list(ACC)

    # items_by_id: ключи — строковые id, item хранится как есть
    assert set(items_by_id) == {"5522666855", "5512844915"}
    assert items_by_id["5522666855"]["type"] == "BOT"
    assert items_by_id["5522666855"]["unread_count"] == 5
    assert items_by_id["5512844915"]["write_possibility"]["name"] == "DISABLED_FOR_APPLICANT"

    # display_info: title/subtitle/icon_url из item["display"]
    assert display_info["5522666855"] == {
        "title": "Карьерный помощник",
        "subtitle": "Бета-версия",
        "icon_url": "https://img.hhcdn.ru/file/18164151.png",
    }
    assert display_info["5512844915"]["title"] == "Художник по окружению / Level artist (gamedev)"
    assert display_info["5512844915"]["subtitle"] == "Студия МГЛА"

    # current_participant_id: участник с is_current_user=True
    assert current_participant_id == "153336782-APPLICANT_USER"

    # один запрос с page=0 и per_page=20; has_next_page=False -> досрочная остановка
    assert len(responses.calls) == 1
    url = responses.calls[0].request.url
    assert "page=0" in url and "per_page=20" in url


@responses.activate
def test_pagination_merges_pages_and_dedups(monkeypatch):
    """Две страницы (has_next_page true->false): items склеиваются, дедуп по id."""
    _patch_token(monkeypatch)
    responses.add(responses.GET, CHATS_URL,
                  json=_chats_response([ITEM_BOT], page=0, has_next_page=True),
                  status=200)
    # На второй странице дубль ITEM_BOT + новый чат
    item2 = dict(ITEM_NEGOTIATION, id="5382085931")
    responses.add(responses.GET, CHATS_URL,
                  json=_chats_response([ITEM_BOT, item2], page=1, has_next_page=False),
                  status=200)

    items_by_id, display_info, current_participant_id = fetch_chat_list(ACC, max_pages=5)

    assert set(items_by_id) == {"5522666855", "5382085931"}
    assert set(display_info) == {"5522666855", "5382085931"}
    assert current_participant_id == "153336782-APPLICANT_USER"
    # ровно два запроса: page=0 и page=1 (после has_next_page=False стоп)
    assert len(responses.calls) == 2
    assert "page=0" in responses.calls[0].request.url
    assert "page=1" in responses.calls[1].request.url


@responses.activate
def test_empty_response_returns_empty_tuple(monkeypatch):
    """Пустой список чатов -> ({}, {}, ""); пустая страница останавливает пагинацию."""
    _patch_token(monkeypatch)
    responses.add(responses.GET, CHATS_URL,
                  json=_chats_response([], has_next_page=True, participants={}),
                  status=200)

    assert fetch_chat_list(ACC) == ({}, {}, "")
    # пустая страница -> досрочная остановка, второй запрос не нужен
    assert len(responses.calls) == 1


@responses.activate
def test_401_raises_mobile_api_error(monkeypatch):
    """Не-2xx не глотается: MobileAPIError со статусом 401 поднимается."""
    _patch_token(monkeypatch)
    responses.add(responses.GET, CHATS_URL,
                  json={"errors": [{"type": "forbidden"}]}, status=401)

    with pytest.raises(MobileAPIError) as ei:
        fetch_chat_list(ACC)
    assert ei.value.status_code == 401


@responses.activate
def test_filter_unread_passed_in_query(monkeypatch):
    """filter_unread=True попадает в query запроса как filter_unread=true."""
    _patch_token(monkeypatch)
    responses.add(responses.GET, CHATS_URL,
                  json=_chats_response([ITEM_NEGOTIATION]), status=200)

    fetch_chat_list(ACC, filter_unread=True)

    url = responses.calls[0].request.url
    assert "filter_unread=true" in url


@responses.activate
def test_client_side_filtering_by_chat_type(monkeypatch):
    """chat_type передаётся серверу, но фильтрация клиентская по item['type']."""
    _patch_token(monkeypatch)
    responses.add(responses.GET, CHATS_URL,
                  json=_chats_response([ITEM_BOT, ITEM_NEGOTIATION]), status=200)

    items_by_id, display_info, _ = fetch_chat_list(ACC, chat_type="NEGOTIATION")

    # BOT-чат отфильтрован на клиенте, NEGOTIATION остался
    assert set(items_by_id) == {"5512844915"}
    assert set(display_info) == {"5512844915"}
    # параметр type передан серверу (для паритета с APK)
    assert "type=NEGOTIATION" in responses.calls[0].request.url


@responses.activate
def test_current_participant_fallbacks(monkeypatch):
    """Нет is_current_user=True -> fallback по суффиксу -APPLICANT_USER;
    нет и его -> пустая строка."""
    _patch_token(monkeypatch)

    # Фаза 1: у участников нет is_current_user, но есть APPLICANT_USER
    no_flag = {
        "153336782-APPLICANT_USER": {"id": "153336782-APPLICANT_USER",
                                      "type": "applicant"},
        "163778010-EMPLOYER_USER": {"id": "163778010-EMPLOYER_USER",
                                     "type": "employer_manager",
                                     "is_current_user": False},
    }
    responses.add(responses.GET, CHATS_URL,
                  json=_chats_response([ITEM_NEGOTIATION], participants=no_flag),
                  status=200)
    _, _, pid = fetch_chat_list(ACC)
    assert pid == "153336782-APPLICANT_USER"

    # Фаза 2: ни is_current_user, ни APPLICANT-суффикса -> ""
    responses.add(responses.GET, CHATS_URL,
                  json=_chats_response([ITEM_NEGOTIATION],
                                       participants={"1-BOT": {"id": "1-BOT"}}),
                  status=200)
    _, _, pid = fetch_chat_list(ACC)
    assert pid == ""
