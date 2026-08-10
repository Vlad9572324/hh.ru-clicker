"""Интеграционные тесты Phase 2: mobile-методы api.hh.ru end-to-end.

Проверяется полный путь: функция модуля → app.hh_mobile_transport.mobile_request
→ реальный HTTP (перехваченный библиотекой `responses`) → разбор ответа.
Никаких живых запросов: все URL api.hh.ru замокан, Bearer-токен подменён
через monkeypatch app.oauth._obtain_oauth_token.

Контракт (реализуется параллельно другими агентами):
- app/mobile_chat_list.py      fetch_chat_list(acc, max_pages=5, chat_type=None,
                                 filter_unread=False) -> (items_by_id, display_info,
                                 current_participant_id);            GET  /chats
- app/mobile_chat_thread.py    fetch_thread(acc, neg_id, limit=50) -> dict;
                               fetch_chat_history(acc, chat_id, max_messages=20) -> list;
                                                                     GET  /chats/{id}?limit&order=next
- app/mobile_send_message.py   send_message(acc, chat_id, text, idempotency_key="")
                               -> True | "chat_not_found" | False; 401/5xx — MobileAPIError;
                                                                     POST /chats/{id}/messages
- app/mobile_chat_actions.py   fetch_quick_replies(acc, chat_id, message_id) -> list
                                                                     PUT  /chats/{id}/suggestions/quick_replies?message_id=
                               mark_chat_read(acc, chat_id, message_id) -> bool
                                                                     PUT  /chats/{id}/messages/last_viewed_id (form)
                               send_participant_action(acc, chat_id, action_type="TYPING") -> bool
                                                                     PUT  /chats/{id}/participants/action (json)
- app/mobile_negotiations.py   fetch_negotiations(acc, max_pages=20, per_page=100) -> dict;
                                                                     GET  /negotiations
- app/mobile_neg_meta.py       fetch_negotiations_metadata(acc) -> dict   GET /negotiations
                               fetch_possible_offers(acc) -> list         GET /vacancies/possible_job_offers
- app/hh_client_fallback.py    FallbackHHClient(mobile, web): MobileAPIError c
                               fallback-статусом (0/401/403/5xx) → повтор через web.

ИМПОРТЫ модулей реализации выполняются ВНУТРИ тест-функций: пока Phase 2
пишется параллельно, отсутствующий модуль должен ронять только свои тесты
(ModuleNotFoundError), а не коллекционирование всего файла.

Маркеры НЕ используются: в pytest.ini включён --strict-markers, а маркер
integration там не зарегистрирован — без маркеров тесты запускаются по
умолчанию.
"""
import importlib
import json
from urllib.parse import parse_qsl

import pytest
import responses

from app import oauth
from app.hh_client_mobile import MobileHHClient
from app.hh_client_web import WebHHClient
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}


@pytest.fixture
def oauth_token(monkeypatch):
    """Bearer-токен добывается через app.oauth._obtain_oauth_token —
    подменяем, чтобы не идти в реальный OAuth-flow."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")


def _last_request():
    assert responses.calls, "ни одного реального HTTP-запроса не было"
    return responses.calls[-1].request


def _assert_bearer(req):
    assert req.headers["Authorization"] == "Bearer t"
    # мобильные заголовки транспорта (контракт APK)
    assert req.headers["x-force-app-access"] == "true"


def _body_as_dict(req):
    """Тело запроса как dict — независимо от кодировки (JSON или form)."""
    raw = req.body or ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except ValueError:
        return dict(parse_qsl(raw))


# ---------------------------------------------------------------------------
# Мок-ответы. Форма — по live-пробам из docs/API_REFERENCE.md (A4/A5) и
# официальному виду коллекций api.hh.ru {"items": [...], "found", "pages"}.
# ---------------------------------------------------------------------------

CHAT_LIST_RESPONSE = {
    "chats": {
        "items": [
            {
                "id": "5522666855",
                "unread_count": 5,
                "type": "NEGOTIATION",
                "display": {"title": "Студия МГЛА"},
                "messages": {
                    "last": {
                        "id": 15047614423,
                        "participant_id": "163778010-EMPLOYER_USER",
                        "body": {"text": {"content": "Добрый день!"}},
                    }
                },
                "participants": {
                    "ids": ["163778010-EMPLOYER_USER", "153336782-APPLICANT_USER"]
                },
                "write_possibility": {"name": "ENABLED_FOR_ALL", "write_disabled_reasons": []},
            }
        ],
        "found": 1,
        "pages": 1,
        "page": 0,
        "per_page": 20,
        "has_next_page": False,
    },
    "participants": {
        "163778010-EMPLOYER_USER": {"display": {"name": "Анна"}},
        "153336782-APPLICANT_USER": {
            "display": {"name": "Тестовый Пользователь"},
            "is_current_user": True,
        },
    },
    "resources": {"employers": {}, "vacancies": {}, "resumes": {}, "negotiations": {}},
}

# Конверт ответа GET /chats/{chat_id} — {chat, participants, resources,
# chat_states}, сообщения в chat.messages.items[] (контракт APK, см.
# докстринг app/mobile_chat_thread.py).
CHAT_THREAD_RESPONSE = {
    "chat": {
        "id": "5512844915",
        "display": {
            "title": "Художник по окружению / Level artist (gamedev)",
            "subtitle": "Студия МГЛА, Анна",
            "icon": None,
        },
        "type": "NEGOTIATION",
        "creation_time": "2026-07-29T11:00:00+0300",
        "unread_count": 1,
        "participants": {
            "ids": ["163778010-EMPLOYER_USER", "153336782-APPLICANT_USER"]
        },
        "messages": {
            "items": [
                {
                    "id": 14932421767,
                    "participant_id": "153336782-APPLICANT_USER",
                    "participant_display": {"name": "Тестовый Пользователь", "is_bot": False},
                    "created_at": "2026-07-29T12:00:00+0300",
                    "type": "SIMPLE",
                    "body": {"text": {"content": "Здравствуйте! Откликнулась на вакансию."}},
                },
                {
                    "id": 14932421768,
                    "participant_id": "163778010-EMPLOYER_USER",
                    "participant_display": {"name": "Анна", "is_bot": False},
                    "created_at": "2026-07-30T03:48:33+0300",
                    "type": "SIMPLE",
                    "body": {"text": {"content": "Добрый день! Когда сможете выйти?"}},
                },
            ],
            "has_next": False,
            "has_prev": False,
        },
        "resources": {"negotiations": ["5465575576"], "vacancies": {}},
    },
    "participants": {
        "163778010-EMPLOYER_USER": {"display": {"name": "Анна"}},
        "153336782-APPLICANT_USER": {"display": {"name": "Тестовый Пользователь"}},
    },
    "resources": {"negotiations": {"5465575576": {"state": {"id": "response"}}}},
    "chat_states": {"write_message_state": {"allowed": True, "reasons": []}},
}

NEGOTIATIONS_RESPONSE = {
    "items": [
        {
            "id": "5512844915",
            "created_at": "2026-08-09T12:00:00+0300",
            "state": {"id": "response", "name": "Отклик"},
            "has_new_messages": True,
            "viewed_by_opponent": True,
            "vacancy": {"id": "135164800", "name": "Python-разработчик"},
            "messages_url": "https://api.hh.ru/negotiations/5512844915/messages",
        }
    ],
    "found": 1,
    "pages": 1,
    "page": 0,
    "per_page": 100,
}

POSSIBLE_OFFERS_RESPONSE = {
    "items": [
        {
            "id": "100500",
            "name": "Студия МГЛА",
            "vacancies": [{"id": "135164800", "name": "Python-разработчик"}],
        }
    ]
}


# ---------------------------------------------------------------------------
# 1. app/mobile_chat_list.py — fetch_chat_list
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_fetch_chat_list_end_to_end(oauth_token):
    from app.mobile_chat_list import fetch_chat_list

    responses.add(responses.GET, MOBILE_BASE + "/chats",
                  json=CHAT_LIST_RESPONSE, status=200)

    result = fetch_chat_list(ACC)

    assert isinstance(result, tuple) and len(result) == 3
    items_by_id, display_info, current_participant_id = result
    assert isinstance(items_by_id, dict)
    assert "5522666855" in items_by_id  # ключ — id чата
    assert isinstance(display_info, dict)
    assert display_info["5522666855"]["title"] == "Студия МГЛА"
    # текущий участник — is_current_user из top-level participants
    assert current_participant_id == "153336782-APPLICANT_USER"

    assert len(responses.calls) == 1  # одна страница: has_next_page=false
    req = _last_request()
    assert req.method == "GET"
    assert req.url.split("?")[0] == MOBILE_BASE + "/chats"
    _assert_bearer(req)


@responses.activate
def test_mobile_fetch_chat_list_filters(oauth_token):
    """chat_type/filter_unread пробрасываются в запрос/фильтрацию."""
    from app.mobile_chat_list import fetch_chat_list

    responses.add(responses.GET, MOBILE_BASE + "/chats",
                  json=CHAT_LIST_RESPONSE, status=200)

    items_by_id, _display, _pid = fetch_chat_list(
        ACC, chat_type="NEGOTIATION", filter_unread=True)

    # чат типа NEGOTIATION остался в результате
    assert "5522666855" in items_by_id
    req = _last_request()
    assert "filter_unread" in req.url.lower()
    _assert_bearer(req)


# ---------------------------------------------------------------------------
# 2. app/mobile_chat_thread.py — fetch_thread, fetch_chat_history
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_fetch_thread_end_to_end(oauth_token):
    from app.mobile_chat_thread import fetch_thread

    responses.add(responses.GET, MOBILE_BASE + "/chats/5512844915",
                  json=CHAT_THREAD_RESPONSE, status=200)

    result = fetch_thread(ACC, "5512844915")

    assert isinstance(result, dict) and result
    # текст последнего сообщения работодателя дошёл до результата
    assert "Добрый день! Когда сможете выйти?" in str(result)

    req = _last_request()
    assert req.method == "GET"
    assert req.url.split("?")[0] == MOBILE_BASE + "/chats/5512844915"
    assert "limit=50" in req.url
    assert "order=next" in req.url
    _assert_bearer(req)


@responses.activate
def test_mobile_fetch_chat_history_end_to_end(oauth_token):
    from app.mobile_chat_thread import fetch_chat_history

    responses.add(responses.GET, MOBILE_BASE + "/chats/5512844915",
                  json=CHAT_THREAD_RESPONSE, status=200)

    messages = fetch_chat_history(ACC, "5512844915", max_messages=20)

    assert isinstance(messages, list)
    assert len(messages) == 2  # оба SIMPLE-сообщения, лимит 20 не режет
    assert all(isinstance(m, dict) for m in messages)
    assert any("Добрый день! Когда сможете выйти?" in str(m) for m in messages)

    req = _last_request()
    assert req.method == "GET"
    assert req.url.split("?")[0] == MOBILE_BASE + "/chats/5512844915"
    assert "limit=" in req.url
    assert "order=next" in req.url
    _assert_bearer(req)


# ---------------------------------------------------------------------------
# 3. app/mobile_send_message.py — send_message
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_send_message_2xx_true_and_body(oauth_token):
    from app.mobile_send_message import send_message

    responses.add(responses.POST, MOBILE_BASE + "/chats/77/messages",
                  json={"id": 15047614424}, status=200)

    assert send_message(ACC, "77", "Здравствуйте!", idempotency_key="k-1") is True

    req = _last_request()
    assert req.method == "POST"
    assert req.url.split("?")[0] == MOBILE_BASE + "/chats/77/messages"
    _assert_bearer(req)
    body = _body_as_dict(req)
    assert body.get("text") == "Здравствуйте!"
    assert str(body.get("idempotency_key")) == "k-1"


@responses.activate
def test_mobile_send_message_404_chat_not_found(oauth_token):
    from app.mobile_send_message import send_message

    responses.add(responses.POST, MOBILE_BASE + "/chats/77/messages",
                  json={"errors": [{"value": "chat_not_found"}]}, status=404)

    assert send_message(ACC, "77", "текст") == "chat_not_found"


@pytest.mark.parametrize("status", [400, 409])
@responses.activate
def test_mobile_send_message_other_4xx_returns_false(oauth_token, status):
    from app.mobile_send_message import send_message

    responses.add(responses.POST, MOBILE_BASE + "/chats/77/messages",
                  json={"errors": [{"value": "bad_request"}]}, status=status)

    assert send_message(ACC, "77", "текст") is False


@pytest.mark.parametrize("status", [401, 500])
@responses.activate
def test_mobile_send_message_fallback_status_raises(oauth_token, status):
    """401/5xx — fallback-статусы: проглатывать нельзя, кидает MobileAPIError."""
    from app.mobile_send_message import send_message

    responses.add(responses.POST, MOBILE_BASE + "/chats/77/messages",
                  json={"errors": [{"value": "token_expired"}]}, status=status)

    with pytest.raises(MobileAPIError) as ei:
        send_message(ACC, "77", "текст")
    assert ei.value.status_code == status


# ---------------------------------------------------------------------------
# 4. app/mobile_chat_actions.py — quick_replies, mark_chat_read, participant action
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_fetch_quick_replies_end_to_end(oauth_token):
    from app.mobile_chat_actions import fetch_quick_replies

    responses.add(
        responses.PUT, MOBILE_BASE + "/chats/c1/suggestions/quick_replies",
        json={"quick_replies": [
            {"id": "qr1", "type": "send", "text": "Здравствуйте! Расскажите подробнее."},
            {"id": "qr2", "type": "send", "text": "Какая зарплата?"},
        ]},
        status=200,
    )

    result = fetch_quick_replies(ACC, "c1", "m1")

    assert isinstance(result, list)
    assert len(result) == 2

    req = _last_request()
    assert req.method == "PUT"
    assert req.url.split("?")[0] == MOBILE_BASE + "/chats/c1/suggestions/quick_replies"
    assert "message_id=m1" in req.url
    _assert_bearer(req)


@responses.activate
def test_mobile_mark_chat_read_end_to_end(oauth_token):
    from app.mobile_chat_actions import mark_chat_read

    responses.add(responses.PUT,
                  MOBILE_BASE + "/chats/c1/messages/last_viewed_id",
                  status=204)  # write-маркер: пустое тело

    assert mark_chat_read(ACC, "c1", "999") is True

    req = _last_request()
    assert req.method == "PUT"
    assert req.url.split("?")[0] == MOBILE_BASE + "/chats/c1/messages/last_viewed_id"
    # form-body message_id=<long>
    assert _body_as_dict(req).get("message_id") in ("999", 999)
    _assert_bearer(req)


@responses.activate
def test_mobile_send_participant_action_end_to_end(oauth_token):
    from app.mobile_chat_actions import send_participant_action

    responses.add(responses.PUT,
                  MOBILE_BASE + "/chats/c1/participants/action",
                  json={}, status=200)

    assert send_participant_action(ACC, "c1") is True  # дефолт action_type="TYPING"

    req = _last_request()
    assert req.method == "PUT"
    assert req.url.split("?")[0] == MOBILE_BASE + "/chats/c1/participants/action"
    # контракт APK: enum в нижнем регистре ("typing"/"none") — реализация
    # нормализует входящий "TYPING" (web-конвенция) к нижнему
    assert str(_body_as_dict(req).get("action_type")).upper() == "TYPING"
    _assert_bearer(req)


# ---------------------------------------------------------------------------
# 5. app/mobile_negotiations.py — fetch_negotiations
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_fetch_negotiations_end_to_end(oauth_token):
    from app.mobile_negotiations import fetch_negotiations

    responses.add(responses.GET, MOBILE_BASE + "/negotiations",
                  json=NEGOTIATIONS_RESPONSE, status=200)

    result = fetch_negotiations(ACC, max_pages=1)

    assert isinstance(result, dict) and result
    # web-совместимая статистика: один topic в состоянии "response",
    # просмотрен работодателем, есть непрочитанные HR'ом сообщения
    assert result["neg_ids"] == ["5512844915"]
    assert result["auth_error"] is False
    assert result["viewed"] == 1
    assert result["unread_by_employer"] == 1
    assert len(responses.calls) == 1  # max_pages=1 и pages=1

    req = _last_request()
    assert req.method == "GET"
    assert req.url.split("?")[0] == MOBILE_BASE + "/negotiations"
    assert "per_page=100" in req.url
    _assert_bearer(req)


# ---------------------------------------------------------------------------
# 6. app/mobile_neg_meta.py — fetch_negotiations_metadata, fetch_possible_offers
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_fetch_negotiations_metadata_end_to_end(oauth_token):
    from app.mobile_neg_meta import fetch_negotiations_metadata

    responses.add(responses.GET, MOBILE_BASE + "/negotiations",
                  json=NEGOTIATIONS_RESPONSE, status=200)

    result = fetch_negotiations_metadata(ACC)

    assert isinstance(result, dict)
    # web-совместимая структура: politeness/activity в mobile недоступны
    # (пустые), per-vacancy статусы — из items GET /negotiations
    assert "politeness" in result and "activity" in result
    topic = result["topics_by_vid"]["135164800"]
    assert topic["viewed_by_opponent"] is True
    assert topic["last_state"] == "response"
    assert topic["has_new_messages"] is True

    req = _last_request()
    assert req.method == "GET"
    assert req.url.split("?")[0] == MOBILE_BASE + "/negotiations"
    _assert_bearer(req)


@responses.activate
def test_mobile_fetch_possible_offers_end_to_end(oauth_token):
    from app.mobile_neg_meta import fetch_possible_offers

    responses.add(responses.GET, MOBILE_BASE + "/vacancies/possible_job_offers",
                  json=POSSIBLE_OFFERS_RESPONSE, status=200)

    result = fetch_possible_offers(ACC)

    assert isinstance(result, list)
    assert len(result) == 1
    # web-совместимый формат: имя компании + названия вакансий
    assert result[0]["name"] == "Студия МГЛА"
    assert result[0]["vacancyNames"] == ["Python-разработчик"]

    req = _last_request()
    assert req.method == "GET"
    assert req.url.split("?")[0] == MOBILE_BASE + "/vacancies/possible_job_offers"
    _assert_bearer(req)


# ---------------------------------------------------------------------------
# 7. Guard: все функции Phase 2 присутствуют и вызываемы.
#    8 клиентских методов группы A (phase 2) + 2 функции mobile_neg_meta.
# ---------------------------------------------------------------------------

PHASE2_MODULE_FUNCTIONS = [
    ("mobile_chat_list", "fetch_chat_list"),
    ("mobile_chat_thread", "fetch_thread"),
    ("mobile_chat_thread", "fetch_chat_history"),
    ("mobile_send_message", "send_message"),
    ("mobile_chat_actions", "fetch_quick_replies"),
    ("mobile_chat_actions", "mark_chat_read"),
    ("mobile_chat_actions", "send_participant_action"),
    ("mobile_negotiations", "fetch_negotiations"),
    ("mobile_neg_meta", "fetch_negotiations_metadata"),
    ("mobile_neg_meta", "fetch_possible_offers"),
]


@pytest.mark.parametrize(
    "module_name,func_name",
    PHASE2_MODULE_FUNCTIONS,
    ids=[f"{m}.{f}" for m, f in PHASE2_MODULE_FUNCTIONS],
)
def test_phase2_function_exists_and_callable(module_name, func_name):
    module = importlib.import_module(f"app.{module_name}")
    func = getattr(module, func_name, None)
    assert func is not None, f"в app.{module_name} нет {func_name}"
    assert callable(func)


# ---------------------------------------------------------------------------
# 8. Auto-fallback mobile → web (app/hh_client_fallback.py).
#    Фейки — наследники реальных клиентов: проходят любые isinstance-проверки,
#    подменяя только тестируемые методы.
# ---------------------------------------------------------------------------

class _Mobile401(MobileHHClient):
    """Реальный MobileHHClient, но phase-2 методы кидают MobileAPIError(401)."""

    def fetch_thread(self, neg_id):
        raise MobileAPIError(401, payload="token_expired",
                             url=f"{MOBILE_BASE}/chats/{neg_id}")

    def send_message(self, neg_id, text, topic_id=""):
        raise MobileAPIError(401, payload="token_expired",
                             url=f"{MOBILE_BASE}/chats/{neg_id}/messages")


class _Mobile404(MobileHHClient):
    def fetch_thread(self, neg_id):
        raise MobileAPIError(404, payload={"errors": [{"value": "chat_not_found"}]},
                             url=f"{MOBILE_BASE}/chats/{neg_id}")


class _MobileOk(MobileHHClient):
    def fetch_thread(self, neg_id):
        return {"neg_id": neg_id, "messages": [], "via": "mobile"}


class _RecordingWeb(WebHHClient):
    """Web-двойник: записывает вызовы и возвращает узнаваемый результат."""

    def __init__(self, acc):
        super().__init__(acc)
        self.calls = []

    def fetch_thread(self, neg_id):
        self.calls.append(("fetch_thread", neg_id))
        return {"neg_id": neg_id, "messages": [], "via": "web"}

    def send_message(self, neg_id, text, topic_id=""):
        self.calls.append(("send_message", neg_id, text))
        return True


def test_fallback_client_401_switches_to_web():
    from app.hh_client_fallback import FallbackHHClient

    web = _RecordingWeb(ACC)
    client = FallbackHHClient(_Mobile401(ACC), web)

    result = client.fetch_thread("n1")

    assert result == {"neg_id": "n1", "messages": [], "via": "web"}
    assert web.calls == [("fetch_thread", "n1")]


def test_fallback_client_mobile_ok_web_untouched():
    from app.hh_client_fallback import FallbackHHClient

    web = _RecordingWeb(ACC)
    client = FallbackHHClient(_MobileOk(ACC), web)

    assert client.fetch_thread("n2") == {"neg_id": "n2", "messages": [], "via": "mobile"}
    assert web.calls == []  # mobile справился — web не трогаем


def test_fallback_client_non_fallback_status_reraises():
    """404 — НЕ fallback-статус: повтор через web запрещён, ошибка пробрасывается."""
    from app.hh_client_fallback import FallbackHHClient

    web = _RecordingWeb(ACC)
    client = FallbackHHClient(_Mobile404(ACC), web)

    with pytest.raises(MobileAPIError) as ei:
        client.fetch_thread("n3")
    assert ei.value.status_code == 404
    assert web.calls == []


@responses.activate
def test_fallback_real_mobile_401_falls_back_to_web(oauth_token):
    """Полный end-to-end: реальный MobileHHClient.fetch_thread получает 401
    от api.hh.ru → FallbackHHClient прозрачно повторяет через web-клиент.

    Требует phase-2 обвязки MobileHHClient.fetch_thread мобильными модулями;
    пока обвязки нет, тест падает с NotImplementedError — это ожидаемо и
    фиксируется в отчёте.
    """
    from app.hh_client_fallback import FallbackHHClient

    body = {"errors": [{"type": "authorization", "value": "token_expired"}]}
    responses.add(responses.GET, MOBILE_BASE + "/chats/n9",
                  json=body, status=401)

    web = _RecordingWeb(ACC)
    client = FallbackHHClient(MobileHHClient(ACC), web)

    result = client.fetch_thread("n9")

    assert result == {"neg_id": "n9", "messages": [], "via": "web"}
    assert web.calls == [("fetch_thread", "n9")]
