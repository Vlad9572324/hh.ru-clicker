"""Phase 3: миграция POST /api/apply/submit на HHClient-фабрику (mobile-ветка).

Покрывает:
- чистый маппер _result_to_response: все 6 result'ов client.submit_response()
  (sent/limit/already/test/auth_error/error) → корректные UI-статусы;
- выбор ветки в api_apply_submit:
  * mobile (FallbackHHClient) + пустой answers → отклик через
    client.submit_response() БЕЗ web-form aiohttp + bookkeeping
    (state.sent += 1, questionnaire_sent НЕ трогается, add_applied,
    bot._add_log "Ручной отклик (mobile)");
  * mobile + НЕпустой answers → старый web-form flow (submit_response не
    вызывается — анкеты остаются территорией web-flow);
  * web-режим (get_client вернул не-FallbackHHClient) → старый web-form
    flow, submit_response не вызывается;
  * исключение из client.submit_response() → {"status": "error"}.

pytest-asyncio в проекте нет — async handler вызывается через asyncio.run()
(хелпер _run устойчив к уже запущенному в потоке event loop — паттерн из
tests/test_debug_neg_ids_regression.py). Бот подменяется monkeypatch'ем
атрибутов singleton'а app.instances.bot (там же паттерн).
"""

import asyncio
import threading
import types

import pytest

import app.routes.apply as apply_route
from app.hh_client_fallback import FallbackHHClient
from app.instances import bot
from app.routes.apply import _result_to_response, api_apply_submit


def _run(coro):
    """Исполнить корутину через asyncio.run, устойчиво к занятому потоку."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict = {}

    def _target():
        try:
            box["result"] = asyncio.run(coro)
        except BaseException as exc:  # перебрасываем в основной поток
            box["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


ACC = {
    "name": "acc1",
    "cookies": {"_xsrf": "x"},
    "resume_hash": "rh1",
    "letter": "cover letter",
    "mode": "mobile",
}


class FakeMobileClient(FallbackHHClient):
    """Поддельный FallbackHHClient: bypass __init__, счётчик submit_response.

    isinstance(..., FallbackHHClient) — истинно, т.е. роут видит mobile-режим
    по тому же признаку, что и в проде (фабрика возвращает именно этот тип).
    """

    def __init__(self, acc, ret):
        self.acc = acc
        self.mode = "mobile"
        self._ret = ret
        self.submit_calls = []

    async def submit_response(self, vid, letter_max_length=None):
        self.submit_calls.append((vid, letter_max_length))
        return self._ret


class ExplodingMobileClient(FallbackHHClient):
    """FallbackHHClient, чей submit_response кидает исключение."""

    def __init__(self):
        self.mode = "mobile"

    async def submit_response(self, vid, letter_max_length=None):
        raise RuntimeError("mobile boom")


class FakeWebClient:
    """Клиент без FallbackHHClient-признака — роут считает его web-режимом."""

    def __init__(self, acc):
        self.acc = acc
        self.submit_calls = []

    async def submit_response(self, vid, letter_max_length=None):
        self.submit_calls.append(vid)
        raise AssertionError("submit_response не должен вызываться в web-ветке")


class _WebFlowMarker:
    """Замена aiohttp: фиксирует ЛЮБОЕ обращение к web-form flow и падает.

    Если роут попытался войти в web-flow (aiohttp.ClientSession/FormData/...) —
    это видно по calls, а RuntimeError перехватывает except роута, и тест
    получает управляемый {"status": "error"} без реального HTTP.
    """

    def __init__(self, calls):
        self._calls = calls

    def __getattr__(self, name):
        self._calls.append(name)
        raise RuntimeError("web-flow reached")


def _async_value(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


@pytest.fixture
def bot_stub(monkeypatch):
    """Подменяет bot-хелперы и add_applied шпионами (без диска и реального bot'а)."""
    acc = dict(ACC)
    state = types.SimpleNamespace(sent=0, questionnaire_sent=0, short="a1", color="green")
    logs: list = []
    applied: list = []
    monkeypatch.setattr(bot, "_get_apply_acc", lambda idx: dict(acc))
    monkeypatch.setattr(bot, "_get_apply_state", lambda idx: state)
    monkeypatch.setattr(
        bot, "_add_log",
        lambda short, color, msg, level="info", neg_id="": logs.append((short, color, msg, level)),
    )
    monkeypatch.setattr(apply_route, "add_applied",
                        lambda name, vid, info=None: applied.append((name, vid)))
    return {"acc": acc, "state": state, "logs": logs, "applied": applied}


@pytest.fixture
def no_aiohttp(monkeypatch):
    """Гарантия: mobile-ветка НЕ ходит в web-form aiohttp."""
    calls: list = []
    monkeypatch.setattr(apply_route, "aiohttp", _WebFlowMarker(calls))
    return calls


# ── 1. Чистый маппер: все 6 result'ов ────────────────────────────────────────


def test_mapper_sent():
    resp = _result_to_response("sent", {}, "123")
    assert resp == {"status": "sent", "vacancy_id": "123",
                    "message": "Отклик успешно отправлен ✅"}


def test_mapper_limit():
    resp = _result_to_response("limit", {}, "123")
    assert resp == {"status": "limit", "vacancy_id": "123",
                    "message": "Достигнут дневной лимит откликов"}


def test_mapper_already():
    resp = _result_to_response("already", {}, "123")
    assert resp == {"status": "already", "vacancy_id": "123",
                    "message": "Отклик на эту вакансию уже был отправлен"}


def test_mapper_test_required():
    questions = [{"field": "task_1_text", "type": "textarea"}]
    resp = _result_to_response("test", {}, "123", questions=questions, letter="hi")
    assert resp == {
        "status": "test_required",
        "vacancy_id": "123",
        "questions": questions,
        "letter": "hi",
        "message": "Вакансия требует опрос (1 вопросов)",
    }


def test_mapper_auth_error():
    resp = _result_to_response("auth_error", {}, "123")
    assert resp == {"status": "error", "vacancy_id": "123",
                    "message": "⚠️ Куки протухли — обновите в настройках"}


def test_mapper_error_message_priority():
    """error → message из info: error_type > exception > raw > дефолт."""
    assert _result_to_response("error", {"error_type": "captcha", "exception": "x", "raw": "y"},
                               "1")["message"] == "captcha"
    assert _result_to_response("error", {"exception": "boom", "raw": "y"}, "1")["message"] == "boom"
    assert _result_to_response("error", {"raw": "<html>err</html>"}, "1")["message"] == "<html>err</html>"
    assert _result_to_response("error", {}, "1")["message"] == "Ошибка отклика"


def test_mapper_unknown_result_is_error():
    resp = _result_to_response("weird-new-status", {}, "123")
    assert resp["status"] == "error"
    assert resp["message"] == "Ошибка отклика"


# ── 2. Mobile-ветка без answers: фабрика + bookkeeping, без web-form ─────────


def test_mobile_sent_uses_client_and_bookkeeping(monkeypatch, bot_stub, no_aiohttp):
    client = FakeMobileClient(bot_stub["acc"], ("sent", {"title": "Vacancy"}))
    seen_acc: dict = {}
    monkeypatch.setattr(apply_route, "get_client", lambda acc: (seen_acc.update(acc=acc), client)[1])

    resp = _run(api_apply_submit({"account_idx": 0, "vacancy_id": "777"}))

    assert resp == {"status": "sent", "vacancy_id": "777",
                    "message": "Отклик успешно отправлен ✅"}
    # submit_response вызван ровно один раз, letter_max_length не передавался
    assert client.submit_calls == [("777", None)]
    # в web-form aiohttp не ходили
    assert no_aiohttp == []
    # клиент получил acc со смерженным letter (letter в body не задан → из acc)
    assert seen_acc["acc"]["letter"] == "cover letter"
    # bookkeeping: sent += 1, questionnaire_sent НЕ тронут
    assert bot_stub["state"].sent == 1
    assert bot_stub["state"].questionnaire_sent == 0
    assert bot_stub["applied"] == [("acc1", "777")]
    assert bot_stub["logs"] == [("a1", "green", "\U0001f4dd Ручной отклик (mobile): 777", "success")]


def test_mobile_sent_with_custom_letter_merges_into_client_acc(monkeypatch, bot_stub, no_aiohttp):
    client = FakeMobileClient(bot_stub["acc"], ("sent", {}))
    seen_acc: dict = {}
    monkeypatch.setattr(apply_route, "get_client", lambda acc: (seen_acc.update(acc=acc), client)[1])

    resp = _run(api_apply_submit({"account_idx": 0, "vacancy_id": "777", "letter": "custom"}))

    assert resp["status"] == "sent"
    # get_client увидел acc ПОСЛЕ мержа letter — submit_response возьмёт его сам
    assert seen_acc["acc"]["letter"] == "custom"


@pytest.mark.parametrize("result,expected", [
    ("limit", {"status": "limit", "vacancy_id": "777",
               "message": "Достигнут дневной лимит откликов"}),
    ("already", {"status": "already", "vacancy_id": "777",
                 "message": "Отклик на эту вакансию уже был отправлен"}),
    ("auth_error", {"status": "error", "vacancy_id": "777",
                    "message": "⚠️ Куки протухли — обновите в настройках"}),
])
def test_mobile_refusals_no_bookkeeping(monkeypatch, bot_stub, no_aiohttp, result, expected):
    client = FakeMobileClient(bot_stub["acc"], (result, {}))
    monkeypatch.setattr(apply_route, "get_client", lambda acc: client)

    resp = _run(api_apply_submit({"account_idx": 0, "vacancy_id": "777"}))

    assert resp == expected
    assert client.submit_calls == [("777", None)]
    assert no_aiohttp == []
    # отказы НЕ bookkeeping'ятся
    assert bot_stub["state"].sent == 0
    assert bot_stub["state"].questionnaire_sent == 0
    assert bot_stub["applied"] == []
    assert bot_stub["logs"] == []


def test_mobile_error_result_message_from_info(monkeypatch, bot_stub, no_aiohttp):
    client = FakeMobileClient(bot_stub["acc"], ("error", {"exception": "timeout"}))
    monkeypatch.setattr(apply_route, "get_client", lambda acc: client)

    resp = _run(api_apply_submit({"account_idx": 0, "vacancy_id": "777"}))

    assert resp == {"status": "error", "vacancy_id": "777", "message": "timeout"}
    assert bot_stub["applied"] == []


def test_mobile_test_result_fetches_questionnaire(monkeypatch, bot_stub, no_aiohttp):
    """result="test" → анкеты нет, но она обязательна: возвращаем вопросы
    существующим _fetch_questionnaire_data (как api_apply_check)."""
    client = FakeMobileClient(bot_stub["acc"], ("test", {}))
    monkeypatch.setattr(apply_route, "get_client", lambda acc: client)
    qdata = {"questions": [{"field": "task_1_text", "type": "textarea", "text": "?",
                            "options": [], "suggested": ""}]}
    monkeypatch.setattr(apply_route, "_fetch_questionnaire_data", _async_value(qdata))

    resp = _run(api_apply_submit({"account_idx": 0, "vacancy_id": "777"}))

    assert resp == {
        "status": "test_required",
        "vacancy_id": "777",
        "questions": qdata["questions"],
        "letter": "cover letter",
        "message": "Вакансия требует опрос (1 вопросов)",
    }
    assert no_aiohttp == []  # вопросы пришли из подменённого _fetch_questionnaire_data
    assert bot_stub["state"].sent == 0
    assert bot_stub["applied"] == []


def test_mobile_submit_exception_returns_error(monkeypatch, bot_stub, no_aiohttp):
    monkeypatch.setattr(apply_route, "get_client", lambda acc: ExplodingMobileClient())

    resp = _run(api_apply_submit({"account_idx": 0, "vacancy_id": "777"}))

    assert resp == {"status": "error", "message": "mobile boom"}
    assert no_aiohttp == []
    assert bot_stub["state"].sent == 0


# ── 3. Ветки, где сохраняется старый web-form flow ───────────────────────────


def test_mobile_with_answers_stays_on_web_flow(monkeypatch, bot_stub):
    """Анкета (answers непустой) — территория web-flow даже для mobile-аккаунта."""
    client = FakeMobileClient(bot_stub["acc"], ("sent", {}))
    monkeypatch.setattr(apply_route, "get_client", lambda acc: client)
    web_calls: list = []
    monkeypatch.setattr(apply_route, "aiohttp", _WebFlowMarker(web_calls))

    resp = _run(api_apply_submit(
        {"account_idx": 0, "vacancy_id": "777", "answers": {"task_1_text": "да"}}))

    assert client.submit_calls == []          # submit_response НЕ вызван
    assert web_calls                          # web-form flow реально начался
    assert resp == {"status": "error", "message": "web-flow reached"}


def test_web_mode_stays_on_web_flow(monkeypatch, bot_stub):
    """get_client вернул не-FallbackHHClient → старый web-form flow."""
    fake_web = FakeWebClient(dict(ACC))
    monkeypatch.setattr(apply_route, "get_client", lambda acc: fake_web)
    web_calls: list = []
    monkeypatch.setattr(apply_route, "aiohttp", _WebFlowMarker(web_calls))

    resp = _run(api_apply_submit({"account_idx": 0, "vacancy_id": "777"}))

    assert fake_web.submit_calls == []        # submit_response НЕ вызван
    assert web_calls                          # web-form flow реально начался
    assert resp == {"status": "error", "message": "web-flow reached"}
