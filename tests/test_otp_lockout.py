"""Regression-тесты HIGH №6: защита OTP-входа от перебора и rate-limit.

Lockout после 5 неудач, TTL протухшего state, throttle повторного запроса
кода, дневной лимит запросов кода. Все проверки локальные — без сети.
"""
import json
import time
from datetime import date

import pytest

from app import mobile_auth as ma
from app.mobile_auth import HHMobileClient, MobileAuthError


@pytest.fixture
def otp_env(tmp_data_dir):
    """tmp cwd (data/ в tmp) + очистка STATE_FILE после теста."""
    yield
    ma.STATE_FILE.unlink(missing_ok=True)


def _write_state(state: dict):
    ma._atomic_write(ma.STATE_FILE, state)


def _read_state() -> dict:
    return json.loads(ma.STATE_FILE.read_text(encoding="utf-8"))


def _fresh_state(**extra) -> dict:
    state = {
        "login": "+79161234567",
        "login_type": "phone",
        "requested_at": int(time.time()),
        "retry_after": 0,
        "code_length": 4,
    }
    state.update(extra)
    return state


def test_otp_constants():
    assert ma.OTP_MAX_ATTEMPTS == 5
    assert ma.OTP_LOCKOUT_SECONDS == 900
    assert ma.OTP_STATE_TTL_SECONDS == 300
    assert ma.REQUEST_CODE_THROTTLE_SECONDS == 60
    assert ma.REQUEST_CODE_DAILY_LIMIT == 10


def test_lockout_after_five_failed_attempts(otp_env, monkeypatch):
    _write_state(_fresh_state())
    calls = {"n": 0}

    def fake_request(self, method, path, **kwargs):
        calls["n"] += 1
        raise MobileAuthError("Неверный код подтверждения.")

    monkeypatch.setattr(HHMobileClient, "_request", fake_request)

    # 5 неудачных попыток — каждая доходит до HH (мок) и получает 400.
    for _ in range(ma.OTP_MAX_ATTEMPTS):
        with pytest.raises(MobileAuthError) as excinfo:
            HHMobileClient().login("1234")
        assert excinfo.value.status_code == 400
    assert calls["n"] == ma.OTP_MAX_ATTEMPTS

    # 6-я попытка — локальный lockout 429, запрос к HH НЕ уходит.
    before = calls["n"]
    with pytest.raises(MobileAuthError) as excinfo:
        HHMobileClient().login("1234")
    assert excinfo.value.status_code == 429
    assert calls["n"] == before, "после lockout обращения к HH быть не должно"

    # Lockout зафиксирован на диске.
    assert _read_state().get("locked_until", 0) > time.time()


def test_stale_state_returns_410(otp_env, monkeypatch):
    """State старше OTP_STATE_TTL_SECONDS → 410 Gone, код принимать нельзя."""
    _write_state(_fresh_state(requested_at=int(time.time()) - 400))

    def fake_request(self, method, path, **kwargs):
        raise AssertionError("после истечения TTL запрос к HH запрещён")

    monkeypatch.setattr(HHMobileClient, "_request", fake_request)
    with pytest.raises(MobileAuthError) as excinfo:
        HHMobileClient().login("1234")
    assert excinfo.value.status_code == 410


def test_request_code_throttle(otp_env, monkeypatch):
    """Повторный /request-code раньше throttle-окна → 429 без обращения к HH."""
    calls = {"n": 0}

    def fake_request(self, method, path, **kwargs):
        calls["n"] += 1
        return {"can_request_code_again_in": 30, "code_length": 4}

    monkeypatch.setattr(HHMobileClient, "_request", fake_request)

    result = HHMobileClient().request_code("+79161234567", "phone")
    assert result.get("can_request_code_again_in") == 30

    with pytest.raises(MobileAuthError) as excinfo:
        HHMobileClient().request_code("+79161234567", "phone")
    assert excinfo.value.status_code == 429
    assert calls["n"] == 1, "второй запрос кода должен быть заблокирован локально"


def test_request_code_daily_limit(otp_env, monkeypatch):
    """REQUEST_CODE_DAILY_LIMIT исчерпан за сегодня → 429."""
    _write_state(_fresh_state(
        requested_at=int(time.time()) - 3600,
        request_day=date.today().isoformat(),
        request_count=10,
    ))
    calls = {"n": 0}

    def fake_request(self, method, path, **kwargs):
        calls["n"] += 1
        return {"can_request_code_again_in": 30, "code_length": 4}

    monkeypatch.setattr(HHMobileClient, "_request", fake_request)
    with pytest.raises(MobileAuthError) as excinfo:
        HHMobileClient().request_code("+79161234567", "phone")
    assert excinfo.value.status_code == 429
    assert calls["n"] == 0, "при исчерпанном дневном лимите обращения к HH быть не должно"


def test_auth_status_does_not_leak_code_length(otp_env):
    """auth_status() не раскрывает code_length из state."""
    _write_state(_fresh_state(code_length=4))
    status = ma.auth_status()
    assert status.get("stage") == "code_requested"
    assert "code_length" not in status
