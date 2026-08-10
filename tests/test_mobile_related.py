"""Тесты похожих вакансий для расширения пула через mobile-API
(app/mobile_related.py)."""
import pytest
import responses

from app import mobile_related, oauth
from app.hh_client_mobile import MobileHHClient
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError
from app.mobile_related import fetch_related_vacancies

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}

OFFERS_URL = MOBILE_BASE + "/vacancies/possible_job_offers"


def _suitable_url(seed_vid: str) -> str:
    return f"{MOBILE_BASE}/vacancies/{seed_vid}/suitable_resumes"


def _add_suitable_ok(seed_vid: str, **json_overrides):
    """Регистрация диагностического suitable_resumes (seed непуст -> вызов
    происходит всегда; по умолчанию отдаём «всё подходит»)."""
    body = {"counters": {"suitable": 1, "not_published": 0,
                         "already_applied": 0, "unavailable": 0},
            "suitable": [{"id": "r1"}], "already_applied": [],
            "resume_inconsistencies": {}}
    body.update(json_overrides)
    responses.add(responses.GET, _suitable_url(seed_vid), json=body, status=200)


# ── сбор списка из possible_job_offers ─────────────────────────────────


@responses.activate
def test_offers_list_form_returns_str_ids(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, OFFERS_URL, json=[
        {"name": "E1", "vacancies": [{"id": 111, "name": "v"},
                                      {"id": "222"}]},
    ], status=200)
    _add_suitable_ok("999")

    assert fetch_related_vacancies(ACC, "999") == ["111", "222"]


@responses.activate
def test_seed_vacancy_excluded(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, OFFERS_URL, json=[
        {"name": "E1", "vacancies": [{"id": "111"}, {"id": 222}]},
    ], status=200)
    _add_suitable_ok("111")

    assert fetch_related_vacancies(ACC, "111") == ["222"]


@responses.activate
def test_offers_dict_items_form(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, OFFERS_URL, json={"items": [
        {"name": "E1", "vacancies": [{"id": "111", "name": "v1"}]},
        {"name": "E2", "vacancies": [{"id": "222", "name": "v2"}]},
    ]}, status=200)
    _add_suitable_ok("999")

    assert fetch_related_vacancies(ACC, "999") == ["111", "222"]


@responses.activate
def test_already_applied_items_skipped(monkeypatch):
    # флаг already_applied может быть и на item'е, и на vacancy-объекте
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, OFFERS_URL, json=[
        {"name": "E1", "already_applied": True,
         "vacancies": [{"id": "111"}]},
        {"name": "E2", "vacancies": [{"id": "222", "already_applied": True},
                                      {"id": "333"}]},
    ], status=200)
    _add_suitable_ok("999")

    assert fetch_related_vacancies(ACC, "999") == ["333"]


@responses.activate
def test_single_vacancy_object_form(monkeypatch):
    # элемент без списка vacancies, но с одиночным {"vacancy": {...}}
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, OFFERS_URL, json=[
        {"name": "ИП Иванов", "vacancy": {"id": 333, "name": "Курьер"}},
    ], status=200)
    _add_suitable_ok("999")

    assert fetch_related_vacancies(ACC, "999") == ["333"]


@responses.activate
def test_duplicate_ids_across_items_once(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, OFFERS_URL, json=[
        {"name": "E1", "vacancies": [{"id": "111"}, {"id": 111}]},
        {"name": "E2", "vacancies": [{"id": "111"}, {"id": "222"}]},
    ], status=200)
    _add_suitable_ok("999")

    assert fetch_related_vacancies(ACC, "999") == ["111", "222"]


# ── ошибки possible_job_offers ─────────────────────────────────────────


@responses.activate
def test_offers_401_raises_for_fallback(monkeypatch):
    # fallback-статус: MobileAPIError наверх, обёртка повторит через web-flow
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, OFFERS_URL,
                  json={"errors": [{"value": "unauthorized"}]}, status=401)

    with pytest.raises(MobileAPIError) as ei:
        fetch_related_vacancies(ACC, "999")
    assert ei.value.status_code == 401


@responses.activate
def test_offers_404_returns_empty(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, OFFERS_URL,
                  json={"errors": [{"value": "not_found"}]}, status=404)
    _add_suitable_ok("999")

    assert fetch_related_vacancies(ACC, "999") == []


# ── диагностический suitable_resumes ───────────────────────────────────


@responses.activate
def test_suitable_resumes_called_and_its_404_not_fatal(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, OFFERS_URL, json=[
        {"name": "E1", "vacancies": [{"id": "111"}]},
    ], status=200)
    responses.add(responses.GET, _suitable_url("123"),
                  json={"errors": [{"value": "not_found"}]}, status=404)

    assert fetch_related_vacancies(ACC, "123") == ["111"]
    # диагностический вызов действительно был
    assert any("/vacancies/123/suitable_resumes" in c.request.url
               for c in responses.calls)


@responses.activate
def test_suitable_resumes_zero_suitable_with_inconsistencies_no_crash(monkeypatch):
    # counters.suitable == 0 + непустой resume_inconsistencies -> только
    # log_debug-предупреждение, на результат не влияет
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, OFFERS_URL, json=[
        {"name": "E1", "vacancies": [{"id": "111"}]},
    ], status=200)
    _add_suitable_ok("123",
                     counters={"suitable": 0, "not_published": 0,
                               "already_applied": 0, "unavailable": 1},
                     suitable=[],
                     resume_inconsistencies={"r1": [{"key": "experience"}]})

    assert fetch_related_vacancies(ACC, "123") == ["111"]


@responses.activate
def test_empty_seed_collects_offers_without_suitable_call(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, OFFERS_URL, json=[
        {"name": "E1", "vacancies": [{"id": "111"}]},
    ], status=200)

    assert fetch_related_vacancies(ACC, "") == ["111"]
    assert all("suitable_resumes" not in c.request.url
               for c in responses.calls)


# ── клиентский метод ───────────────────────────────────────────────────


def test_client_method_delegates_to_module(monkeypatch):
    calls = []

    def fake(acc, vid, max_pages=1):
        calls.append((acc, vid, max_pages))
        return ["777"]

    monkeypatch.setattr(mobile_related, "fetch_related_vacancies", fake)
    client = MobileHHClient(ACC)
    assert client.fetch_related_vacancies("123", 2) == ["777"]
    assert calls == [(ACC, "123", 2)]
