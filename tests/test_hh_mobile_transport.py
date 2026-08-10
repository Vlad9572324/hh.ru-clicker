"""Тесты общего транспорта mobile-вызовов (app/hh_mobile_transport.py)."""
import pytest
import responses

from app import oauth
from app.hh_mobile_transport import (
    MOBILE_BASE,
    MobileAPIError,
    is_fallback_status,
    mobile_headers,
    mobile_request,
)

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}


def test_headers_contract():
    h = mobile_headers("tok123")
    assert h["Authorization"] == "Bearer tok123"
    assert h["User-Agent"] == "ru.hh.android/26.28.1"
    assert h["x-force-app-access"] == "true"


def test_no_token_raises_401(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "")
    with pytest.raises(MobileAPIError) as ei:
        mobile_request(ACC, "GET", "/chats")
    assert ei.value.status_code == 401
    assert ei.value.payload == "no_oauth_token"


@responses.activate
def test_2xx_returns_json(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, MOBILE_BASE + "/chats", json={"ok": 1}, status=200)
    assert mobile_request(ACC, "GET", "/chats") == {"ok": 1}
    req = responses.calls[0].request
    assert req.headers["Authorization"] == "Bearer t"
    assert req.headers["x-force-app-access"] == "true"


@responses.activate
def test_204_empty_body_returns_none(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.PUT, MOBILE_BASE + "/chats/1/messages/last_viewed_id",
                  status=204)
    assert mobile_request(ACC, "PUT", "/chats/1/messages/last_viewed_id",
                          form={"message_id": 5}) is None


@responses.activate
def test_non_2xx_raises_with_status_and_payload(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, MOBILE_BASE + "/chats/x",
                  json={"errors": [{"value": "bad"}]}, status=400)
    with pytest.raises(MobileAPIError) as ei:
        mobile_request(ACC, "GET", "/chats/x")
    assert ei.value.status_code == 400
    assert ei.value.payload == {"errors": [{"value": "bad"}]}


@responses.activate
def test_non_json_error_body_kept_as_text(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, MOBILE_BASE + "/oops", body="server died", status=503)
    with pytest.raises(MobileAPIError) as ei:
        mobile_request(ACC, "GET", "/oops")
    assert ei.value.status_code == 503
    assert ei.value.payload == "server died"


def test_network_error_raises_status_zero(monkeypatch):
    # `responses` не умеет корректно симулировать сетевой обрыв (кидает
    # ConnectionError мимо обёрток requests), поэтому monkeypatch'им
    # requests.request напрямую — транспорт обязан поймать RequestException.
    import requests as _requests

    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")

    def _raise(*a, **kw):
        raise _requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(_requests, "request", _raise)
    with pytest.raises(MobileAPIError) as ei:
        mobile_request(ACC, "GET", "/chats")
    assert ei.value.status_code == 0


@responses.activate
def test_full_url_passthrough_and_params(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, "https://api.hh.ru/negotiations",
                  json={"items": []}, status=200)
    mobile_request(ACC, "GET", "https://api.hh.ru/negotiations",
                   params={"per_page": 100})
    assert "per_page=100" in responses.calls[0].request.url


def test_is_fallback_status():
    assert is_fallback_status(0)
    assert is_fallback_status(401)
    assert is_fallback_status(403)
    assert is_fallback_status(500)
    assert is_fallback_status(599)
    assert not is_fallback_status(200)
    assert not is_fallback_status(400)
    assert not is_fallback_status(404)
    assert not is_fallback_status(409)
