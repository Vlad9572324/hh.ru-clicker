"""Тесты mobile-версий метаданных переговоров и возможных офферов
(app/mobile_neg_meta.py)."""
import pytest
import responses

from app import oauth
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError
from app.mobile_neg_meta import fetch_negotiations_metadata, fetch_possible_offers

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}


# ── fetch_negotiations_metadata ────────────────────────────────────────


@responses.activate
def test_metadata_200_fills_topics_by_vid(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, MOBILE_BASE + "/negotiations", json={
        "items": [
            {
                "id": "5465575576",
                "state": {"id": "response", "name": "Отклик"},
                "viewed_by_opponent": True,
                "has_new_messages": True,
                "counters": {"messages": 3, "unread_messages": 1},
                "vacancy": {"id": "134210190", "name": "Художник по окружению"},
            },
            # без vacancy.id — пропускается (в topics_by_vid не попадает)
            {"id": "555", "state": {"id": "discard", "name": "Отказ"}},
        ],
        "found": 2, "pages": 1, "page": 0, "per_page": 100,
        "has_next_page": False,
    }, status=200)

    out = fetch_negotiations_metadata(ACC)

    assert out["topics_by_vid"] == {
        "134210190": {
            "viewed_by_opponent": True,
            "unread_by_employer": 0,
            "last_state": "response",
            "has_new_messages": True,
        },
    }
    # politeness/activity — web-SSR данные, в mobile-API их нет
    assert out["politeness"] == {}
    assert out["activity"] == {}
    # первая страница с большим per_page
    assert "per_page=100" in responses.calls[0].request.url


@pytest.mark.parametrize("status", [401, 403])
@responses.activate
def test_metadata_auth_error_raises_for_fallback(status, monkeypatch):
    # 401/403 — fallback-статусы: MobileAPIError поднимается, обёртка
    # повторит через web-flow (web отдаст полные politeness/activity из SSR).
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, MOBILE_BASE + "/negotiations",
                  json={"errors": [{"value": "unauthorized"}]}, status=status)
    with pytest.raises(MobileAPIError) as ei:
        fetch_negotiations_metadata(ACC)
    assert ei.value.status_code == status


@responses.activate
def test_metadata_5xx_raises_for_fallback(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, MOBILE_BASE + "/negotiations",
                  body="service unavailable", status=503)
    with pytest.raises(MobileAPIError) as ei:
        fetch_negotiations_metadata(ACC)
    assert ei.value.status_code == 503


# ── fetch_possible_offers ──────────────────────────────────────────────


@responses.activate
def test_possible_offers_200_list_response(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, MOBILE_BASE + "/vacancies/possible_job_offers",
                  json=[{"name": "Ромашка",
                         "vacancies": [{"id": "1", "name": "Инженер"},
                                       {"id": "2", "name": "Тестировщик"}]}],
                  status=200)
    assert fetch_possible_offers(ACC) == [
        {"name": "Ромашка", "vacancyNames": ["Инженер", "Тестировщик"]},
    ]


@responses.activate
def test_possible_offers_200_dict_items_response(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, MOBILE_BASE + "/vacancies/possible_job_offers",
                  json={"items": [
                      {"name": "ООО Вектор",
                       "vacancies": [{"name": "Разработчик"}]},
                      # вариант с одиночным vacancy вместо списка vacancies
                      {"name": "ИП Иванов", "vacancy": {"name": "Курьер"}},
                  ]}, status=200)
    assert fetch_possible_offers(ACC) == [
        {"name": "ООО Вектор", "vacancyNames": ["Разработчик"]},
        {"name": "ИП Иванов", "vacancyNames": ["Курьер"]},
    ]


@responses.activate
def test_possible_offers_404_returns_empty(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, MOBILE_BASE + "/vacancies/possible_job_offers",
                  json={"errors": [{"value": "not_found"}]}, status=404)
    assert fetch_possible_offers(ACC) == []


@responses.activate
def test_possible_offers_401_raises(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, MOBILE_BASE + "/vacancies/possible_job_offers",
                  json={"errors": [{"value": "unauthorized"}]}, status=401)
    with pytest.raises(MobileAPIError) as ei:
        fetch_possible_offers(ACC)
    assert ei.value.status_code == 401
