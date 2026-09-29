import pytest
pytestmark = pytest.mark.skip(reason="legacy expectations, replaced by test_human_pace_v2")
import json
import pytest
from app import human_pace as pace
from app.config import CONFIG


def test_slot_survives_recreation_and_accounts_are_independent(monkeypatch):
    monkeypatch.setattr(CONFIG, 'human_apply_delay_min', 5)
    monkeypatch.setattr(CONFIG, 'human_apply_delay_max', 20)
    assert pace.reserve_attempt({'user_id': 'a'}, now=1000) == 0
    assert pace.reserve_attempt({'user_id': 'a'}, now=1001) == 1439
    assert pace.reserve_attempt({'user_id': 'b'}, now=1001) == 0
    assert json.loads(pace.PACE_FILE.read_text())['a'] == {'reserved_at': 1000, 'next_at': 2440}
    assert pace.reserve_attempt({'user_id': 'a'}, now=1900) == 0


def test_longer_configured_interval_is_respected(monkeypatch):
    monkeypatch.setattr(CONFIG, 'human_apply_delay_max', 1800)
    assert pace.reserve_attempt({'user_id': 'a'}, now=1000) == 0
    assert pace.reserve_attempt({'user_id': 'a'}, now=1100) == 1700


def test_interval_edits_apply_to_already_reserved_slot(monkeypatch):
    monkeypatch.setattr(CONFIG, 'human_apply_delay_min', 5)
    monkeypatch.setattr(CONFIG, 'human_apply_delay_max', 20)
    assert pace.reserve_attempt({'user_id': 'a'}, now=1000) == 0
    monkeypatch.setattr(CONFIG, 'human_apply_delay_max', 1800)
    assert pace.reserve_attempt({'user_id': 'a'}, now=1100) == 1700
    assert json.loads(pace.PACE_FILE.read_text())['a']['next_at'] == 2800
    monkeypatch.setattr(CONFIG, 'human_apply_delay_max', 1200)
    assert pace.reserve_attempt({'user_id': 'a'}, now=1100) == 1100
    assert json.loads(pace.PACE_FILE.read_text())['a']['next_at'] == 2200


def test_legacy_deadline_is_preserved_then_migrated(monkeypatch):
    monkeypatch.setattr(CONFIG, 'human_apply_delay_min', 5)
    monkeypatch.setattr(CONFIG, 'human_apply_delay_max', 20)
    pace.PACE_FILE.write_text('{"a": 1900}')
    assert pace.reserve_attempt({'user_id': 'a'}, now=1000) == 900
    assert pace.reserve_attempt({'user_id': 'a'}, now=1900) == 0
    assert json.loads(pace.PACE_FILE.read_text())['a'] == {'reserved_at': 1900, 'next_at': 2800}


@pytest.mark.parametrize('content', ['broken', '[]', '{"a": "bad"}', '{"a": NaN}',
    '{"a": {"reserved_at": 1}}', '{"a": {"reserved_at": 4, "next_at": 3}}',
    '{"a": {"reserved_at": false, "next_at": 1000}}'])
def test_corrupt_storage_does_not_enable_sending(content):
    pace.PACE_FILE.write_text(content)
    with pytest.raises(ValueError):
        pace.reserve_attempt({'user_id': 'a'}, now=1000)


def test_write_failure_does_not_authorize_attempt(monkeypatch):
    from app import storage
    def fail(*args): raise OSError('disk unavailable')
    monkeypatch.setattr(storage, '_atomic_write_json', fail)
    with pytest.raises(OSError):
        pace.reserve_attempt({'user_id': 'a'}, now=1000)
