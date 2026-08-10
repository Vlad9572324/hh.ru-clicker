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


class _Clock:
    """Детерминированные часы вместо time.time(): now = base + shift."""

    def __init__(self, base: float):
        self.base = float(base)
        self.shift = 0.0

    def time(self) -> float:
        return self.base + self.shift

    def advance(self, seconds: float) -> None:
        self.shift += seconds


def _patch_clock(monkeypatch) -> _Clock:
    """Подменяет time в модуле mobile_auth управляемыми часами."""
    clock = _Clock(int(time.time()))
    monkeypatch.setattr(ma, "time", clock)
    return clock


def _fail_login_times(n: int, monkeypatch_calls: dict) -> None:
    """n неудачных попыток login() до срабатывания lockout."""
    for _ in range(n):
        with pytest.raises(MobileAuthError):
            HHMobileClient().login("0000")
    assert monkeypatch_calls["n"] == n


def test_request_code_during_lockout_is_rejected(otp_env, monkeypatch):
    """HIGH №6: запрос нового кода НЕ сбрасывает активный lockout.

    Цикл «5 попыток -> подождал throttle -> новый код -> ещё 5 попыток»
    больше не обходит 15-минутную блокировку: и немедленный request_code,
    и повторный после resend-throttle (в т.ч. с другим phone/email) дают 429.
    """
    clock = _patch_clock(monkeypatch)
    _write_state(_fresh_state())
    calls = {"n": 0}

    def fake_request(self, method, path, **kwargs):
        calls["n"] += 1
        if path.endswith("/generate"):
            return {"can_request_code_again_in": 30, "code_length": 4}
        raise MobileAuthError("Неверный код подтверждения.")

    monkeypatch.setattr(HHMobileClient, "_request", fake_request)

    # 5 неверных кодов -> lockout на OTP_LOCKOUT_SECONDS.
    _fail_login_times(ma.OTP_MAX_ATTEMPTS, calls)
    locked = _read_state()
    assert locked["attempts"] == ma.OTP_MAX_ATTEMPTS
    assert locked.get("last_lockout_at") == int(clock.time())
    assert locked["locked_until"] > clock.time()

    calls["n"] = 0
    # Немедленный запрос нового кода (тот же phone) — 429 с retry_after.
    with pytest.raises(MobileAuthError) as excinfo:
        HHMobileClient().request_code("+79161234567", "phone")
    assert excinfo.value.status_code == 429
    assert 0 < excinfo.value.retry_after <= ma.OTP_LOCKOUT_SECONDS

    # 60-секундный resend-throttle истёк, а lockout всё ещё действует.
    clock.advance(ma.REQUEST_CODE_THROTTLE_SECONDS + 1)
    with pytest.raises(MobileAuthError) as excinfo:
        HHMobileClient().request_code("+79161234567", "phone")
    assert excinfo.value.status_code == 429

    # Другой phone/email не обходит блокировку — lockout глобальный.
    clock.advance(ma.REQUEST_CODE_THROTTLE_SECONDS + 1)
    with pytest.raises(MobileAuthError) as excinfo:
        HHMobileClient().request_code("+79998887766", "phone")
    assert excinfo.value.status_code == 429
    with pytest.raises(MobileAuthError) as excinfo:
        HHMobileClient().request_code("someone@example.com", "email")
    assert excinfo.value.status_code == 429

    # Итог: к HH не обращались, код не выдан, attempts не сброшены,
    # активный challenge не заменён, lockout не снят.
    assert calls["n"] == 0
    state = _read_state()
    assert state["attempts"] == ma.OTP_MAX_ATTEMPTS
    assert state["login"] == "+79161234567"
    assert state["requested_at"] == locked["requested_at"]
    assert state["last_lockout_at"] == locked["last_lockout_at"]
    assert state["locked_until"] > clock.time()

    # /verify в этом состоянии тоже отдаёт 429 без обращения к HH.
    with pytest.raises(MobileAuthError) as excinfo:
        HHMobileClient().login("0000")
    assert excinfo.value.status_code == 429
    assert calls["n"] == 0


def test_lockout_expires_and_new_code_allowed(otp_env, monkeypatch):
    """После истечения TTL lockout снимается: новый код, attempts=0, вход работает."""
    clock = _patch_clock(monkeypatch)
    _write_state(_fresh_state())
    phase = {"fail_login": True}

    def fake_request(self, method, path, **kwargs):
        if path.endswith("/generate"):
            return {"can_request_code_again_in": 30, "code_length": 4}
        if path.endswith("/login"):
            if phase["fail_login"]:
                raise MobileAuthError("Неверный код подтверждения.")
            return {"access_token": "access", "refresh_token": "refresh", "expires_in": 60}
        if path == "me":
            return {"id": "user-1", "first_name": "Test"}
        if path == "resumes/mine":
            return {"items": []}
        raise AssertionError(f"неожиданный запрос: {path}")

    monkeypatch.setattr(HHMobileClient, "_request", fake_request)
    for _ in range(ma.OTP_MAX_ATTEMPTS):
        with pytest.raises(MobileAuthError):
            HHMobileClient().login("0000")

    # За секунду до конца TTL код всё ещё не выдаётся.
    clock.advance(ma.OTP_LOCKOUT_SECONDS - 1)
    with pytest.raises(MobileAuthError) as excinfo:
        HHMobileClient().request_code("+79161234567", "phone")
    assert excinfo.value.status_code == 429
    assert excinfo.value.retry_after == 1

    # TTL истёк — request_code работает как раньше.
    clock.advance(2)
    phase["fail_login"] = False
    payload = HHMobileClient().request_code("+79161234567", "phone")
    assert payload["code_length"] == 4
    state = _read_state()
    assert state["attempts"] == 0
    assert ma._otp_locked_until(state) == 0, "после TTL lockout должен быть снят"

    # Новый код верифицируется.
    tokens, me, resumes = HHMobileClient().login("5678")
    assert tokens["access_token"] == "access"
    assert me["id"] == "user-1"


def test_throttle_still_works_without_lockout(otp_env, monkeypatch):
    """60-секундный throttle запросов кода работает как раньше, если lockout нет."""
    clock = _patch_clock(monkeypatch)
    calls = {"n": 0}

    def fake_request(self, method, path, **kwargs):
        calls["n"] += 1
        return {"can_request_code_again_in": 30, "code_length": 4}

    monkeypatch.setattr(HHMobileClient, "_request", fake_request)

    assert HHMobileClient().request_code("+79161234567", "phone")

    clock.advance(30)
    with pytest.raises(MobileAuthError) as excinfo:
        HHMobileClient().request_code("+79161234567", "phone")
    assert excinfo.value.status_code == 429
    assert excinfo.value.retry_after == ma.REQUEST_CODE_THROTTLE_SECONDS - 30
    assert calls["n"] == 1, "повторный запрос в throttle-окне не должен доходить до HH"

    clock.advance(31)
    assert HHMobileClient().request_code("+79161234567", "phone")
    assert calls["n"] == 2


def test_lockout_survives_state_rewrite_without_locked_until(otp_env):
    """State с last_lockout_at, но без locked_until, всё равно блокирует выдачу кода."""
    _write_state(_fresh_state(attempts=ma.OTP_MAX_ATTEMPTS,
                              last_lockout_at=int(time.time()) - 60))
    with pytest.raises(MobileAuthError) as excinfo:
        HHMobileClient().request_code("+79161234567", "phone")
    assert excinfo.value.status_code == 429
    assert 0 < excinfo.value.retry_after <= ma.OTP_LOCKOUT_SECONDS


def test_lockout_recognized_from_legacy_locked_until_only(otp_env):
    """Старый state только с locked_until (без last_lockout_at) тоже блокирует."""
    _write_state(_fresh_state(attempts=ma.OTP_MAX_ATTEMPTS,
                              locked_until=int(time.time()) + 600))
    with pytest.raises(MobileAuthError) as excinfo:
        HHMobileClient().request_code("+79161234567", "phone")
    assert excinfo.value.status_code == 429
    assert 595 <= excinfo.value.retry_after <= 600
