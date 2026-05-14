"""Тесты на WS Origin check (CSWSH защита, R3).

Bind на 127.0.0.1 не спасает от того что произвольный сайт в браузере юзера
откроет ws://localhost:8000/ws и угонит бота.
"""
import os

import pytest

from app.routes.core import _ws_origin_allowed


def test_origin_localhost_allowed():
    assert _ws_origin_allowed("http://localhost:8000") is True
    assert _ws_origin_allowed("http://127.0.0.1:8000") is True
    assert _ws_origin_allowed("https://127.0.0.1") is True


def test_origin_empty_allowed():
    """curl/python-ws-клиенты не шлют Origin — пускаем (браузер всегда выставит)."""
    assert _ws_origin_allowed("") is True


def test_origin_external_rejected():
    assert _ws_origin_allowed("https://attacker.com") is False
    assert _ws_origin_allowed("http://evil.example") is False


def test_origin_malformed_rejected():
    assert _ws_origin_allowed("not-a-url") is False


def test_origin_extra_via_env(monkeypatch):
    """HH_BOT_ALLOWED_ORIGINS позволяет добавить LAN-хосты для bind 0.0.0.0."""
    monkeypatch.setenv("HH_BOT_ALLOWED_ORIGINS", "192.168.1.100, mybox.local")
    assert _ws_origin_allowed("http://192.168.1.100:8000") is True
    assert _ws_origin_allowed("http://mybox.local") is True
    # А внешний всё ещё блокируется
    assert _ws_origin_allowed("https://attacker.com") is False


def test_origin_extra_origins_isolated(monkeypatch):
    """Без env переменной — только loopback."""
    monkeypatch.delenv("HH_BOT_ALLOWED_ORIGINS", raising=False)
    assert _ws_origin_allowed("http://192.168.1.100") is False
