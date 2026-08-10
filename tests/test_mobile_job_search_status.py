"""Тесты Phase 4: mobile-смена статуса поиска работы (WRITE-операция).

Проверяется полный путь: app.mobile_job_search_status.set_job_search_status
→ app.hh_mobile_transport.mobile_request → реальный HTTP, перехваченный
библиотекой `responses` (никаких живых запросов: все URL api.hh.ru
замоканы, Bearer-токен подменён через monkeypatch
app.oauth._obtain_oauth_token).

Контракт (reverse APK ru.hh.android/26.28.1, JobSearchStatusRemoteApi.kt —
Uq/InterfaceC4443a.java): @PUT + @FormUrlEncoded + @Field("id"), т.е.

    PUT https://api.hh.ru/user_statuses/job_search_statuses/mine
    form-body: id=<status_id>

Конвенция тестов — tests/test_mobile_phase2_integration.py.
"""
import json
from urllib.parse import parse_qsl

import pytest
import responses

from app import oauth
from app.hh_client_mobile import MobileHHClient
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}

STATUS_URL = MOBILE_BASE + "/user_statuses/job_search_statuses/mine"


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
# 1. Happy-path: PUT с form-телом id=<status>, 2xx → {ok, status, label}
# ---------------------------------------------------------------------------

@responses.activate
def test_set_job_search_status_happy_path_200(oauth_token):
    from app.mobile_job_search_status import _STATUS_LABELS, set_job_search_status

    responses.add(responses.PUT, STATUS_URL, json={}, status=200)

    result = set_job_search_status(ACC, "active_search")

    assert result == {
        "ok": True,
        "status": "active_search",
        "label": _STATUS_LABELS["active_search"],
    }

    req = _last_request()
    assert req.method == "PUT"
    assert req.url.split("?")[0] == STATUS_URL
    # form-urlencoded тело: id=<канонический статус>
    assert _body_as_dict(req).get("id") == "active_search"
    _assert_bearer(req)


@responses.activate
def test_set_job_search_status_happy_path_204_empty_body(oauth_token):
    """204 без тела — тоже успех (mobile_request вернёт None)."""
    from app.mobile_job_search_status import _STATUS_LABELS, set_job_search_status

    responses.add(responses.PUT, STATUS_URL, status=204)  # пустое тело

    result = set_job_search_status(ACC, "active_search")

    assert result == {
        "ok": True,
        "status": "active_search",
        "label": _STATUS_LABELS["active_search"],
    }

    req = _last_request()
    assert req.method == "PUT"
    assert req.url.split("?")[0] == STATUS_URL
    assert _body_as_dict(req).get("id") == "active_search"
    _assert_bearer(req)


# ---------------------------------------------------------------------------
# 2. Алиасы и регистр нормализуются к каноническим id (APK SearchStatus.kt)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("alias,canonical", [
    ("not_looking", "not_looking_for_job"),
    ("considering", "looking_for_offers"),
    ("about_to_leave", "looking_for_offers"),
    ("already_found", "accepted_job_offer"),
    ("accept_offers", "looking_for_offers"),   # web-id (hh_resume.py)
    ("ACTIVE_SEARCH", "active_search"),        # регистр не важен
])
@responses.activate
def test_set_job_search_status_aliases(oauth_token, alias, canonical):
    from app.mobile_job_search_status import _STATUS_LABELS, set_job_search_status

    responses.add(responses.PUT, STATUS_URL, json={}, status=200)

    result = set_job_search_status(ACC, alias)

    assert result["ok"] is True
    assert result["status"] == canonical
    assert result["label"] == _STATUS_LABELS[canonical]

    # в сеть уходит КАНОНИЧЕСКИЙ id, а не алиас
    req = _last_request()
    assert _body_as_dict(req).get("id") == canonical
    _assert_bearer(req)


# ---------------------------------------------------------------------------
# 3. Неизвестный статус — ошибка БЕЗ сетевых запросов
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_status", ["banana", ""])
@responses.activate
def test_set_job_search_status_unknown_no_network(oauth_token, bad_status):
    from app.mobile_job_search_status import set_job_search_status

    result = set_job_search_status(ACC, bad_status)

    assert result["ok"] is False
    assert "Неизвестный статус" in result["error"]
    assert "Доступные" in result["error"]
    # ни одного запроса не ушло
    assert len(responses.calls) == 0


# ---------------------------------------------------------------------------
# 4. Ошибки HTTP: не-fallback → {ok: False, error}; fallback → MobileAPIError
# ---------------------------------------------------------------------------

@responses.activate
def test_set_job_search_status_http_400_error_dict(oauth_token):
    from app.mobile_job_search_status import set_job_search_status

    responses.add(responses.PUT, STATUS_URL,
                  json={"errors": [{"value": "bad_status"}]}, status=400)

    result = set_job_search_status(ACC, "active_search")

    assert result["ok"] is False
    assert "HTTP 400" in result["error"]


@pytest.mark.parametrize("code", [401, 500])
@responses.activate
def test_set_job_search_status_fallback_raises(oauth_token, code):
    """401/5xx — fallback-статусы: проглатывать нельзя, кидает MobileAPIError
    (фабрика повторит через web-flow)."""
    from app.mobile_job_search_status import set_job_search_status

    responses.add(responses.PUT, STATUS_URL,
                  json={"errors": [{"value": "token_expired"}]}, status=code)

    with pytest.raises(MobileAPIError) as ei:
        set_job_search_status(ACC, "active_search")
    assert ei.value.status_code == code


# ---------------------------------------------------------------------------
# 5. Делегат MobileHHClient.set_job_search_status
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_client_delegate_set_job_search_status(oauth_token):
    responses.add(responses.PUT, STATUS_URL, json={}, status=200)

    result = MobileHHClient(ACC).set_job_search_status("active_search")

    assert result["ok"] is True
    assert result["status"] == "active_search"
    assert _body_as_dict(_last_request()).get("id") == "active_search"
