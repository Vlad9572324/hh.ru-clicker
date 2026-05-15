"""Tests for app.oauth._token_key composite key logic."""
import app.oauth as oauth_mod


def test_same_acc_same_key():
    acc = {"resume_hash": "abc", "cookies": {"hhtoken": "tok1"}}
    assert oauth_mod._token_key(acc) == oauth_mod._token_key(acc)


def test_different_hhtoken_different_key():
    acc1 = {"resume_hash": "abc", "cookies": {"hhtoken": "tok1"}}
    acc2 = {"resume_hash": "abc", "cookies": {"hhtoken": "tok2"}}
    assert oauth_mod._token_key(acc1) != oauth_mod._token_key(acc2)


def test_empty_resume_hash_returns_empty():
    assert oauth_mod._token_key({"cookies": {"hhtoken": "x"}}) == ""


def test_plain_resume_hash_readable(monkeypatch):
    monkeypatch.setattr(
        oauth_mod, "_oauth_tokens", {"abc": {"access_token": "x", "expires_at": 9999999999}}
    )
    status = oauth_mod.get_oauth_status("abc")
    assert status["has_token"] is True
