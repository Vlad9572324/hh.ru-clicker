from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
import random

import pytest

from app import human_pace as pace
from app.config import CONFIG, _CONFIG_KEYS, config_snapshot


@pytest.fixture(autouse=True)
def defaults(monkeypatch):
    monkeypatch.setattr(CONFIG, 'human_mode_enabled', True)
    monkeypatch.setattr(CONFIG, 'human_active_hours', '07-24')
    monkeypatch.setattr(CONFIG, 'human_captcha_backoff_hours', 2)
    monkeypatch.setattr(pace, '_rng', random.Random(17))


def freeze(monkeypatch, value):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return value
    monkeypatch.setattr(pace, 'datetime', Clock)


def test_random_ranges_and_rare_reading_pause():
    delays = [pace.random_apply_delay() for _ in range(2000)]
    assert all(5 <= d <= 60 for d in delays)
    assert any(30 <= d <= 60 for d in delays)
    assert all(d <= 20 or d >= 30 for d in delays)
    assert {pace.random_burst_size() for _ in range(200)} == set(range(3, 9))
    pauses = [pace.random_burst_pause() for _ in range(2000)]
    assert all(180 <= p <= 480 or 600 <= p <= 1200 for p in pauses)
    assert any(p >= 600 for p in pauses)


@pytest.mark.parametrize('hours,hour,expected', [
    ('07-24', 8, True), ('07-24', 3, False), ('07-24', 7, True),
    ('22-06', 23, True), ('22-06', 5, True), ('22-06', 15, False),
    ('22-06', 6, False), ('00-24', 0, True), ('22-00', 0, False),
    ('07-07', 7, False), ('25-26', 8, False), ('invalid', 8, False),
])
def test_active_hours(monkeypatch, hours, hour, expected):
    monkeypatch.setattr(CONFIG, 'human_active_hours', hours)
    freeze(monkeypatch, datetime(2026, 9, 24, hour, 30))
    assert pace.is_active_hour() is expected


@pytest.mark.parametrize('age,expected', [(60, 2), (7199, 2), (7200, 1), (10000, 1)])
def test_backoff(monkeypatch, age, expected):
    monkeypatch.setattr(pace.time, 'time', lambda: 20000)
    assert pace.adaptive_backoff_multiplier(SimpleNamespace(_last_captcha_at=20000-age)) == expected
    assert pace.adaptive_backoff_multiplier(SimpleNamespace(acc={'_last_captcha_at': 20000-age})) == expected
    assert pace.adaptive_backoff_multiplier(SimpleNamespace()) == 1


@pytest.mark.parametrize('day,expected', [(25, 1), (26, .7), (27, .7), (28, 1)])
def test_weekend(monkeypatch, day, expected):
    freeze(monkeypatch, datetime(2026, 9, day))
    assert pace.weekend_variance() == expected


def test_wait_until_window_and_shutdown(monkeypatch):
    freeze(monkeypatch, datetime(2026, 9, 24, 6, 59, 45))
    stop = Mock()
    stop.is_set.return_value = False
    def wait(seconds):
        assert seconds == 15
        freeze(monkeypatch, datetime(2026, 9, 24, 7))
        return False
    stop.wait.side_effect = wait
    pace.sleep_until_active_hour(SimpleNamespace(), stop)
    stop.wait.assert_called_once_with(15)
    freeze(monkeypatch, datetime(2026, 9, 24, 3))
    stop.wait.side_effect = None
    stop.wait.return_value = True
    pace.sleep_until_active_hour(SimpleNamespace(), stop)
    assert stop.wait.call_args.args == (60,)


def test_config_exposed():
    assert set(pace.HUMAN_CONFIG_KEYS) <= set(_CONFIG_KEYS)
    assert set(pace.HUMAN_CONFIG_KEYS) <= set(config_snapshot())
