from unittest.mock import Mock

import pytest
from app import telegram_alerts as alerts


@pytest.fixture(autouse=True)
def clean_window(monkeypatch):
    monkeypatch.setattr(alerts, '_windows', alerts.defaultdict(alerts.deque))
    monkeypatch.setattr(alerts.CONFIG, 'tg_alert_hr_question_enabled', True)


def test_sliding_window_and_account_isolation(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(alerts.time, 'monotonic', lambda: now[0])
    send = Mock(return_value=True)
    monkeypatch.setattr(alerts.telegram_notify, 'send_once', send)
    for i in range(20):
        assert alerts.send_alert('hr_question', f'message:A:{i}', 'question')
    assert not alerts.send_alert('hr_question', 'message:A:21', 'question')
    assert send.call_count == 20
    assert alerts.send_alert('hr_question', 'message:B:21', 'question')
    now[0] += 3600
    assert alerts.send_alert('hr_question', 'message:A:21', 'question')


def test_disabled_failed_and_duplicate_do_not_consume_budget(monkeypatch):
    send = Mock(return_value=False)
    monkeypatch.setattr(alerts.telegram_notify, 'send_once', send)
    for _ in range(25):
        assert not alerts.send_alert('hr_question', 'message:A:same', 'question')
    assert not alerts._windows['A']
    monkeypatch.setattr(alerts.CONFIG, 'tg_alert_hr_question_enabled', False)
    send.reset_mock()
    assert not alerts.send_alert('hr_question', 'message:A:1', 'question')
    send.assert_not_called()
