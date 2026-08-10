"""Тесты mobile-чтения треда/истории чата (app/mobile_chat_thread.py).

Фикстуры — обрезанные реальные ответы GET api.hh.ru/chats/{chat_id}
(scratchpad/deepdive/g7_raw/neg_history.json, bot_history.json).
Все запросы через мок-библиотеку responses — живого HTTP нет.
"""
import copy

import pytest
import responses

from app import oauth
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError
from app.mobile_chat_thread import fetch_chat_history, fetch_thread

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}


@pytest.fixture
def acc(monkeypatch):
    """Аккаунт с подменённым получением OAuth-токена (всегда 't')."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    return ACC


# Обрезанный реальный neg_history.json: NEGOTIATION-чат, 2 сообщения —
# отклик applicant'а и отказ employer'а (оба SIMPLE, оба с workflow_transition).
NEG_HISTORY = {
    "chat": {
        "id": "5512844915",
        "unread_count": 1,
        "type": "NEGOTIATION",
        "messages": {
            "has_more": False,
            "items": [
                {
                    "id": 14932421768,
                    "participant_id": "153336782-APPLICANT_USER",
                    "participant_display": {"name": "Тестовый Пользователь", "is_bot": False},
                    "created_at": "2026-07-30T03:48:33+0300",
                    "type": "SIMPLE",
                    "body": {"text": {"content": "Здравствуйте! Я выражаю искренний интерес к вашей компании."}},
                    "workflow_transition": {"id": "14932421765", "topic_id": "5465575576",
                                            "applicant_state": {"id": "response", "name": "Отклик"}},
                },
                {
                    "id": 15030336814,
                    "participant_id": "163778010-EMPLOYER_USER",
                    "participant_display": {"name": "Анна", "is_bot": False},
                    "created_at": "2026-08-07T15:29:51+0300",
                    "type": "SIMPLE",
                    "body": {"text": {"content": "Здравствуйте! Спасибо за отклик. Увы, сейчас предложить ничего не можем."}},
                    "workflow_transition": {"id": "15030336721", "topic_id": "5465575576",
                                            "applicant_state": {"id": "discard", "name": "Отказ"}},
                },
            ],
        },
        "display": {"title": "Художник по окружению / Level artist (gamedev)",
                    "subtitle": "Студия МГЛА"},
        "participants": {"ids": ["163778010-EMPLOYER_USER", "153336782-APPLICANT_USER"]},
        "resources": {"vacancies": ["134210190"], "resumes": ["243602103"],
                      "negotiations": ["5465575576"]},
    },
    "participants": {
        "153336782-APPLICANT_USER": {"id": "153336782-APPLICANT_USER", "type": "applicant",
                                     "is_current_user": True},
        "163778010-EMPLOYER_USER": {"id": "163778010-EMPLOYER_USER", "type": "employer_manager",
                                    "is_current_user": False},
    },
    "resources": {"negotiations": {"5465575576": {"id": "5465575576", "vacancy": "134210190",
                                                  "applicant_state": {"id": "discard", "name": "Отказ"}}}},
    "chat_states": {"write_message_state": {"allowed": False, "reasons": ["WITHOUT_INVITATION"]}},
}

# Обрезанный реальный bot_history.json / career_bot_history.json: BOT-чат,
# сообщения бота с body.actions + не-SIMPLE событие (должно отфильтроваться).
BOT_HISTORY = {
    "chat": {
        "id": "5536833271",
        "unread_count": 2,
        "type": "BOT",
        "messages": {
            "has_more": False,
            "items": [
                {
                    "id": 15043347544,
                    "participant_id": "128627571-BOT",
                    "participant_display": {"name": "ИИ-помощник", "is_bot": True},
                    "type": "SIMPLE",
                    "body": {"text": {"content": "Привет! Я ваш ИИ-помощник"}},
                },
                {
                    "id": 15043347545,
                    "participant_id": "128627571-BOT",
                    "participant_display": {"name": "ИИ-помощник", "is_bot": True},
                    "type": "SIMPLE",
                    "body": {"text": {"content": "О чем вы хотите узнать?"},
                             "actions": {"buttons": [],
                                         "text_buttons": [{"size": "compact", "text": "Да"},
                                                          {"size": "compact", "text": "Нет"}]}},
                },
                {
                    "id": 15043347546,
                    "participant_id": "153336782-APPLICANT_USER",
                    "participant_display": {"name": "Тестовый Пользователь", "is_bot": False},
                    "type": "SIMPLE",
                    "body": {"text": {"content": "Ищу работу в продажах"}},
                },
                {
                    # не-SIMPLE — в историю попасть не должно
                    "id": 15043347547,
                    "participant_id": "128627571-BOT",
                    "participant_display": {"name": "ИИ-помощник", "is_bot": True},
                    "type": "WORKFLOW",
                    "body": {"text": {"content": "системное событие"}},
                },
            ],
        },
        "display": {"title": "Поиск с ИИ-помощником", "subtitle": "Бета-версия"},
        "resources": {"negotiations": []},
    },
    "chat_states": {"write_message_state": {"allowed": True, "reasons": []}},
}


def _mock_chat(chat_id: str, payload: dict, status: int = 200):
    responses.add(responses.GET, f"{MOBILE_BASE}/chats/{chat_id}",
                  json=payload, status=status)


# ── fetch_thread ──────────────────────────────────────────────────────


@responses.activate
def test_fetch_thread_ok_neg_history(acc):
    """200 на реальном neg_history.json: ключи, маппинг полей, запрос."""
    _mock_chat("5512844915", NEG_HISTORY)
    r = fetch_thread(acc, "5512844915")

    assert r["error"] == ""
    assert r["neg_id"] == "5512844915"
    assert r["employer_name"] == "Студия МГЛА"           # display.subtitle
    assert r["vacancy_title"] == "Художник по окружению / Level artist (gamedev)"  # display.title
    assert r["topic_id"] == "5465575576"                 # resources.negotiations[0]
    assert len(r["messages"]) == 2                       # оба SIMPLE с текстом
    assert r["messages"][0]["sender"] == "applicant"
    assert r["messages"][0]["msg_id"] == "14932421768"
    assert r["messages"][0]["is_bot"] is False
    assert r["messages"][1]["sender"] == "employer"
    assert r["last_msg_id"] == "15030336814"
    assert r["last_employer_msg"].startswith("Здравствуйте! Спасибо за отклик.")
    # unread_count=1, последнее от employer, текст есть -> нужен ответ
    assert r["needs_reply"] is True

    req = responses.calls[0].request
    assert "limit=50" in req.url and "order=next" in req.url
    assert req.headers["Authorization"] == "Bearer t"


@responses.activate
def test_fetch_thread_last_from_applicant_no_reply(acc):
    """Последнее сообщение от applicant (даже при unread>0) -> needs_reply False."""
    payload = copy.deepcopy(NEG_HISTORY)
    payload["chat"]["unread_count"] = 3
    payload["chat"]["messages"]["items"].append({
        "id": 15030336999,
        "participant_id": "153336782-APPLICANT_USER",
        "participant_display": {"name": "Тестовый Пользователь", "is_bot": False},
        "type": "SIMPLE",
        "body": {"text": {"content": "Поняла, спасибо за ответ!"}},
    })
    _mock_chat("5512844915", payload)
    r = fetch_thread(acc, "5512844915")

    assert r["needs_reply"] is False
    assert r["last_msg_id"] == "15030336999"
    # последнее от applicant -> last_employer_msg остаётся текстом employer'а
    assert r["last_employer_msg"].startswith("Здравствуйте! Спасибо за отклик.")


@responses.activate
def test_fetch_thread_employer_unread_needs_reply(acc):
    """Последнее от employer + unread>0 -> needs_reply True; unread=0 -> False."""
    _mock_chat("5512844915", NEG_HISTORY)
    assert fetch_thread(acc, "5512844915")["needs_reply"] is True

    responses.reset()
    payload = copy.deepcopy(NEG_HISTORY)
    payload["chat"]["unread_count"] = 0
    _mock_chat("5512844915", payload)
    assert fetch_thread(acc, "5512844915")["needs_reply"] is False


@responses.activate
def test_fetch_thread_workflow_event_no_text_no_reply(acc):
    """Последнее — workflow-событие без текста (смена статуса) -> needs_reply False."""
    payload = copy.deepcopy(NEG_HISTORY)
    payload["chat"]["messages"]["items"].append({
        "id": 15030337000,
        "participant_id": "163778010-EMPLOYER_USER",
        "participant_display": {"name": "Анна", "is_bot": False},
        "type": "SIMPLE",
        "body": {"text": {"content": ""}},
        "workflow_transition": {"id": "15030336999", "topic_id": "5465575576",
                                "applicant_state": {"id": "discard", "name": "Отказ"}},
    })
    _mock_chat("5512844915", payload)
    r = fetch_thread(acc, "5512844915")

    assert r["needs_reply"] is False
    assert r["last_msg_id"] == "15030337000"
    assert len(r["messages"]) == 2  # workflow-событие без текста не в messages


@responses.activate
def test_fetch_thread_404_returns_error_dict(acc):
    """404 -> dict с заполненным error, НЕ кидает."""
    _mock_chat("999", {"errors": [{"type": "not_found"}]}, status=404)
    r = fetch_thread(acc, "999")

    assert isinstance(r, dict)
    assert r["neg_id"] == "999"
    assert r["error"] != ""
    assert "404" in r["error"]
    assert r["messages"] == [] and r["needs_reply"] is False


@responses.activate
def test_fetch_thread_400_returns_error_dict(acc):
    """400 (не fallback) -> тоже dict с error, не исключение."""
    _mock_chat("5512844915", {"errors": [{"type": "bad_request"}]}, status=400)
    r = fetch_thread(acc, "5512844915")

    assert r["error"] != "" and "400" in r["error"]


@responses.activate
def test_fetch_thread_401_raises_mobile_api_error(acc):
    """401 — fallback-статус: MobileAPIError поднимается (не глотается)."""
    _mock_chat("5512844915", {"errors": [{"type": "unauthorized"}]}, status=401)
    with pytest.raises(MobileAPIError) as ei:
        fetch_thread(acc, "5512844915")
    assert ei.value.status_code == 401


# ── fetch_chat_history ────────────────────────────────────────────────


@responses.activate
def test_fetch_chat_history_ok_oldest_first_simple_only(acc):
    """200 на bot-фикстуре: oldest-first, sender'ы, только SIMPLE с текстом."""
    _mock_chat("5536833271", BOT_HISTORY)
    history = fetch_chat_history(acc, "5536833271")

    # WORKFLOW-событие отфильтровано, остальные 3 — в порядке возрастания id
    assert [m["msg_id"] for m in history] == ["15043347544", "15043347545", "15043347546"]
    assert [m["sender"] for m in history] == ["employer", "employer", "applicant"]
    assert [m["is_bot"] for m in history] == [True, True, False]
    assert history[0]["text"] == "Привет! Я ваш ИИ-помощник"
    # actions из body.actions; у сообщений без actions — {}
    assert history[1]["actions"]["text_buttons"][0]["text"] == "Да"
    assert history[0]["actions"] == {}
    assert history[2]["actions"] == {}

    req = responses.calls[0].request
    assert "limit=20" in req.url and "order=next" in req.url


@responses.activate
def test_fetch_chat_history_truncates_to_max_messages(acc):
    """Обрезка до последних max_messages (свежайший контекст)."""
    _mock_chat("5536833271", BOT_HISTORY)
    history = fetch_chat_history(acc, "5536833271", max_messages=2)

    assert len(history) == 2
    assert [m["msg_id"] for m in history] == ["15043347545", "15043347546"]
    assert history[0]["sender"] == "employer" and history[1]["sender"] == "applicant"


@responses.activate
def test_fetch_chat_history_non_fallback_error_returns_empty(acc):
    """404/400 (не fallback) -> пустой список, без исключения."""
    _mock_chat("999", {"errors": [{"type": "not_found"}]}, status=404)
    assert fetch_chat_history(acc, "999") == []

    responses.reset()
    _mock_chat("999", {"errors": [{"type": "bad_request"}]}, status=400)
    assert fetch_chat_history(acc, "999") == []


@responses.activate
def test_fetch_chat_history_401_raises_mobile_api_error(acc):
    """401 — fallback-статус: MobileAPIError поднимается."""
    _mock_chat("5536833271", {"errors": [{"type": "unauthorized"}]}, status=401)
    with pytest.raises(MobileAPIError) as ei:
        fetch_chat_history(acc, "5536833271")
    assert ei.value.status_code == 401
