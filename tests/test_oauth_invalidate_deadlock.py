"""Regression: issue #19 — invalidate_oauth_token → _save_oauth_tokens
deadlock (оба брали _oauth_lock, threading.Lock не re-entrant, поток
вешался навсегда → зависал весь бэк). Проверяем что invalidate возвращает
управление за разумное время и корректно чистит токен."""
import threading
from unittest.mock import patch

from app import oauth


def test_invalidate_oauth_token_does_not_deadlock(tmp_path, monkeypatch):
    # Изолируем storage чтобы реальный oauth_tokens.json не тронуть.
    monkeypatch.setattr(oauth, "_OAUTH_FILE", tmp_path / "oauth.json")
    monkeypatch.setattr(oauth, "_oauth_tokens", {
        "abc123": {"access_token": "T1"},
        "abc123::compkey": {"access_token": "T2"},
    })

    done = threading.Event()

    def _run():
        oauth.invalidate_oauth_token("abc123", acc=None)
        done.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    # До фикса поток вис навсегда — на _save_oauth_tokens пытавшемся
    # взять _oauth_lock повторно. 3 сек с большим запасом.
    assert done.wait(timeout=3.0), "invalidate_oauth_token завис — deadlock не пофикшен"
    assert "abc123" not in oauth._oauth_tokens
    assert "abc123::compkey" not in oauth._oauth_tokens


def test_invalidate_no_ops_on_empty_hash(monkeypatch):
    """Пустой resume_hash → быстрый ранний return, без побочек."""
    called = []
    monkeypatch.setattr(oauth, "_save_oauth_tokens", lambda: called.append(1))
    oauth.invalidate_oauth_token("", acc=None)
    assert called == []
