"""Tests for storage LRU eviction (job R)."""

import pytest

from app.storage import (
    _INTERVIEWS_MAX,
    _APPLIED_MAX,
    upsert_interview,
    add_applied,
    _cache_interviews,
    _cache_applied,
    _cache_lock,
)


@pytest.fixture(autouse=True)
def isolate_storage_cache(monkeypatch):
    """Reset in-memory caches and suppress async disk writes for isolation."""
    import app.storage as storage

    with storage._cache_lock:
        old_interviews = storage._cache_interviews
        old_applied = storage._cache_applied
        old_tests = storage._cache_tests
        storage._cache_interviews = {}
        storage._cache_applied = {}
        storage._cache_tests = {}

    monkeypatch.setattr(storage, "_schedule_save", lambda fn: None)

    yield

    with storage._cache_lock:
        storage._cache_interviews = old_interviews
        storage._cache_applied = old_applied
        storage._cache_tests = old_tests


def test_upsert_interview_evicts_oldest_at_max_plus_one(monkeypatch):
    import app.storage as storage

    monkeypatch.setattr(storage, "_INTERVIEWS_MAX", 5)
    monkeypatch.setattr(storage, "_INTERVIEWS_EVICT", 1)

    # sentinel records + normal records to hit the cap
    upsert_interview("s1", "acc", llm_sent=True, replied_msg_id="r1")
    upsert_interview("s2", "acc", llm_sent=True, replied_msg_id="r2")
    for i in range(3):
        upsert_interview(str(i), "acc")

    assert len(storage._cache_interviews) == 5

    # 6th record → eviction of oldest non-sentinel
    upsert_interview("new", "acc")
    assert len(storage._cache_interviews) == 5
    assert "s1" in storage._cache_interviews
    assert "s2" in storage._cache_interviews
    assert "new" in storage._cache_interviews
    assert "0" not in storage._cache_interviews


def test_llm_sent_preserved_during_eviction(monkeypatch):
    import app.storage as storage

    monkeypatch.setattr(storage, "_INTERVIEWS_MAX", 4)
    monkeypatch.setattr(storage, "_INTERVIEWS_EVICT", 2)

    # two sentinels + two normals
    upsert_interview("s1", "acc", llm_sent=True, replied_msg_id="r1")
    upsert_interview("s2", "acc", llm_sent=True, replied_msg_id="r2")
    upsert_interview("n1", "acc")
    upsert_interview("n2", "acc")

    # add two more → triggers eviction of 2 oldest non-sentinel
    upsert_interview("n3", "acc")
    upsert_interview("n4", "acc")

    assert "s1" in storage._cache_interviews
    assert "s2" in storage._cache_interviews
    # the normal records may have rotated, but sentinels must survive


def test_add_applied_lru_eviction_by_at_timestamp(monkeypatch):
    import app.storage as storage

    monkeypatch.setattr(storage, "_APPLIED_MAX", 5)
    monkeypatch.setattr(storage, "_APPLIED_EVICT", 1)

    for i in range(5):
        add_applied("acc", str(i), {"title": f"Job {i}"})

    assert len(storage._cache_applied["acc"]) == 5

    # 6th record → oldest by `at` evicted
    add_applied("acc", "5", {"title": "Job 5"})
    assert len(storage._cache_applied["acc"]) == 5
    assert "0" not in storage._cache_applied["acc"]
    assert "5" in storage._cache_applied["acc"]


def test_max_constants_exist():
    assert isinstance(_INTERVIEWS_MAX, int)
    assert isinstance(_APPLIED_MAX, int)
