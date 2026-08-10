"""Интеграционные тесты Phase 3: fallback-политика (401/403/5xx → web)
сквозь РЕАЛЬНЫЙ FallbackHHClient из фабрики get_client.

Проверяемый путь: фабрика (app/hh_client_factory.py) для аккаунта с
mode="mobile" возвращает FallbackHHClient(MobileHHClient, WebHHClient) →
запрос уходит в api.hh.ru (перехвачен `responses`) → при fallback-статусе
(0/401/403/5xx, см. app.hh_mobile_transport.is_fallback_status) или
NotImplementedError вызов прозрачно повторяется через web-flow.

Web-цели патчатся как атрибуты МОДУЛЯ app.hh_apply (WebHHClient импортирует
модули, а не функции — конвенция tests/test_hh_client_delegates.py):
- submit_response            → hh_apply.send_response_async            (async)
- fill_questionnaire         → hh_apply.fill_and_submit_questionnaire  (async)
- check_vacancy_before_apply → hh_apply._check_vacancy_before_apply
- check_limit                → hh_apply.check_limit
- touch_resume               → hh_apply.touch_resume
- fetch_related_vacancies    → hh_apply.fetch_related_vacancies

Никаких живых запросов: HTTP перехвачен библиотекой `responses`,
OAuth-токен подменён monkeypatch app.oauth._obtain_oauth_token.
"""
import asyncio
import concurrent.futures

import pytest
import responses

from app import hh_apply, oauth
from app.hh_client_factory import get_client
from app.hh_client_fallback import FallbackHHClient
from app.hh_client_mobile import MobileHHClient
from app.hh_client_web import WebHHClient
from app.hh_mobile_transport import MOBILE_BASE

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1",
       "mode": "mobile", "letter": "здравствуйте"}

# Mobile-endpoint'ы Phase 3 (api.hh.ru) — по реализациям app/mobile_*.py.
URL_NEGOTIATIONS = MOBILE_BASE + "/negotiations"
URL_DATA_INCONSISTENCY = MOBILE_BASE + "/resume_profile/data_inconsistency"
URL_STATISTIC = MOBILE_BASE + "/negotiations_statistic/mine"
URL_PUBLISH = MOBILE_BASE + "/resumes/rh1/publish"
URL_POSSIBLE_OFFERS = MOBILE_BASE + "/vacancies/possible_job_offers"


def _run_coro(coro):
    # Тот же приём, что в tests/test_hh_client_delegates.py: pytest-playwright
    # (e2e) может держать «running» loop в главном потоке, поэтому asyncio.run()
    # исполняем в отдельном потоке. Исключение из корутины пробрасывается тем
    # же объектом.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


@pytest.fixture
def oauth_token(monkeypatch):
    """Bearer-токен добывается через app.oauth._obtain_oauth_token —
    подменяем, чтобы не идти в реальный OAuth-flow."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")


@pytest.fixture
def client(oauth_token):
    """Реальный клиент из фабрики для mobile-аккаунта + проверка обвязки:
    mode="mobile" → FallbackHHClient(MobileHHClient, WebHHClient)."""
    client = get_client(ACC)
    assert isinstance(client, FallbackHHClient)
    assert isinstance(client.mobile, MobileHHClient)
    assert isinstance(client.web, WebHHClient)
    assert client.mode == "mobile"
    return client


def _patch_web(monkeypatch, name, fake):
    """Подменить web-цель в модуле app.hh_apply и вернуть список вызовов."""
    calls = []

    def recorder(*args, **kwargs):
        calls.append((args, kwargs))
        return fake(*args, **kwargs)

    async def async_recorder(*args, **kwargs):
        calls.append((args, kwargs))
        return await fake(*args, **kwargs)

    if asyncio.iscoroutinefunction(fake):
        monkeypatch.setattr(hh_apply, name, async_recorder)
    else:
        monkeypatch.setattr(hh_apply, name, recorder)
    return calls


def _assert_single_mobile_call(expected_url, expected_status):
    """Ровно один HTTP-запрос: попытка mobile с ожидаемым статусом
    (web-fallback ходит в подменённые fake'и, а не в сеть)."""
    assert len(responses.calls) == 1
    call = responses.calls[0]
    assert call.request.url.split("?")[0] == expected_url
    assert call.response.status_code == expected_status


# ── Фабрика: mobile-аккаунт → FallbackHHClient(MobileHHClient, WebHHClient) ─


def test_factory_mobile_wiring(oauth_token):
    client = get_client(ACC)
    assert isinstance(client, FallbackHHClient)
    assert isinstance(client.mobile, MobileHHClient)
    assert isinstance(client.web, WebHHClient)
    assert client.mode == "mobile"


# ── submit_response: 401 → web; 400 limit_exceeded → НЕ web ─────────────────


@responses.activate
def test_submit_response_mobile_401_falls_back_to_web(monkeypatch, client):
    responses.add(responses.POST, URL_NEGOTIATIONS,
                  json={"code": "token_expired"}, status=401)

    async def fake_send(acc, vid, letter_max_length=None):
        return ("sent", {"topic_id": "web-topic-1"})

    web_calls = _patch_web(monkeypatch, "send_response_async", fake_send)

    result = _run_coro(client.submit_response("v123"))

    assert result == ("sent", {"topic_id": "web-topic-1"})
    assert len(web_calls) == 1
    fwd_args, fwd_kwargs = web_calls[0]
    assert fwd_args[0] is ACC
    assert fwd_args[1] == "v123"
    assert fwd_kwargs == {}
    _assert_single_mobile_call(URL_NEGOTIATIONS, 401)


@responses.activate
def test_submit_response_400_limit_exceeded_not_retried_via_web(
        monkeypatch, client):
    """400 — НЕ fallback-статус: mobile сам разбирает бизнес-код
    limit_exceeded и возвращает ("limit", ...); web-flow не вызывается."""
    responses.add(responses.POST, URL_NEGOTIATIONS,
                  json={"code": "limit_exceeded"}, status=400)

    async def fake_send(acc, vid, letter_max_length=None):
        return ("sent", {})

    web_calls = _patch_web(monkeypatch, "send_response_async", fake_send)

    result = _run_coro(client.submit_response("v123"))

    assert result[0] == "limit"
    assert result[1].get("error_type") == "limit_exceeded"
    assert web_calls == []  # web-flow не трогали
    _assert_single_mobile_call(URL_NEGOTIATIONS, 400)


# ── check_vacancy_before_apply: 401/403 → web ────────────────────────────────


@pytest.mark.parametrize("status", [401, 403])
@responses.activate
def test_check_vacancy_before_apply_fallback_status_retries_web(
        monkeypatch, client, status):
    responses.add(responses.GET, URL_DATA_INCONSISTENCY,
                  json={"code": "forbidden"}, status=status)

    def fake_precheck(acc, vid):
        return {"ok": True, "missing": []}

    web_calls = _patch_web(monkeypatch, "_check_vacancy_before_apply",
                           fake_precheck)

    result = client.check_vacancy_before_apply("v7")

    assert result == {"ok": True, "missing": []}
    assert len(web_calls) == 1
    assert web_calls[0][0] == (ACC, "v7")
    _assert_single_mobile_call(URL_DATA_INCONSISTENCY, status)


# ── check_limit: 401/500 → web ───────────────────────────────────────────────


@pytest.mark.parametrize("status", [401, 500])
@responses.activate
def test_check_limit_fallback_status_retries_web(monkeypatch, client, status):
    responses.add(responses.GET, URL_STATISTIC,
                  json={"code": "unavailable"}, status=status)

    def fake_check_limit(acc):
        return True  # web-семантика: True = лимит активен

    web_calls = _patch_web(monkeypatch, "check_limit", fake_check_limit)

    result = client.check_limit()

    assert result is True  # возвращён результат web-flow
    assert len(web_calls) == 1
    assert web_calls[0][0] == (ACC,)
    _assert_single_mobile_call(URL_STATISTIC, status)


# ── touch_resume: 401 → web; 400 → NotImplementedError → web ─────────────────


@responses.activate
def test_touch_resume_mobile_401_falls_back_to_web(monkeypatch, client):
    responses.add(responses.POST, URL_PUBLISH,
                  json={"code": "token_expired"}, status=401)

    def fake_touch(acc):
        return True, "резюме поднято (web)"

    web_calls = _patch_web(monkeypatch, "touch_resume", fake_touch)

    result = client.touch_resume()

    assert result == (True, "резюме поднято (web)")
    assert len(web_calls) == 1
    assert web_calls[0][0] == (ACC,)
    _assert_single_mobile_call(URL_PUBLISH, 401)


@responses.activate
def test_touch_resume_400_not_implemented_goes_to_web(monkeypatch, client):
    """Прочие 4xx (400) в mobile-модуле поднимают NotImplementedError —
    обёртка ловит его и прозрачно повторяет через web hh_apply.touch_resume."""
    responses.add(responses.POST, URL_PUBLISH,
                  json={"code": "need_hhpro"}, status=400)

    def fake_touch(acc):
        return True, "резюме поднято (web)"

    web_calls = _patch_web(monkeypatch, "touch_resume", fake_touch)

    result = client.touch_resume()

    assert result == (True, "резюме поднято (web)")
    assert len(web_calls) == 1
    _assert_single_mobile_call(URL_PUBLISH, 400)


# ── fetch_related_vacancies: 401 → web ───────────────────────────────────────


@responses.activate
def test_fetch_related_vacancies_mobile_401_falls_back_to_web(
        monkeypatch, client):
    responses.add(responses.GET, URL_POSSIBLE_OFFERS,
                  json={"code": "token_expired"}, status=401)

    def fake_related(acc, seed_vid, max_pages=1):
        return ["v2", "v3"]

    web_calls = _patch_web(monkeypatch, "fetch_related_vacancies",
                           fake_related)

    result = client.fetch_related_vacancies("v1")

    assert result == ["v2", "v3"]
    assert len(web_calls) == 1
    fwd_args, fwd_kwargs = web_calls[0]
    assert fwd_args[0] is ACC
    assert fwd_args[1] == "v1"
    assert fwd_kwargs == {}
    _assert_single_mobile_call(URL_POSSIBLE_OFFERS, 401)


# ── fill_questionnaire: делегирование в web-flow без HTTP в api.hh.ru ────────


@responses.activate
def test_fill_questionnaire_delegates_to_web_flow_without_http(
        monkeypatch, client):
    """Mobile-реализация сама делегирует в web-flow
    (hh_apply.fill_and_submit_questionnaire): ровно один вызов цели,
    результат пробрасывается наружу, запросов в api.hh.ru нет."""

    async def fake_fill(acc, vid, vacancy_title="", company=""):
        return ("sent", {"via": "questionnaire"})

    web_calls = _patch_web(monkeypatch, "fill_and_submit_questionnaire",
                           fake_fill)

    result = _run_coro(client.fill_questionnaire("v9", "Dev", "Ромашка"))

    assert result == ("sent", {"via": "questionnaire"})
    assert len(web_calls) == 1
    fwd_args, fwd_kwargs = web_calls[0]
    assert fwd_args[0] is ACC
    assert fwd_args[1:] == ("v9", "Dev", "Ромашка")
    assert fwd_kwargs == {}
    assert len(responses.calls) == 0  # без HTTP в api.hh.ru
