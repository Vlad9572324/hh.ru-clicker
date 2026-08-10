"""Regression-тесты CRITICAL №1: /api/backup всегда требует X-API-Key.

Бэкап содержит cookies/llm_api_key/oauth-токены — без ключа endpoints должны
отдавать 401 даже когда глобальный HH_BOT_API_KEY не задан. Плюс проверка
web_app._resolve_host: bind наружу без API-key невозможен.
"""
import pytest
from fastapi.testclient import TestClient

import web_app
from app.routes import app

client = TestClient(app)


def _seed_data_files(data_dir):
    """Готовим минимальные data/*.json в tmp, чтобы restore/wipe и live-reload
    (load_accounts) не запускали фоновые записи вне tmp_data_dir."""
    (data_dir / "config.json").write_text("{}", encoding="utf-8")
    (data_dir / "accounts.json").write_text("[]", encoding="utf-8")
    (data_dir / "browser_sessions.json").write_text("[]", encoding="utf-8")


# ─── ключ НЕ задан → backup закрыт полностью ─────────────────────────────────


def test_backup_get_denied_without_key(tmp_data_dir, monkeypatch):
    _seed_data_files(tmp_data_dir)
    monkeypatch.setattr("app.routes._API_KEY", "")
    r = client.get("/api/backup")
    assert r.status_code == 401
    assert r.json().get("ok") is False


def test_backup_post_denied_without_key(tmp_data_dir, monkeypatch):
    _seed_data_files(tmp_data_dir)
    monkeypatch.setattr("app.routes._API_KEY", "")
    r = client.post("/api/backup", json={"config.json": {}})
    assert r.status_code == 401
    assert r.json().get("ok") is False


def test_backup_delete_denied_without_key(tmp_data_dir, monkeypatch):
    _seed_data_files(tmp_data_dir)
    monkeypatch.setattr("app.routes._API_KEY", "")
    r = client.delete("/api/backup")
    assert r.status_code == 401
    assert r.json().get("ok") is False


# ─── ключ задан → без корректного X-API-Key всё равно 401 ────────────────────


def test_backup_get_denied_without_header(tmp_data_dir, monkeypatch):
    _seed_data_files(tmp_data_dir)
    monkeypatch.setattr("app.routes._API_KEY", "s3cret")
    r = client.get("/api/backup")
    assert r.status_code == 401
    assert r.json().get("ok") is False


def test_backup_get_denied_with_wrong_key(tmp_data_dir, monkeypatch):
    _seed_data_files(tmp_data_dir)
    monkeypatch.setattr("app.routes._API_KEY", "s3cret")
    r = client.get("/api/backup", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401
    assert r.json().get("ok") is False


def test_backup_get_allowed_with_correct_key(tmp_data_dir, monkeypatch):
    _seed_data_files(tmp_data_dir)
    monkeypatch.setattr("app.routes._API_KEY", "s3cret")
    r = client.get("/api/backup", headers={"X-API-Key": "s3cret"})
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")


def test_backup_post_allowed_with_correct_key(tmp_data_dir, monkeypatch):
    _seed_data_files(tmp_data_dir)
    monkeypatch.setattr("app.routes._API_KEY", "s3cret")
    r = client.post("/api/backup", json={"config.json": {}},
                    headers={"X-API-Key": "s3cret"})
    assert r.status_code == 200


def test_backup_delete_allowed_with_correct_key(tmp_data_dir, monkeypatch):
    _seed_data_files(tmp_data_dir)
    monkeypatch.setattr("app.routes._API_KEY", "s3cret")
    r = client.delete("/api/backup", headers={"X-API-Key": "s3cret"})
    assert r.status_code == 200


# ─── web_app._resolve_host: наружу только с явного разрешения + API key ─────


def test_resolve_host_unsafe_expose_without_key_raises(monkeypatch):
    """0.0.0.0 + UNSAFE_EXPOSE=1, но API key пуст → RuntimeError (отказ)."""
    monkeypatch.setenv("HH_BOT_HOST", "0.0.0.0")
    monkeypatch.delenv("HH_BOT_API_KEY", raising=False)
    monkeypatch.setenv("HH_BOT_UNSAFE_EXPOSE", "1")
    with pytest.raises(RuntimeError):
        web_app._resolve_host()


def test_resolve_host_unsafe_expose_with_key(monkeypatch):
    """0.0.0.0 + UNSAFE_EXPOSE=1 + API key → bind наружу разрешён."""
    monkeypatch.setenv("HH_BOT_HOST", "0.0.0.0")
    monkeypatch.setenv("HH_BOT_API_KEY", "x")
    monkeypatch.setenv("HH_BOT_UNSAFE_EXPOSE", "1")
    assert web_app._resolve_host() == "0.0.0.0"


def test_resolve_host_default_loopback(monkeypatch):
    """Без HH_BOT_HOST — только loopback."""
    monkeypatch.delenv("HH_BOT_HOST", raising=False)
    monkeypatch.delenv("HH_BOT_UNSAFE_EXPOSE", raising=False)
    assert web_app._resolve_host() == "127.0.0.1"


def test_resolve_host_external_host_without_expose_falls_back(monkeypatch):
    """HH_BOT_HOST=0.0.0.0, key задан, но UNSAFE_EXPOSE пуст → fallback 127.0.0.1."""
    monkeypatch.setenv("HH_BOT_HOST", "0.0.0.0")
    monkeypatch.setenv("HH_BOT_API_KEY", "x")
    monkeypatch.delenv("HH_BOT_UNSAFE_EXPOSE", raising=False)
    assert web_app._resolve_host() == "127.0.0.1"
