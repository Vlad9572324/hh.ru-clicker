"""Regression-тесты Phase 3 миграции mobile-api.

Страхуют, что Phase 3 ничего не сломала:
1. Фабрика get_client: матрица mode → тип клиента
   (docs/PHASE_MATRIX.md): mobile → FallbackHHClient, web/auto/нет поля/
   не-строка → WebHHClient.
2. Ни один из 6 методов Phase 3 на MobileHHClient больше не кидает
   NotImplementedError("phase 3") при живом токене: responses 200 на
   mobile-endpoint → вызов проходит и возвращает результат; web-flow при
   этом НЕ вызывается (подменён рекордерами).
3. Web-flow не тронут: classify_apply_response из app.hh_apply
   классифицирует базовые кейсы как раньше.
4. Phase 2 не задета: mobile send_message по-прежнему работает.
5. FallbackHHClient._METHODS синхронизирован с контрактом HHClient
   (guard-assert при импорте модуля) и содержит все 6 имён Phase 3.

Никаких живых запросов: HTTP перехвачен `responses`, OAuth-токен подменён
monkeypatch app.oauth._obtain_oauth_token.
"""
import asyncio
import concurrent.futures

import pytest
import responses

from app import hh_apply, oauth
from app.config import CONFIG
from app.hh_client import HHClient
from app.hh_client_factory import get_client
from app.hh_client_fallback import FallbackHHClient, _METHODS
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

# Все 6 методов Phase 3 — имена в контракте HHClient / FallbackHHClient.
PHASE3_METHODS = {
    "submit_response",
    "fill_questionnaire",
    "check_vacancy_before_apply",
    "check_limit",
    "touch_resume",
    "fetch_related_vacancies",
}


def _run_coro(coro):
    # Тот же приём, что в tests/test_hh_client_delegates.py: pytest-playwright
    # (e2e) может держать «running» loop в главном потоке, поэтому asyncio.run()
    # исполняем в отдельном потоке.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


@pytest.fixture
def oauth_token(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")


@pytest.fixture
def web_recs(monkeypatch):
    """Рекордеры web-целей в модуле app.hh_apply (WebHHClient импортирует
    модуль). Для 5 sync/async методов Phase 3 список должен остаться ПУСТЫМ
    (mobile справился сам); для fill_questionnaire делегирование в
    fill_and_submit_questionnaire — ожидаемый путь (ровно 1 вызов)."""
    recs = {
        "send_response_async": [],
        "fill_and_submit_questionnaire": [],
        "_check_vacancy_before_apply": [],
        "check_limit": [],
        "touch_resume": [],
        "fetch_related_vacancies": [],
    }

    async def fake_send(acc, vid, letter_max_length=None):
        recs["send_response_async"].append((acc, vid, letter_max_length))
        return ("sent", {})

    async def fake_fill(acc, vid, vacancy_title="", company=""):
        recs["fill_and_submit_questionnaire"].append(
            (acc, vid, vacancy_title, company))
        return ("sent", {"via": "questionnaire"})

    def fake_precheck(acc, vid):
        recs["_check_vacancy_before_apply"].append((acc, vid))
        return {"ok": True, "missing": []}

    def fake_check_limit(acc):
        recs["check_limit"].append((acc,))
        return True

    def fake_touch(acc):
        recs["touch_resume"].append((acc,))
        return True, "web"

    def fake_related(acc, seed_vid, max_pages=1):
        recs["fetch_related_vacancies"].append((acc, seed_vid, max_pages))
        return []

    monkeypatch.setattr(hh_apply, "send_response_async", fake_send)
    monkeypatch.setattr(hh_apply, "fill_and_submit_questionnaire", fake_fill)
    monkeypatch.setattr(hh_apply, "_check_vacancy_before_apply", fake_precheck)
    monkeypatch.setattr(hh_apply, "check_limit", fake_check_limit)
    monkeypatch.setattr(hh_apply, "touch_resume", fake_touch)
    monkeypatch.setattr(hh_apply, "fetch_related_vacancies", fake_related)
    return recs


# ── 1. Фабрика: матрица mode ─────────────────────────────────────────────────


@pytest.mark.parametrize("mode,expected", [
    ("mobile", "fallback"),
    ("web", "web"),
    ("auto", "web"),
    (None, "web"),      # поля "mode" нет → CONFIG.default_client_mode ("web")
    (123, "web"),       # не-строка → "auto" → web (docs/PHASE_MATRIX.md)
], ids=["mobile", "web", "auto", "mode-missing", "mode-non-string-123"])
def test_factory_mode_matrix(monkeypatch, mode, expected):
    monkeypatch.setattr(CONFIG, "default_client_mode", "web")
    acc = {"name": "a1", "cookies": {}, "resume_hash": "rh"}
    if mode is not None:
        acc["mode"] = mode

    client = get_client(acc)

    if expected == "fallback":
        assert isinstance(client, FallbackHHClient)
        assert isinstance(client, HHClient)
        assert isinstance(client.mobile, MobileHHClient)
        assert isinstance(client.web, WebHHClient)
        assert client.mode == "mobile"
    else:
        assert isinstance(client, WebHHClient)
        assert not isinstance(client, FallbackHHClient)


def test_factory_bare_account_dict_is_web(monkeypatch):
    """Совсем пустой аккаунт {} — тоже web (нет поля mode → default "web")."""
    monkeypatch.setattr(CONFIG, "default_client_mode", "web")
    client = get_client({})
    assert isinstance(client, WebHHClient)
    assert not isinstance(client, FallbackHHClient)


# ── 2. Методы Phase 3 на MobileHHClient: без NotImplementedError ─────────────
#
# Важно: вызываем MobileHHClient НАПРЯМУЮ (не через FallbackHHClient) —
# NotImplementedError("phase 3") уронил бы тест, а web_recs доказывают,
# что результат дал именно mobile-flow, а не тихий fallback.


@responses.activate
def test_mobile_submit_response_200_sent(oauth_token, web_recs):
    responses.add(responses.POST, URL_NEGOTIATIONS,
                  json={"id": "777888"}, status=200)

    result = _run_coro(MobileHHClient(ACC).submit_response("v1"))

    assert result[0] == "sent"
    assert result[1].get("negotiation_id") == "777888"
    assert web_recs["send_response_async"] == []


@responses.activate
def test_mobile_fill_questionnaire_delegates_to_web_flow(oauth_token, web_recs):
    """Mobile-реализация делегирует в web-flow — без HTTP в api.hh.ru."""
    result = _run_coro(
        MobileHHClient(ACC).fill_questionnaire("v9", "Dev", "Ромашка"))

    assert result == ("sent", {"via": "questionnaire"})
    assert web_recs["fill_and_submit_questionnaire"] == [
        (ACC, "v9", "Dev", "Ромашка")]
    assert len(responses.calls) == 0


@responses.activate
def test_mobile_check_vacancy_before_apply_200(oauth_token, web_recs):
    responses.add(responses.GET, URL_DATA_INCONSISTENCY,
                  json={"data_inconsistency": []}, status=200)

    result = MobileHHClient(ACC).check_vacancy_before_apply("v1")

    assert result == {"ok": True, "hard_missing": [], "soft_missing": []}
    assert web_recs["_check_vacancy_before_apply"] == []


@responses.activate
def test_mobile_check_limit_200(oauth_token, web_recs):
    responses.add(responses.GET, URL_STATISTIC,
                  json={"applicant_statistic": {"responses_streak": {
                      "responses_count": 5, "responses_required": 200}}},
                  status=200)

    result = MobileHHClient(ACC).check_limit()

    assert result is False  # can_apply=True → лимит НЕ активен
    assert web_recs["check_limit"] == []


@responses.activate
def test_mobile_touch_resume_200(oauth_token, web_recs):
    responses.add(responses.POST, URL_PUBLISH, status=200)

    result = MobileHHClient(ACC).touch_resume()

    assert isinstance(result, tuple) and len(result) == 2
    assert result[0] is True
    assert isinstance(result[1], str)
    assert web_recs["touch_resume"] == []


@responses.activate
def test_mobile_fetch_related_vacancies_200(oauth_token, web_recs):
    responses.add(responses.GET, URL_POSSIBLE_OFFERS,
                  json={"items": [{"name": "Ромашка", "vacancies": [
                      {"id": "111", "name": "Dev"},
                      {"id": "222", "name": "QA"}]}]},
                  status=200)
    # диагностический suitable_resumes (best-effort, глотает ошибки)
    responses.add(responses.GET, MOBILE_BASE + "/vacancies/v1/suitable_resumes",
                  json={"counters": {"suitable": 2}}, status=200)

    result = MobileHHClient(ACC).fetch_related_vacancies("v1")

    assert result == ["111", "222"]
    assert all(isinstance(v, str) for v in result)
    assert web_recs["fetch_related_vacancies"] == []


# ── 3. Web-flow не тронут: classify_apply_response ───────────────────────────


def test_classify_apply_response_401_auth_error():
    assert hh_apply.classify_apply_response(401, "") == ("auth_error", {})


def test_classify_apply_response_200_success_sent_with_topic_id():
    result, info = hh_apply.classify_apply_response(
        200, '{"success":true,"topic_id":"t1"}')
    assert result == "sent"
    assert info.get("topic_id") == "t1"


def test_classify_apply_response_200_login_page_is_auth_error():
    # Маркер login-страницы — по app.logging_utils._is_login_page
    # ("hh.ru/account/login").
    html = ('<!doctype html><html><head></head><body>'
            '<a href="https://hh.ru/account/login?backurl=/vacancy/1">'
            'Вход</a></body></html>')
    result, _info = hh_apply.classify_apply_response(200, html)
    assert result == "auth_error"


# ── 4. Phase 2 не задета: mobile send_message ────────────────────────────────


@responses.activate
def test_phase2_mobile_send_message_smoke(oauth_token):
    from app import mobile_send_message

    responses.add(responses.POST, MOBILE_BASE + "/chats/777/messages",
                  json={"id": 42}, status=200)

    assert mobile_send_message.send_message(
        ACC, "777", "hi", idempotency_key="k") is True


# ── 5. FallbackHHClient._METHODS синхронизирован с контрактом ────────────────


def test_fallback_methods_synced_and_contain_phase3():
    # Импорт app.hh_client_fallback сам выполняет guard-assert
    # set(_METHODS) == set(HHClient.__abstractmethods__); здесь фиксируем
    # явно, что все 6 имён Phase 3 на месте.
    assert PHASE3_METHODS <= set(_METHODS)
    assert set(_METHODS) == set(HHClient.__abstractmethods__)
    assert FallbackHHClient.__abstractmethods__ == frozenset()
