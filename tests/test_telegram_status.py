import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import telegram_status as status


@pytest.fixture
def manager(monkeypatch, tmp_path):
    monkeypatch.setattr(status, '_EVENTS_FILE', tmp_path / 'events.json')
    monkeypatch.setattr(status.CONFIG, 'daily_apply_limit', 50)
    monkeypatch.setattr(status.CONFIG, 'hh_daily_limit', 200)
    monkeypatch.setattr(status.CONFIG, 'automation_paused', False)
    monkeypatch.setattr(status.storage, '_load_cache', lambda: None)
    now = datetime.now(status._MSK)
    monkeypatch.setattr(status.storage, '_cache_applied', {'Maria': {
        '1': {'at': now.isoformat()},
        '2': {'at': (now - timedelta(days=1)).isoformat()},
        '3': {'at': ''},
    }})
    account = SimpleNamespace(name='Maria', short='Мария', status='applying',
                              current_vacancy_title='Python Developer',
                              current_vacancy_company='Yandex')
    bot = SimpleNamespace(account_states=[account], temp_states={}, _add_log=Mock())
    status.install_status_tracking(bot)
    return bot


def test_snapshot(manager):
    manager._add_log('Мария', '', '🔐 HH запросил капчу', 'warning')
    manager._add_log('Мария', '', 'Ошибка запроса', 'error')
    snapshot = status.build_status_snapshot(manager)
    assert snapshot['accounts'] == [dict(short='Мария', state='🟢 работает',
        applied_today=1, daily_limit=50, hourly_rate=1.0,
        current_vacancy='Python Developer / Yandex', last_error='Ошибка запроса', captcha_count=1)]
    assert snapshot['totals'] == dict(applied_today=1, captcha_today=1, errors_today=1)


def test_html(manager):
    snapshot = status.build_status_snapshot(manager)
    html = status.build_status_html(snapshot)
    assert '1/50 (2%)' in html
    assert '~1/час' in html
    assert '<i>Python Developer / Yandex</i>' in html
    snapshot['accounts'][0]['short'] = '<script>&'
    assert '&lt;script&gt;&amp;' in status.build_status_html(snapshot)


def test_unchanged(manager):
    snapshot = status.build_status_snapshot(manager)
    assert not status.should_send(snapshot, deepcopy(snapshot))


@pytest.mark.parametrize('field,value', [('applied_today', 2), ('state', '🚫 challenge'),
                                         ('captcha_count', 1), ('last_error', 'error')])
def test_changed(manager, field, value):
    previous = status.build_status_snapshot(manager)
    current = deepcopy(previous)
    current['accounts'][0][field] = value
    assert status.should_send(previous, current)


def test_new_error_same_text(manager):
    previous = status.build_status_snapshot(manager)
    current = deepcopy(previous)
    current['totals']['errors_today'] += 1
    assert status.should_send(previous, current)


def test_rate_alone_does_not_send(manager):
    previous = status.build_status_snapshot(manager)
    current = deepcopy(previous)
    current['accounts'][0]['hourly_rate'] = 0
    assert not status.should_send(previous, current)


@pytest.mark.parametrize('reason,expected', [('challenge', '🚫 challenge'), ('limit', '🔴 лимит')])
def test_state_priority(manager, reason, expected):
    manager.account_states[0].paused = True
    manager.account_states[0].paused_reason = reason
    assert status.build_status_snapshot(manager)['accounts'][0]['state'] == expected


def test_daily_rollover(manager):
    manager._add_log('Мария', '', 'HH запросил капчу', 'warning')
    manager._telegram_status_events['day'] -= timedelta(days=1)
    assert status.build_status_snapshot(manager)['totals']['captcha_today'] == 0


def test_heartbeat_send_and_cancel(manager, monkeypatch):
    monkeypatch.setattr(status.CONFIG, 'telegram_status_enabled', True)
    send = Mock(return_value=True)
    monkeypatch.setattr(status.telegram_notify, 'send_once', send)
    sleeps = 0

    async def sleep(seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(status.asyncio, 'sleep', sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(status.status_heartbeat(manager, None, 30))
    assert send.call_count == 1
    assert send.call_args.args[0].startswith('status:')
    assert send.call_args.kwargs == {'parse_mode': 'HTML'}


def test_counters_survive_restart(manager):
    manager._add_log(acc_short='Мария', acc_color='', message='HH запросил капчу', level='warning')
    restarted = SimpleNamespace(account_states=manager.account_states, temp_states={}, _add_log=Mock())
    status.install_status_tracking(restarted)
    assert status.build_status_snapshot(restarted)['totals']['captcha_today'] == 1
