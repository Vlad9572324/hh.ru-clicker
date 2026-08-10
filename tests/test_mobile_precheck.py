"""Тесты mobile pre-flight проверки вакансии перед откликом
(app/mobile_precheck.py)."""
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from app import oauth
from app.hh_client_mobile import MobileHHClient
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError
from app.mobile_precheck import check_vacancy_before_apply

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
URL = MOBILE_BASE + "/resume_profile/data_inconsistency"


def _query() -> dict:
    """Query-параметры последнего запроса в виде {key: [значения]}."""
    return parse_qs(urlparse(responses.calls[-1].request.url).query)


@responses.activate
def test_200_empty_missing_ok_and_query_params(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, URL, json={"data_inconsistency": []}, status=200)

    out = check_vacancy_before_apply(ACC, "123", resume_id="rh1")

    assert out == {"ok": True, "hard_missing": [], "soft_missing": []}
    q = _query()
    assert q["vacancy_id"] == ["123"]
    assert q["resume_id"] == ["rh1"]
    assert q["flow"] == ["vacancy_response"]
    assert q["auto_seen"] == ["true"]
    # supported_screens по контракту APK не отправляем
    assert "supported_screens" not in q


@responses.activate
def test_200_list_of_strings_missing(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, URL,
                  json={"data_inconsistency": ["WORK_FORMAT", "PHOTO"]}, status=200)

    out = check_vacancy_before_apply(ACC, "123", resume_id="rh1")

    assert out == {"ok": False, "hard_missing": ["WORK_FORMAT"], "soft_missing": ["PHOTO"]}


@responses.activate
def test_200_list_of_dicts_type_or_id(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, URL, json={"data_inconsistency": [
        {"type": "PHOTO"},
        {"id": "EDUCATION"},
        {"name": "OTHER"},  # без type/id — пропускается
    ]}, status=200)

    out = check_vacancy_before_apply(ACC, "123", resume_id="rh1")

    assert out == {"ok": True, "hard_missing": [], "soft_missing": ["PHOTO", "EDUCATION"]}


@responses.activate
def test_200_dict_with_values_missing(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, URL, json={"data_inconsistency": {
        "items": ["PHOTO"],
        "single": "WORK_FORMAT",
    }}, status=200)

    out = check_vacancy_before_apply(ACC, "123", resume_id="rh1")

    assert out["ok"] is False
    assert out["hard_missing"] == ["WORK_FORMAT"]
    assert out["soft_missing"] == ["PHOTO"]


@responses.activate
def test_200_empty_body_fail_closed(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, URL, body="", status=200,
                  content_type="text/plain")

    out = check_vacancy_before_apply(ACC, "123", resume_id="rh1")

    # пустое тело → mobile_request вернёт None → fail-closed как в web
    assert out == {"ok": False, "missing": [], "reason": "empty_response"}


@responses.activate
def test_200_not_a_list_defensively_empty(monkeypatch):
    # data_inconsistency не list и не dict → защитно missing=[] (ok=True)
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, URL,
                  json={"data_inconsistency": "unexpected"}, status=200)

    out = check_vacancy_before_apply(ACC, "123", resume_id="rh1")

    assert out == {"ok": True, "hard_missing": [], "soft_missing": []}


@responses.activate
def test_401_raises_for_fallback(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, URL, json={"errors": []}, status=401)
    with pytest.raises(MobileAPIError) as ei:
        check_vacancy_before_apply(ACC, "123", resume_id="rh1")
    assert ei.value.status_code == 401


@responses.activate
def test_500_raises_for_fallback(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, URL, body="internal error", status=500)
    with pytest.raises(MobileAPIError) as ei:
        check_vacancy_before_apply(ACC, "123", resume_id="rh1")
    assert ei.value.status_code == 500


@responses.activate
def test_404_fail_closed_http_404(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, URL, json={"errors": []}, status=404)

    out = check_vacancy_before_apply(ACC, "123", resume_id="rh1")

    assert out == {"ok": False, "missing": [], "reason": "http_404"}


@responses.activate
def test_client_substitutes_resume_hash_from_acc(monkeypatch):
    # MobileHHClient.check_vacancy_before_apply подставляет resume_hash
    # из acc как resume_id в query.
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, URL, json={"data_inconsistency": []}, status=200)

    out = MobileHHClient(ACC).check_vacancy_before_apply("123")

    assert out == {"ok": True, "hard_missing": [], "soft_missing": []}
    q = _query()
    assert q["resume_id"] == ["rh1"]
    assert q["vacancy_id"] == ["123"]
    assert q["flow"] == ["vacancy_response"]
