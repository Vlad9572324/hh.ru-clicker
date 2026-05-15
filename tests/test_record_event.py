"""Tests for app.storage.record_event (job R)."""

import json

from app.storage import record_event


def test_record_event_writes_one_json_line(monkeypatch, tmp_data_dir):
    import app.storage as storage

    events_file = tmp_data_dir / "events.jsonl"
    monkeypatch.setattr(storage, "EVENTS_FILE", events_file)
    monkeypatch.setattr(storage, "_schedule_save", lambda fn: fn())

    record_event("test_event", foo="bar")

    content = events_file.read_text(encoding="utf-8")
    lines = [l for l in content.strip().split("\n") if l]
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["kind"] == "test_event"
    assert event["foo"] == "bar"
    assert "ts" in event


def test_record_event_multiple_calls_append(monkeypatch, tmp_data_dir):
    import app.storage as storage

    events_file = tmp_data_dir / "events.jsonl"
    monkeypatch.setattr(storage, "EVENTS_FILE", events_file)
    monkeypatch.setattr(storage, "_schedule_save", lambda fn: fn())

    record_event("event_a", x=1)
    record_event("event_b", x=2)

    content = events_file.read_text(encoding="utf-8")
    lines = [l for l in content.strip().split("\n") if l]
    assert len(lines) == 2
    assert json.loads(lines[0])["kind"] == "event_a"
    assert json.loads(lines[1])["kind"] == "event_b"
