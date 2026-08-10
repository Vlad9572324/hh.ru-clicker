"""Edge-case тесты get_client() factory (Phase 0).

Покрывают нормализацию account["mode"] и семантику get_client:
  - нет mode → CONFIG.default_client_mode;
  - не-str mode → "auto"; strip().lower();
  - mode вне {web, mobile, auto} → CONFIG.default_client_mode → fallback "web";
  - "auto" → всегда WebHHClient (решение Phase 0, docs/PHASE_MATRIX.md:
    mobile-клиент не готов, авто-выбор не должен приводить к mobile даже
    при живом OAuth-токене); явный "mobile" → MobileHHClient без токена.

Каждый тест явно monkeypatch'ит CONFIG.default_client_mode и состояние
oauth-хранилища, чтобы не зависеть от дефолтов и data/oauth_tokens.json.
"""
import time

import pytest

from app import oauth
from app.config import CONFIG
from app.hh_client_factory import get_client
from app.hh_client_mobile import MobileHHClient
from app.hh_client_web import WebHHClient


def _acc(**extra) -> dict:
    acc = {"name": "edge-acc", "cookies": {}, "resume_hash": "rh1"}
    acc.update(extra)
    return acc


def _isolate(monkeypatch, default_mode: str, tokens: dict = None) -> None:
    """Изолировать CONFIG.default_client_mode и in-memory oauth-токены."""
    monkeypatch.setattr(CONFIG, "default_client_mode", default_mode)
    monkeypatch.setattr(oauth, "_oauth_tokens", {} if tokens is None else tokens)


# ── 1. Аккаунт без "mode": решает CONFIG.default_client_mode ────────────────


def test_missing_mode_default_web(monkeypatch):
    _isolate(monkeypatch, "web")
    assert isinstance(get_client(_acc()), WebHHClient)


def test_missing_mode_default_mobile(monkeypatch):
    _isolate(monkeypatch, "mobile")
    assert isinstance(get_client(_acc()), MobileHHClient)


def test_missing_mode_default_auto_phase0_web(monkeypatch):
    _isolate(monkeypatch, "auto")
    assert isinstance(get_client(_acc()), WebHHClient)


# ── 2. Whitespace / регистр нормализуются ────────────────────────────────────


def test_mode_whitespace_uppercase_mobile(monkeypatch):
    _isolate(monkeypatch, "web")
    assert isinstance(get_client(_acc(mode="  MOBILE  ")), MobileHHClient)


def test_mode_mixedcase_web(monkeypatch):
    _isolate(monkeypatch, "mobile")
    assert isinstance(get_client(_acc(mode="Web")), WebHHClient)


# ── 3. Неизвестный mode → CONFIG.default_client_mode → fallback "web" ───────


def test_unknown_mode_falls_to_default_web(monkeypatch):
    _isolate(monkeypatch, "web")
    assert isinstance(get_client(_acc(mode="desktop")), WebHHClient)


def test_unknown_mode_garbage_default_final_fallback_web(monkeypatch):
    # Даже если default_client_mode сам по себе мусор — финальный fallback "web".
    _isolate(monkeypatch, "garbage!!")
    assert isinstance(get_client(_acc(mode="desktop")), WebHHClient)


# ── 4. Не-str mode → "auto" → web (Phase 0), без исключений ─────────────────


@pytest.mark.parametrize("bad_mode", [5, True, None])
def test_non_string_mode_becomes_auto_phase0_web(monkeypatch, bad_mode):
    # default намеренно "mobile": контракт «не-str → auto», а НЕ «не-str → default».
    # Если реализация уронит не-str в default — вернётся MobileHHClient и тест упадёт.
    _isolate(monkeypatch, "mobile")
    client = get_client(_acc(mode=bad_mode))
    assert isinstance(client, WebHHClient)


# ── 5. Пустой resume_hash + auto: не падает ──────────────────────────────────


def test_auto_empty_resume_hash_web(monkeypatch):
    _isolate(monkeypatch, "web")
    assert isinstance(get_client(_acc(mode="auto", resume_hash="")), WebHHClient)


# ── 6. "auto": решение Phase 0 — всегда web, независимо от токена ───────────


def test_p1_auto_live_token_stays_web(monkeypatch):
    # Решение Phase 0 (docs/PHASE_MATRIX.md): "auto" → WebHHClient даже при
    # живом OAuth-токене; mobile — только при явном mode="mobile".
    _isolate(
        monkeypatch,
        "web",
        tokens={"rh1": {"access_token": "t", "expires_at": time.time() + 3600}},
    )
    assert isinstance(get_client(_acc(mode="auto")), WebHHClient)


def test_p1_auto_expired_token_stays_web(monkeypatch):
    _isolate(
        monkeypatch,
        "web",
        tokens={"rh1": {"access_token": "t", "expires_at": time.time() - 3600}},
    )
    assert isinstance(get_client(_acc(mode="auto")), WebHHClient)


def test_p1_auto_status_without_has_token_stays_web(monkeypatch):
    # auto → web при любом oauth-состоянии (фабрика в Phase 0 не смотрит
    # на токены); подмена get_oauth_status — страховка от регресса к старой
    # token-based семантике.
    _isolate(monkeypatch, "web")
    monkeypatch.setattr(oauth, "get_oauth_status", lambda resume_hash: {})
    assert isinstance(get_client(_acc(mode="auto")), WebHHClient)


def test_p1_explicit_mobile_without_any_token_is_mobile(monkeypatch):
    # Контроль: явный mobile не зависит от токена вообще.
    _isolate(monkeypatch, "web")
    assert isinstance(get_client(_acc(mode="mobile")), MobileHHClient)
