"""Тесты mobile-анкеты (Phase 3): app/mobile_questionnaire.py и
MobileHHClient.fill_questionnaire.

Факт из разбора APK (ru.hh.android v26.28.1): нативного Retrofit-endpoint'а
для анкет/опросов НЕТ — официальное приложение при error_type=test_required
открывает WEB-страницу анкеты (applicant/vacancy_response) в webview.
Решение Phase 3 — делегирование в web-flow
hh_apply.fill_and_submit_questionnaire (семантика официального приложения).

Проверяется:
- модуль mobile_questionnaire.fill_questionnaire делегирует в
  hh_apply.fill_and_submit_questionnaire: аргументы (acc, vid,
  vacancy_title, company) пробрасываются позиционно, результат
  возвращается как есть;
- клиентский метод MobileHHClient.fill_questionnaire делегирует в модуль
  mobile_questionnaire (подставляя self.acc первым аргументом);
- NotImplementedError больше НЕ кидается — метод реально отрабатывает
  (smoke), дефолтные vacancy_title/company пробрасываются как "".

Стиль monkeypatch'а — как в test_hh_client_delegates.py: патчим атрибуты
МОДУЛЕЙ (делегаты вызывают функции через атрибут модуля). Async-вызовы —
asyncio.run в отдельном потоке (_run_coro): pytest-playwright (tests/e2e/)
может держать «running» loop в главном потоке до конца сессии.
"""
import asyncio
import concurrent.futures

from app import hh_apply, mobile_questionnaire
from app.hh_client_mobile import MobileHHClient

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}


def _run_coro(coro):
    # pytest-playwright (tests/e2e/) держит asyncio-loop «running» в главном
    # потоке до конца сессии, поэтому прямой asyncio.run() падает с
    # RuntimeError. Запускаем корутину в отдельном потоке — там лупа нет.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


def test_module_delegates_to_hh_apply(monkeypatch):
    """mobile_questionnaire.fill_questionnaire →
    hh_apply.fill_and_submit_questionnaire: аргументы позиционно,
    результат без преобразования."""
    sentinel = ("sent", {"ok": True})
    calls = []

    async def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return sentinel

    monkeypatch.setattr(hh_apply, "fill_and_submit_questionnaire", fake)

    result = _run_coro(
        mobile_questionnaire.fill_questionnaire(ACC, "v1", "Заголовок", "Ромашка"))

    assert result is sentinel  # возвращено как есть
    assert len(calls) == 1
    fwd_args, fwd_kwargs = calls[0]
    assert fwd_args == (ACC, "v1", "Заголовок", "Ромашка")
    assert fwd_args[0] is ACC  # тот же объект, не копия
    assert fwd_kwargs == {}  # делегирование только позиционное


def test_client_method_delegates_to_module(monkeypatch):
    """MobileHHClient.fill_questionnaire →
    mobile_questionnaire.fill_questionnaire (self.acc первым аргументом)."""
    sentinel = ("test", {})
    calls = []

    async def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return sentinel

    monkeypatch.setattr(mobile_questionnaire, "fill_questionnaire", fake)

    result = _run_coro(MobileHHClient(ACC).fill_questionnaire("v2", "T", "C"))

    assert result is sentinel
    assert len(calls) == 1
    fwd_args, fwd_kwargs = calls[0]
    assert fwd_args == (ACC, "v2", "T", "C")
    assert fwd_args[0] is ACC
    assert fwd_kwargs == {}


def test_fill_questionnaire_no_longer_raises_not_implemented(monkeypatch):
    """Smoke: NotImplementedError больше не кидается — полный путь
    клиент → модуль → hh_apply отрабатывает; дефолтные vacancy_title и
    company пробрасываются как пустые строки."""
    calls = []

    async def fake(*args, **kwargs):
        calls.append(args)
        return ("sent", {})

    monkeypatch.setattr(hh_apply, "fill_and_submit_questionnaire", fake)

    result = _run_coro(MobileHHClient(ACC).fill_questionnaire("v1"))

    assert result == ("sent", {})
    assert calls == [(ACC, "v1", "", "")]
