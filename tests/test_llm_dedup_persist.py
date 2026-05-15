"""Тесты на персистентность LLM dedup — фикс C4.

Без этого фикса после рестарта бот мог повторно отвечать в каждой беседе,
где последнее сообщение от работодателя.
"""
import importlib

import pytest


@pytest.fixture
def fresh_storage(tmp_path, monkeypatch):
    """Изолированная storage с tmp-данными — patched _cache_* + INTERVIEWS_FILE."""
    monkeypatch.chdir(tmp_path)
    # Re-import storage, чтобы DATA_DIR смотрел на cwd=tmp_path.
    import app.storage as storage
    importlib.reload(storage)
    # Сбросим все кэши на свежем модуле — _load_cache работает с None-сентинелями.
    storage._cache_interviews = None
    storage._cache_applied = None
    storage._cache_tests = None
    storage._cache_answer_history = None
    yield storage


def test_replied_msg_id_persisted_via_upsert(fresh_storage):
    storage = fresh_storage
    # Записываем ответ + replied_msg_id
    storage.upsert_interview(
        "neg123", acc="acc1", llm_sent=True, replied_msg_id="msg_abc",
    )
    # Должно вернуться через get_replied_keys
    keys = storage.get_replied_keys()
    assert ("neg123", "msg_abc") in keys


def test_unsent_interview_not_in_replied_keys(fresh_storage):
    """llm_sent=False → не должен попасть в dedup-сет (это черновик)."""
    storage = fresh_storage
    storage.upsert_interview("neg999", acc="a", llm_sent=False, replied_msg_id="m1")
    keys = storage.get_replied_keys()
    assert ("neg999", "m1") not in keys


def test_interview_without_replied_msg_id_legacy_sentinel(fresh_storage):
    """Старые записи без replied_msg_id (legacy) получают sentinel '__legacy__'
    чтобы не переотправить ответ при upgrade (r12-2 #3)."""
    storage = fresh_storage
    storage.upsert_interview("neg_old", acc="a", llm_sent=True)
    keys = storage.get_replied_keys()
    assert ("neg_old", "__legacy__") in keys


def test_multiple_interviews_aggregated(fresh_storage):
    storage = fresh_storage
    storage.upsert_interview("n1", acc="a", llm_sent=True, replied_msg_id="m1")
    storage.upsert_interview("n2", acc="b", llm_sent=True, replied_msg_id="m2")
    storage.upsert_interview("n3", acc="c", llm_sent=False, replied_msg_id="m3")  # черновик
    keys = storage.get_replied_keys()
    assert ("n1", "m1") in keys
    assert ("n2", "m2") in keys
    assert ("n3", "m3") not in keys  # llm_sent=False


def test_upsert_never_downgrades_llm_sent(fresh_storage):
    """Регресс: повторный upsert с llm_sent=False не должен сбрасывать True."""
    storage = fresh_storage
    storage.upsert_interview("n1", acc="a", llm_sent=True, replied_msg_id="m1")
    storage.upsert_interview("n1", acc="a", llm_sent=False)  # попытка downgrade
    keys = storage.get_replied_keys()
    assert ("n1", "m1") in keys, "llm_sent=True должен быть sticky"


def test_replied_msg_id_str_coerced(fresh_storage):
    """replied_msg_id может прилететь как int — должен сохраниться как str."""
    storage = fresh_storage
    storage.upsert_interview("n1", acc="a", llm_sent=True, replied_msg_id=12345)
    keys = storage.get_replied_keys()
    assert ("n1", "12345") in keys
