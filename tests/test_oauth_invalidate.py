"""Tests for OAuth token invalidation and refresh-lock dedup."""
from unittest.mock import patch

import app.oauth as oauth_mod


def test_invalidate_purges_existing_key(monkeypatch):
    monkeypatch.setattr(oauth_mod, "_oauth_tokens", {"hash1": {"token": "x"}})
    with patch.object(oauth_mod, "_save_oauth_tokens"):
        oauth_mod.invalidate_oauth_token("hash1")
    assert "hash1" not in oauth_mod._oauth_tokens


def test_invalidate_noop_on_missing_key(monkeypatch):
    monkeypatch.setattr(oauth_mod, "_oauth_tokens", {"hash1": {"token": "x"}})
    with patch.object(oauth_mod, "_save_oauth_tokens") as mock_save:
        oauth_mod.invalidate_oauth_token("hash2")
    mock_save.assert_not_called()
    assert "hash1" in oauth_mod._oauth_tokens


def test_invalidate_noop_on_empty_hash(monkeypatch):
    monkeypatch.setattr(oauth_mod, "_oauth_tokens", {"hash1": {"token": "x"}})
    with patch.object(oauth_mod, "_save_oauth_tokens") as mock_save:
        oauth_mod.invalidate_oauth_token("")
    mock_save.assert_not_called()
    assert "hash1" in oauth_mod._oauth_tokens


def test_get_refresh_lock_same_key_same_lock_different_keys_different_locks():
    lock_a1 = oauth_mod._get_refresh_lock("a")
    lock_a2 = oauth_mod._get_refresh_lock("a")
    lock_b = oauth_mod._get_refresh_lock("b")
    assert lock_a1 is lock_a2
    assert lock_a1 is not lock_b
