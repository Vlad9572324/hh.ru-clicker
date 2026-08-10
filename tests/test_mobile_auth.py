import json
from pathlib import Path

import pytest
import requests

from app import mobile_auth as ma


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
        self.content = json.dumps(self._payload).encode()

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses, web_responses=None):
        self.responses = list(responses)
        self.web_responses = list(web_responses or [])
        self.calls = []
        self.cookies = requests.cookies.RequestsCookieJar()

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.calls.append(("GET-WEB", url, kwargs))
        return self.web_responses.pop(0)


@pytest.fixture
def isolated_mobile(monkeypatch, tmp_path):
    monkeypatch.setattr(ma, "CONFIG_FILE", tmp_path / "mobile_auth_config.json")
    monkeypatch.setattr(ma, "LEGACY_CONFIG_FILE", tmp_path / "legacy_mobile_auth_config.json")
    monkeypatch.setattr(ma, "STATE_FILE", tmp_path / "mobile_auth_state.json")
    ma._web_overrides.clear()
    for env in ma.ENV_KEYS.values():
        monkeypatch.delenv(env, raising=False)
    yield tmp_path
    ma._web_overrides.clear()


def test_defaults_and_user_agent(isolated_mobile):
    cfg, sources = ma.effective_config()
    assert cfg.user_agent == "ru.hh.android/26.29.11476, Device: Pixel 10, Android OS: 17 (UUID: 8f42e879-43c7-4d86-a671-31ea36ed924b)"
    assert set(sources.values()) == {"default"}


def test_priority_and_secret_mask(isolated_mobile, monkeypatch):
    ma.CONFIG_FILE.write_text(json.dumps({"unrelated": 1, "mobile_auth": {**ma.DEFAULTS, "device_model": "File"}}), encoding="utf-8")
    monkeypatch.setenv("HH_DEVICE_MODEL", "Environment")
    data = ma.save_config({"device_model": "Web"})
    assert data["values"]["device_model"] == "Web"
    assert data["sources"]["device_model"] == "web"
    assert data["values"]["app_client_token"] == ma.MASK
    assert ma.DEFAULTS["app_client_token"] not in json.dumps(data)
    assert json.loads(ma.CONFIG_FILE.read_text())["unrelated"] == 1


def test_mask_does_not_overwrite_secret(isolated_mobile):
    ma.save_config({"app_client_token": "custom-secret"})
    ma.save_config({"app_client_token": ma.MASK, "device_model": "Changed"})
    cfg, _ = ma.effective_config()
    assert cfg.app_client_token == "custom-secret"


@pytest.mark.parametrize("updates", [
    {"app_version_code": 0}, {"device_uuid": "not-a-uuid"},
    {"user_agent_template": "%s"},
])
def test_invalid_config_rejected(isolated_mobile, updates):
    with pytest.raises(ma.MobileAuthError):
        ma.save_config(updates)


def test_request_and_login_persist_state_and_tokens(isolated_mobile):
    session = FakeSession([
        FakeResponse(payload={"code_length": 4, "can_request_code_again_in": 30}),
        FakeResponse(payload={"access_token": "access", "refresh_token": "refresh", "expires_in": 60}),
        FakeResponse(payload={"id": "user-1", "first_name": "Test"}),
        FakeResponse(payload={"items": [{"id": "resume-1", "title": "QA"}]}),
    ])
    client = ma.HHMobileClient(session=session)
    client.request_code("test@example.com", "email")
    assert ma.auth_status()["login_masked"] == "te***@example.com"
    tokens, me, resumes = client.login("1234")
    assert tokens["expires_at"] >= tokens["obtained_at"] + 60
    assert me["id"] == "user-1" and resumes[0]["id"] == "resume-1"


def test_bad_code_error_is_safe(isolated_mobile):
    session = FakeSession([
        FakeResponse(payload={"code_length": 4}),
        FakeResponse(status=400, payload={"errors": [{"type": "bad_argument", "value": "confirmation_code"}]}),
    ])
    client = ma.HHMobileClient(session=session)
    client.request_code("+79990000000", "phone")
    with pytest.raises(ma.MobileAuthError, match="Неверный код"):
        client.login("1111")


def test_atomic_write_keeps_no_tmp(isolated_mobile):
    ma.save_config({"device_model": "Pixel Test"})
    assert ma.CONFIG_FILE.exists()
    assert not ma.CONFIG_FILE.with_suffix(".json.tmp").exists()


def test_official_autologin_collects_browser_cookies(isolated_mobile):
    session = FakeSession(
        [FakeResponse(payload={"key": "one-time-key"})],
        [FakeResponse(status=302, headers={"Location": "/account"}), FakeResponse(payload={})],
    )
    session.cookies.set("hhtoken", "web-token", domain=".hh.ru")
    session.cookies.set("hhuid", "web-uid", domain=".hh.ru")
    session.cookies.set("_xsrf", "csrf", domain=".hh.ru")
    client = ma.HHMobileClient(session=session)
    cookies = client.create_browser_cookies("oauth-token", {"id": "42", "crypted_id": "crypted"})
    assert cookies == {"hhtoken": "web-token", "hhuid": "web-uid", "_xsrf": "csrf", "crypted_id": "crypted"}
    assert "loginkey=one-time-key" in session.calls[1][1]
    assert "Authorization" not in session.calls[1][2]["headers"]


def test_autologin_rejects_external_redirect(isolated_mobile):
    session = FakeSession(
        [FakeResponse(payload={"key": "key"})],
        [FakeResponse(status=302, headers={"Location": "https://evil.example/steal"})],
    )
    client = ma.HHMobileClient(session=session)
    with pytest.raises(ma.MobileAuthError, match="внешний адрес"):
        client.create_browser_cookies("oauth", {"id": "42"})


def test_captcha_error_exposes_only_safe_hh_url():
    response = FakeResponse(status=403, payload={"errors": [{
        "type": "captcha_required", "value": "captcha_required",
        "captcha_url": "https://hh.ru/account/captcha?state=test",
    }]})
    error = ma._safe_error(response)
    assert error.captcha_url == "https://hh.ru/account/captcha?state=test"
    assert "CAPTCHA" in str(error)


def test_captcha_error_rejects_external_url():
    response = FakeResponse(status=403, payload={"errors": [{
        "type": "captcha_required", "value": "captcha_required",
        "captcha_url": "https://evil.example/captcha",
    }]})
    assert ma._safe_error(response).captcha_url is None
