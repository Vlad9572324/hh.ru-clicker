"""Тесты делегатов WebHHClient (Phase 0, finding P2).

WebHHClient — чистый адаптер: каждый метод подставляет self.acc первым
аргументом в целевую функцию модуля (hh_chat / hh_apply / hh_negotiations /
hh_resume / oauth) и возвращает результат без преобразования.

Проверяется для ВСЕХ делегатов (таблицы ниже построены по полному списку
методов класса, см. guard-тест test_table_covers_all_web_client_methods):
- ровно 1 вызов цели;
- первый аргумент is self.acc (identity, не копия);
- остальные positional-аргументы проброшены как есть, kwargs не используются;
- возвращённое значение проброшено без преобразования (is sentinel);
- дефолтные параметры метода пробрасываются в цель как positional;
- async-делегаты реально await'ятся (pytest-asyncio нет — asyncio.run
  в отдельном потоке через _run_coro, см. ниже);
- исключения проходят насквозь без преобразования (тот же объект);
- полнота реализации ABC у WebHHClient и MobileHHClient.

Стиль monkeypatch'а — как в test_hh_client_abstraction.py: патчим атрибуты
МОДУЛЕЙ (WebHHClient импортирует модули, а не функции).
"""
import asyncio
import concurrent.futures

import pytest

from app import hh_api, hh_apply, hh_chat, hh_negotiations, hh_resume, oauth
from app.hh_client import HHClient
from app.hh_client_mobile import MobileHHClient
from app.hh_client_web import WebHHClient

# ---------------------------------------------------------------------------
# Таблицы делегатов
#
# Формат строки SYNC_DELEGATES:
#   (имя метода WebHHClient, модуль-цель, имя функции-цели в модуле,
#    аргументы «полного» вызова метода (позиционные, без self.acc),
#    проверка дефолтов: None | (аргументы вызова, ожидаемый проброс без acc))
# ---------------------------------------------------------------------------
SYNC_DELEGATES = [
    ("search_vacancies", hh_api, "fetch_hh_vacancies",
     ("python", 2, 40, 1, {"experience": "between1And3"}, 5),
     (("python",), ("python", 113, 20, 0, None, 20))),
    # --- Группа A: переговоры / чат ---
    ("fetch_negotiations", hh_negotiations, "fetch_hh_negotiations_stats",
     (7,), ((), (20,))),
    ("fetch_thread", hh_chat, "fetch_negotiation_thread",
     ("neg1",), None),
    ("send_message", hh_chat, "send_negotiation_message",
     ("neg1", "привет", "t7"), (("neg1", "привет"), ("neg1", "привет", ""))),
    ("fetch_chat_list", hh_chat, "_fetch_chat_list",
     (3,), ((), (5,))),
    ("fetch_chat_history", hh_chat, "_fetch_chat_history",
     ("c1", 50), (("c1",), ("c1", 20))),
    ("fetch_quick_replies", hh_chat, "fetch_quick_replies",
     ("c1", "m1"), None),
    ("send_participant_action", hh_chat, "send_participant_action",
     ("c1", "NONE"), (("c1",), ("c1", "TYPING"))),
    ("mark_chat_read", hh_chat, "mark_chat_read",
     ("c1", "m9"), None),
    ("fetch_possible_offers", hh_negotiations, "fetch_hh_possible_offers",
     (), None),
    ("auto_decline_discards", hh_negotiations, "auto_decline_discards",
     (), None),
    ("fetch_negotiations_metadata", hh_negotiations, "fetch_negotiations_metadata",
     (), None),
    ("fetch_employer_rating", hh_negotiations, "fetch_employer_rating",
     ("emp1",), None),
    ("fetch_employer_id_for_vacancy", hh_negotiations, "fetch_employer_id_for_vacancy",
     ("v1",), None),
    ("fetch_vacancy_owner_hr_hhid", hh_negotiations, "fetch_vacancy_owner_hr_hhid",
     ("v1",), None),
    # --- Группа B: отклики (sync-часть; async-делегаты — в ASYNC_DELEGATES) ---
    ("check_vacancy_before_apply", hh_apply, "_check_vacancy_before_apply",
     ("v1",), None),
    ("check_limit", hh_apply, "check_limit",
     (), None),
    ("touch_resume", hh_apply, "touch_resume",
     (), None),
    ("fetch_related_vacancies", hh_apply, "fetch_related_vacancies",
     ("v1", 4), (("v1",), ("v1", 1))),
    # --- Группа C: резюме ---
    ("fetch_stats", hh_resume, "fetch_resume_stats",
     (), None),
    ("fetch_resume", hh_resume, "fetch_resume_text",
     (), None),
    ("fetch_resume_view_history", hh_resume, "fetch_resume_view_history",
     (5,), ((), (50,))),
    ("fetch_resume_views_aggregate", hh_resume, "fetch_resume_views_aggregate",
     (), None),
    ("analyze_resume", hh_resume, "_analyze_resume",
     (["python", "asyncio"],), ((), (None,))),
    ("edit_resume_field", hh_resume, "_edit_resume_field",
     ("rh1", {"first_name": "X"}), None),
    ("set_job_search_status", hh_resume, "set_job_search_status",
     ("activeVacancy",), None),
    ("fetch_account_diagnostics", hh_resume, "fetch_account_diagnostics",
     (), None),
    # --- Группа E: OAuth-extras (Bearer api.hh.ru, живут в app/oauth.py) ---
    ("fetch_saved_vacancy_searches", oauth, "fetch_saved_vacancy_searches",
     (), None),
    ("fetch_favorited_vacancies", oauth, "fetch_favorited_vacancies",
     (), None),
    ("fetch_blacklisted_vacancies", oauth, "fetch_blacklisted_vacancies",
     (), None),
    ("fetch_vacancy_details", oauth, "fetch_vacancy_details",
     ("v1",), None),
    ("fetch_negotiations_today_count", oauth, "fetch_negotiations_today_count",
     (), None),
    ("fetch_negotiations_statistic", oauth, "fetch_negotiations_statistic",
     (), None),
    ("fetch_resume_status", oauth, "fetch_resume_status",
     (), None),
    # цель — oauth.fetch_employer_rating (не путать с hh_negotiations.fetch_employer_rating)
    ("fetch_employer_rating_oauth", oauth, "fetch_employer_rating",
     ("emp1",), None),
]

# Формат строки ASYNC_DELEGATES:
#   (имя метода WebHHClient, имя функции-цели в app.hh_apply,
#    аргументы «полного» вызова, (аргументы дефолтного вызова, ожидаемый проброс без acc))
ASYNC_DELEGATES = [
    ("submit_response", "send_response_async",
     ("v1", 500), (("v1",), ("v1", None))),
    ("fill_questionnaire", "fill_and_submit_questionnaire",
     ("v1", "Разработчик", "Ромашка"), (("v1",), ("v1", "", ""))),
]

# Представители разных модулей для теста проброса исключений
# (метод, модуль, цель, аргументы, async ли).
EXCEPTION_CASES = [
    ("fetch_thread", hh_chat, "fetch_negotiation_thread", ("neg1",), False),
    ("analyze_resume", hh_resume, "_analyze_resume", (), False),
    ("fetch_vacancy_details", oauth, "fetch_vacancy_details", ("v1",), False),
    ("submit_response", hh_apply, "send_response_async", ("v1",), True),
]


def _ids_sync(rows):
    return [r[0] for r in rows]


def _run_coro(coro):
    """Запускает корутину через asyncio.run в ОТДЕЛЬНОМ потоке.

    Устойчиво к ситуации, когда в текущем (главном) потоке уже есть
    «running» event loop: pytest-playwright (e2e) держит session-scoped
    Playwright-инстанс, чей loop считается активным в главном потоке до
    конца сессии, и прямой asyncio.run() падает с
    RuntimeError: asyncio.run() cannot be called from a running event loop.
    Новый поток гарантированно не имеет активного loop'а.

    Исключение из корутины пробрасывается из future.result() тем же
    объектом (без обёртки) — identity-проверки в тестах сохраняются.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


# ---------------------------------------------------------------------------
# Guard: таблица покрывает ВСЕ публичные методы WebHHClient (без хардкода
# числа делегатов — при добавлении/переименовании метода тест упадёт).
# ---------------------------------------------------------------------------

def test_table_covers_all_web_client_methods():
    defined = {
        name
        for name, value in vars(WebHHClient).items()
        if not name.startswith("_") and callable(value)
    }
    covered = (
        {row[0] for row in SYNC_DELEGATES}
        | {row[0] for row in ASYNC_DELEGATES}
        # Эти методы — не делегаты: fetch_counters кидает NotImplementedError,
        # workflow-event имеет безопасную web-заглушку.
        | {"fetch_counters", "send_workflow_event"}
    )
    assert covered == defined


# ---------------------------------------------------------------------------
# Sync-делегаты: проброс аргументов и результата
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method_name,module,target_name,args,default_check",
    SYNC_DELEGATES,
    ids=_ids_sync(SYNC_DELEGATES),
)
def test_sync_delegate_forwards_args_and_returns_sentinel(
    monkeypatch, method_name, module, target_name, args, default_check
):
    acc = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
    sentinel = object()
    calls = []

    def fake(*fwd_args, **fwd_kwargs):
        calls.append((fwd_args, fwd_kwargs))
        return sentinel

    monkeypatch.setattr(module, target_name, fake)

    result = getattr(WebHHClient(acc), method_name)(*args)

    if method_name == "fetch_resume":
        assert result == {"text": sentinel, "source": "web"}
    else:
        assert result is sentinel  # возвращено без преобразования
    assert len(calls) == 1
    fwd_args, fwd_kwargs = calls[0]
    assert fwd_args[0] is acc  # тот же объект, не копия
    assert fwd_args[1:] == args
    assert fwd_kwargs == {}  # делегаты ходят только positional


@pytest.mark.parametrize(
    "method_name,module,target_name,default_call,expected",
    [row[:3] + row[4] for row in SYNC_DELEGATES if row[4] is not None],
    ids=[row[0] for row in SYNC_DELEGATES if row[4] is not None],
)
def test_sync_delegate_default_args_forwarded(
    monkeypatch, method_name, module, target_name, default_call, expected
):
    acc = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
    calls = []

    def fake(*fwd_args, **fwd_kwargs):
        calls.append((fwd_args, fwd_kwargs))
        return {}

    monkeypatch.setattr(module, target_name, fake)

    getattr(WebHHClient(acc), method_name)(*default_call)

    assert len(calls) == 1
    fwd_args, fwd_kwargs = calls[0]
    assert fwd_args[0] is acc
    # дефолт метода проброшен в цель как positional-значение
    assert fwd_args[1:] == expected
    assert fwd_kwargs == {}


# ---------------------------------------------------------------------------
# Async-делегаты: await реально происходит (fake async записывает вызов),
# аргументы и результат пробрасываются.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method_name,target_name,args,default_check",
    ASYNC_DELEGATES,
    ids=[r[0] for r in ASYNC_DELEGATES],
)
def test_async_delegate_awaited_and_forwards(
    monkeypatch, method_name, target_name, args, default_check
):
    acc = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
    sentinel = ("applied", "payload")
    calls = []

    async def fake(*fwd_args, **fwd_kwargs):
        calls.append((fwd_args, fwd_kwargs))
        return sentinel

    monkeypatch.setattr(hh_apply, target_name, fake)

    result = _run_coro(getattr(WebHHClient(acc), method_name)(*args))

    assert len(calls) == 1  # запись есть → await состоялся
    assert result is sentinel
    fwd_args, fwd_kwargs = calls[0]
    assert fwd_args[0] is acc
    assert fwd_args[1:] == args
    assert fwd_kwargs == {}


@pytest.mark.parametrize(
    "method_name,target_name,default_call,expected",
    [row[0:2] + row[3] for row in ASYNC_DELEGATES],
    ids=[row[0] for row in ASYNC_DELEGATES],
)
def test_async_delegate_default_args_forwarded(
    monkeypatch, method_name, target_name, default_call, expected
):
    acc = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
    calls = []

    async def fake(*fwd_args, **fwd_kwargs):
        calls.append((fwd_args, fwd_kwargs))
        return ()

    monkeypatch.setattr(hh_apply, target_name, fake)

    _run_coro(getattr(WebHHClient(acc), method_name)(*default_call))

    assert len(calls) == 1
    fwd_args, fwd_kwargs = calls[0]
    assert fwd_args[0] is acc
    assert fwd_args[1:] == expected
    assert fwd_kwargs == {}


# ---------------------------------------------------------------------------
# Исключения проходят насквозь без преобразования (тот же объект).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method_name,module,target_name,args,is_async",
    EXCEPTION_CASES,
    ids=[r[0] for r in EXCEPTION_CASES],
)
def test_delegate_exception_passes_through_unchanged(
    monkeypatch, method_name, module, target_name, args, is_async
):
    acc = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
    boom = ValueError("boom")

    if is_async:
        async def fake(*fwd_args, **fwd_kwargs):
            raise boom
    else:
        def fake(*fwd_args, **fwd_kwargs):
            raise boom

    monkeypatch.setattr(module, target_name, fake)

    if is_async:
        with pytest.raises(ValueError, match="boom") as excinfo:
            _run_coro(getattr(WebHHClient(acc), method_name)(*args))
    else:
        with pytest.raises(ValueError, match="boom") as excinfo:
            getattr(WebHHClient(acc), method_name)(*args)

    assert excinfo.value is boom  # тот же объект, не обёртка/преобразование


# ---------------------------------------------------------------------------
# Полнота реализации ABC
# ---------------------------------------------------------------------------

def test_web_client_implements_full_abc():
    assert WebHHClient.__abstractmethods__ == frozenset()


def test_mobile_client_implements_full_abc():
    assert MobileHHClient.__abstractmethods__ == frozenset()


def test_subclass_missing_one_method_cannot_be_instantiated():
    # Возвращаем одному методу пометку abstractmethod → класс снова абстрактный.
    class MissingFetchThread(WebHHClient):
        fetch_thread = HHClient.fetch_thread

    assert MissingFetchThread.__abstractmethods__ == frozenset({"fetch_thread"})
    with pytest.raises(TypeError):
        MissingFetchThread({"name": "a1", "cookies": {}, "resume_hash": "rh1"})


# ---------------------------------------------------------------------------
# fetch_counters: web — NotImplementedError (нет аналога GET /me),
# mobile без токена — {} (конвенция app/oauth.py).
# ---------------------------------------------------------------------------

def test_web_fetch_counters_not_implemented():
    acc = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
    with pytest.raises(NotImplementedError):
        WebHHClient(acc).fetch_counters()


def test_mobile_fetch_counters_without_token_returns_empty(monkeypatch):
    acc = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: None)
    assert MobileHHClient(acc).fetch_counters() == {}
