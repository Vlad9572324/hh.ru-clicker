"""Тесты mobile-отклика на вакансию (app/mobile_apply.py) и клиентского
метода MobileHHClient.submit_response."""
import asyncio
import concurrent.futures
from urllib.parse import parse_qs, urlparse

import pytest
import requests as _requests
import responses

from app import oauth
from app.hh_client_mobile import MobileHHClient
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError
from app.mobile_apply import submit_response

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
URL = MOBILE_BASE + "/negotiations"


def _run_coro(coro):
    """Запускает корутину через asyncio.run в ОТДЕЛЬНОМ потоке.

    Устойчиво к ситуации, когда в главном потоке уже есть «running» event
    loop (pytest-playwright e2e держит session-scoped Playwright-инстанс) —
    прямой asyncio.run() падал бы с RuntimeError. Приём из
    tests/test_hh_client_delegates.py.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


def _form_of(call_index: int = 0) -> dict:
    """Form-urlencoded поля отправленного запроса (списки значений)."""
    return parse_qs(responses.calls[call_index].request.body)


def _query_of(call_index: int = 0) -> dict:
    """Query-параметры URL отправленного запроса (списки значений)."""
    return parse_qs(urlparse(responses.calls[call_index].request.url).query)


# ---------------------------------------------------------------------------
# app/mobile_apply.submit_response — успех 2xx и контракт запроса
# ---------------------------------------------------------------------------

@responses.activate
def test_200_returns_ok_and_form_contract(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"id": "123"}, status=200)
    result = submit_response(ACC, "v1", "rh1")
    assert result == {"ok": True, "negotiation_id": "123"}
    form = _form_of()
    assert form["vacancy_id"] == ["v1"]
    assert form["resume_id"] == ["rh1"]
    assert form["with_chat_info"] == ["true"]
    # message пустой → поле не шлётся; response_source по дефолту тоже omit.
    assert "message" not in form
    assert "response_source" not in form
    # Tracking query-параметры приложения обязательны.
    query = _query_of()
    assert query["hhtmSource"] == ["vacancy"]
    assert query["hhtmFrom"] == ["vacancy"]


@responses.activate
def test_200_with_message_includes_message_field(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"id": "124"}, status=200)
    result = submit_response(ACC, "v1", "rh1", message="Здравствуйте!")
    assert result["ok"] is True
    assert _form_of()["message"] == ["Здравствуйте!"]


@responses.activate
def test_200_id_null_gives_empty_negotiation_id(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"id": None}, status=200)
    result = submit_response(ACC, "v1", "rh1")
    assert result == {"ok": True, "negotiation_id": ""}


@responses.activate
def test_response_source_sent_when_nonempty(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"id": "1"}, status=200)
    submit_response(ACC, "v1", "rh1", response_source="REGISTRATION")
    assert _form_of()["response_source"] == ["REGISTRATION"]


@responses.activate
def test_custom_hhtm_tracking_params(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"id": "1"}, status=200)
    submit_response(ACC, "v1", "rh1", hhtm_source="search", hhtm_from="catalog")
    query = _query_of()
    assert query["hhtmSource"] == ["search"]
    assert query["hhtmFrom"] == ["catalog"]


# ---------------------------------------------------------------------------
# Бизнес-ошибки (не-2xx, НЕ fallback-статус)
# ---------------------------------------------------------------------------

@responses.activate
def test_400_limit_exceeded(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL,
                  json={"type": "negotiations", "code": "limit_exceeded"},
                  status=400)
    result = submit_response(ACC, "v1", "rh1")
    assert result["ok"] is False
    assert result["error_type"] == "limit_exceeded"
    assert result["http_status"] == 400
    assert result["error"]


@responses.activate
def test_400_test_required(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL,
                  json={"type": "negotiations", "code": "test_required"},
                  status=400)
    result = submit_response(ACC, "v1", "rh1")
    assert result["ok"] is False
    assert result["error_type"] == "test_required"
    assert result["http_status"] == 400


@responses.activate
def test_400_already_applied(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL,
                  json={"type": "negotiations", "code": "already_applied"},
                  status=400)
    result = submit_response(ACC, "v1", "rh1")
    assert result["ok"] is False
    assert result["error_type"] == "already_applied"


@responses.activate
def test_404_vacancy_not_found_in_errors_list(monkeypatch):
    """Код находится и внутри списка errors[] (формат ApiError HH)."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL,
                  json={"errors": [{"type": "vacancy_not_found"}]}, status=404)
    result = submit_response(ACC, "v1", "rh1")
    assert result["ok"] is False
    assert result["error_type"] == "vacancy_not_found"
    assert result["http_status"] == 404


@responses.activate
def test_non_json_payload_with_marker(monkeypatch):
    """Не-JSON текст ошибки с маркером известного кода тоже распознаётся."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, body="oops: limit_exceeded happened",
                  status=400, content_type="text/plain")
    result = submit_response(ACC, "v1", "rh1")
    assert result["ok"] is False
    assert result["error_type"] == "limit_exceeded"


@responses.activate
def test_unknown_error_418(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"type": "teapot"}, status=418)
    result = submit_response(ACC, "v1", "rh1")
    assert result["ok"] is False
    assert result["error_type"] == "http_418"
    assert result["http_status"] == 418


# ---------------------------------------------------------------------------
# Fallback-статусы (0/401/403/5xx) — MobileAPIError наверх без обработки
# ---------------------------------------------------------------------------

@responses.activate
def test_401_raises_mobile_api_error_for_fallback(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"errors": []}, status=401)
    with pytest.raises(MobileAPIError) as ei:
        submit_response(ACC, "v1", "rh1")
    assert ei.value.status_code == 401


@responses.activate
def test_403_raises_mobile_api_error_for_fallback(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"errors": []}, status=403)
    with pytest.raises(MobileAPIError) as ei:
        submit_response(ACC, "v1", "rh1")
    assert ei.value.status_code == 403


@responses.activate
def test_500_raises_mobile_api_error_for_fallback(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, body="internal error", status=500)
    with pytest.raises(MobileAPIError) as ei:
        submit_response(ACC, "v1", "rh1")
    assert ei.value.status_code == 500


@responses.activate
def test_network_error_raises_mobile_api_error_status_zero(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    # Именно requests.exceptions.ConnectionError: responses кидает body-
    # исключение прямо из адаптера, и транспорт ловит requests.RequestException.
    responses.add(responses.POST, URL,
                  body=_requests.exceptions.ConnectionError("net down"))
    with pytest.raises(MobileAPIError) as ei:
        submit_response(ACC, "v1", "rh1")
    assert ei.value.status_code == 0


# ---------------------------------------------------------------------------
# MobileHHClient.submit_response — маппинг dict → web-совместимый tuple
# ---------------------------------------------------------------------------

@responses.activate
def test_client_200_returns_sent_tuple(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"id": "123"}, status=200)
    client = MobileHHClient(dict(ACC))
    status, info = _run_coro(client.submit_response("v1"))
    assert status == "sent"
    assert info == {"negotiation_id": "123"}
    # resume_id взят из acc["resume_hash"].
    assert _form_of()["resume_id"] == ["rh1"]


@responses.activate
def test_client_400_limit_exceeded_returns_limit_tuple(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL,
                  json={"type": "negotiations", "code": "limit_exceeded"},
                  status=400)
    client = MobileHHClient(dict(ACC))
    status, info = _run_coro(client.submit_response("v1"))
    assert status == "limit"
    assert info["error_type"] == "limit_exceeded"
    assert info["http_status"] == 400


@responses.activate
def test_client_letter_max_length_truncates_message(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"id": "9"}, status=200)
    acc = {**ACC, "letter": "0123456789" * 5}  # 50 символов, без {a|b}
    client = MobileHHClient(acc)
    status, _ = _run_coro(client.submit_response("v1", letter_max_length=5))
    assert status == "sent"
    message = _form_of()["message"][0]
    assert len(message) <= 5
    assert message == "01234"


@responses.activate
def test_client_no_letter_means_no_message_field(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"id": "9"}, status=200)
    client = MobileHHClient(dict(ACC))  # acc без ключа "letter"
    status, _ = _run_coro(client.submit_response("v1"))
    assert status == "sent"
    assert "message" not in _form_of()


@pytest.mark.parametrize("code,expected", [
    ("test_required", "test"),
    ("already_applied", "already"),
    ("vacancy_not_found", "error"),
])
@responses.activate
def test_client_maps_business_errors_to_web_tuple(monkeypatch, code, expected):
    """Остальные ветки клиентского маппинга dict→tuple (паритет с web
    classify_apply_response): test_required→test, already_applied→already,
    прочие бизнес-коды→error."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL,
                  json={"type": "negotiations", "code": code}, status=400)
    client = MobileHHClient(dict(ACC))
    status, info = _run_coro(client.submit_response("v1"))
    assert status == expected
    assert info["error_type"] == code
    assert info["http_status"] == 400
