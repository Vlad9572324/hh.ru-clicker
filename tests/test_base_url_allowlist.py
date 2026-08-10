"""Regression-тесты CRITICAL №2: allowlist base_url мобильного API.

base_url обязан указывать строго на api.hh.ru / *.hh.ru / *.hh.kz:
похожие домены (hh.ru.attacker.com, evilhh.ru, attacker-hh.ru), userinfo,
не-443 порты, пути и query — отклоняются с MobileAuthError.
"""
import pytest
from fastapi.testclient import TestClient

from app import mobile_auth as ma
from app.mobile_auth import MobileAuthError, validate_base_url
from app.routes import app

client = TestClient(app)

ACCEPTED = [
    ("https://api.hh.ru", "https://api.hh.ru"),
    ("https://api.hh.ru/", "https://api.hh.ru"),  # нормализация trailing slash
    ("https://sub.hh.ru", "https://sub.hh.ru"),
    ("https://foo.hh.kz", "https://foo.hh.kz"),
    ("https://api.hh.ru:443", "https://api.hh.ru"),  # порт 443 → нормализуется
]

REJECTED = [
    "https://hh.ru.attacker.com",   # суффикс на границе без точки
    "https://attacker-hh.ru",       # дефис, не поддомен
    "https://evilhh.ru",            # склейка имени
    "https://user@api.hh.ru",       # userinfo
    "https://user:pass@api.hh.ru",  # userinfo с паролем
    "http://api.hh.ru",             # не-https
    "https://api.hh.ru/path",       # путь
    "https://api.hh.ru:8443",       # произвольный порт
    "https://api.hh.ru?x=1",        # query
    "",                             # пусто
    "api.hh.ru",                    # без схемы
]


@pytest.mark.parametrize("raw,expected", ACCEPTED)
def test_validate_base_url_accepts(raw, expected):
    assert validate_base_url(raw) == expected


@pytest.mark.parametrize("raw", REJECTED)
def test_validate_base_url_rejects(raw):
    with pytest.raises(MobileAuthError):
        validate_base_url(raw)


def test_save_config_rejects_foreign_base_url(tmp_data_dir, monkeypatch):
    """Через конфиг-путь: save_config с чужим доменом падает с MobileAuthError."""
    monkeypatch.delenv("HH_API_BASE_URL", raising=False)
    ma._web_overrides.clear()
    ma.effective_config.cache_clear()
    try:
        with pytest.raises(MobileAuthError):
            ma.save_config({"base_url": "https://hh.ru.attacker.com"})
    finally:
        # Не оставляем кэш с результатами из этого теста другим тестам.
        ma.effective_config.cache_clear()


def test_put_settings_rejects_foreign_base_url(tmp_data_dir, monkeypatch):
    """Через HTTP: PUT /api/mobile-auth/settings → 400 и ok:false."""
    # Детерминизм: auth middleware не должна вмешиваться в этот тест.
    monkeypatch.setattr("app.routes._API_KEY", "")
    monkeypatch.delenv("HH_API_BASE_URL", raising=False)
    ma._web_overrides.clear()
    ma.effective_config.cache_clear()
    try:
        r = client.put(
            "/api/mobile-auth/settings",
            json={"values": {"base_url": "https://hh.ru.attacker.com"}},
        )
        assert r.status_code == 400
        assert r.json().get("ok") is False
    finally:
        ma.effective_config.cache_clear()
