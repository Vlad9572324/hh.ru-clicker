"""Regression-тесты CRITICAL №4: propagation refresh-токена после ротации.

HH ротирует refresh_token при каждом refresh. Если один refresh_token shared
несколькими записями (plain-ключи + composite-ключи одного аккаунта), после
refresh ВСЕ они должны получить новый токен — иначе «отставшие» записи
останутся с мёртвым R1 и следующий запрос упадёт/сделает лишний refresh.
"""
import time

import pytest

import app.oauth as oauth_mod


@pytest.fixture
def oauth_tokens_scope(tmp_data_dir):
    """Подменяем модульный dict токенов и возвращаем оригинал в конце.

    tmp_data_dir гарантирует, что _save_oauth_tokens() пишет в tmp/data/.
    """
    original = oauth_mod._oauth_tokens
    try:
        yield
    finally:
        oauth_mod._oauth_tokens = original


def _seed_shared_refresh_token():
    now = int(time.time())

    def entry():
        return {
            "access_token": "A1",
            "refresh_token": "R1",
            "expires_at": now - 100,  # просрочен → proactive refresh обязан сработать
            "source": "mobile_otp",
        }

    oauth_mod._oauth_tokens = {
        "r1": entry(),
        "r2": entry(),
        "r1::acc1": entry(),
    }


def test_proactive_refresh_propagates_rotated_token(oauth_tokens_scope, monkeypatch):
    _seed_shared_refresh_token()
    monkeypatch.setattr(
        oauth_mod, "_do_refresh",
        lambda *a, **k: {"access_token": "A2", "refresh_token": "R2", "expires_in": 1209599},
    )

    stats = oauth_mod.refresh_oauth_tokens_proactive(min_ttl_hours=48)

    assert stats["refreshed"] >= 1
    tokens = oauth_mod._oauth_tokens
    # Дубликатов не появилось: те же 3 ключа.
    assert len(tokens) == 3
    for key in ("r1", "r2", "r1::acc1"):
        assert key in tokens
        assert tokens[key]["refresh_token"] == "R2", f"{key} не получил новый refresh_token"
        assert tokens[key]["access_token"] == "A2", f"{key} не получил новый access_token"
    # Нигде не остался мёртвый R1.
    assert all(
        v.get("refresh_token") != "R1"
        for v in tokens.values()
        if isinstance(v, dict)
    )


def test_propagate_refresh_token_helper(oauth_tokens_scope):
    """Хелпер _propagate_refresh_token: обновляет все matching-записи,
    возвращает их число; plain-ключи не получают служебные поля на '_'."""
    propagate = getattr(oauth_mod, "_propagate_refresh_token", None)
    if propagate is None:
        pytest.skip("app.oauth._propagate_refresh_token ещё не реализован")

    now = int(time.time())
    new_full = {
        "access_token": "A2",
        "refresh_token": "R2",
        "expires_at": now + 100000,
        "_expires_monotonic": time.monotonic() + 100000,
    }
    oauth_mod._oauth_tokens = {
        "a": {"access_token": "A1", "refresh_token": "R1", "expires_at": now - 10},
        "b::acc": {"access_token": "A1", "refresh_token": "R1", "expires_at": now - 10},
        "c": {"access_token": "AX", "refresh_token": "RX", "expires_at": now + 5000},
    }

    updated = propagate("R1", dict(new_full))

    assert updated == 2
    tokens = oauth_mod._oauth_tokens
    assert tokens["a"]["refresh_token"] == "R2"
    assert tokens["a"]["access_token"] == "A2"
    assert tokens["b::acc"]["refresh_token"] == "R2"
    # Не matching запись не тронута.
    assert tokens["c"]["refresh_token"] == "RX"
    assert tokens["c"]["access_token"] == "AX"
    # plain-ключ (без "::") — публичный вид: никаких служебных полей на "_".
    assert not any(k.startswith("_") for k in tokens["a"])
