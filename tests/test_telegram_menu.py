"""Live inline menus and shared configuration controls."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from app import telegram_menu as menu
from app.config import CONFIG


@pytest.fixture
def manager(monkeypatch):
    manager = SimpleNamespace(paused=False)
    manager.toggle_pause = lambda: setattr(manager, 'paused', not manager.paused)
    monkeypatch.setattr(menu, 'save_config', Mock())
    monkeypatch.setattr(CONFIG, 'human_mode_enabled', True)
    for category in menu.ALERT_CATEGORIES:
        monkeypatch.setattr(CONFIG, f'tg_alert_{category}_enabled', False)
    return manager


def test_main_menu(manager, monkeypatch):
    monkeypatch.setenv('HH_BOT_DASHBOARD_URL', 'https://dashboard.example')
    monkeypatch.setenv('HH_BOT_API_KEY', 'test+key&value')
    buttons = [row[0] for row in menu.build_main_menu(manager)['inline_keyboard']]
    assert [b['callback_data'] for b in buttons[:-1]] == [
        'status', 'pause_toggle', 'today', 'human_toggle', 'notif', 'captcha']
    assert all(len(b['callback_data'].encode()) <= 64 for b in buttons[:-1])
    assert parse_qs(urlsplit(buttons[-1]['url']).query) == {'key': ['test+key&value']}
    assert buttons[1]['text'] == '⏸ Пауза'
    manager.paused = True
    assert menu.build_main_menu(manager)['inline_keyboard'][1][0]['text'] == '▶ Продолжить'


def test_captcha_menu_highlights_only_active_challenges(manager):
    manager.account_states = [SimpleNamespace(paused_reason='challenge'),
                              SimpleNamespace(paused_reason='manual')]
    rows = menu.build_main_menu(manager)['inline_keyboard']
    button = next(row[0] for row in rows if row[0].get('callback_data') == 'captcha')
    assert button['text'] == '🔴 Нужна капча · 1 — открыть'
    manager.account_states[0].paused_reason = ''
    rows = menu.build_main_menu(manager)['inline_keyboard']
    button = next(row[0] for row in rows if row[0].get('callback_data') == 'captcha')
    assert button['text'] == '🔐 Проверки HH'


def test_pause_toggle(manager):
    for expected in (True, False):
        popup, keyboard = asyncio.run(menu.handle_callback(manager, 'pause_toggle', 1, 2))
        assert manager.paused is expected
        assert popup == ('⏸ Пауза' if expected else '▶ Работает')
        assert keyboard == menu.build_main_menu(manager)


def test_human_toggle(manager):
    _, keyboard = asyncio.run(menu.handle_callback(manager, 'human_toggle', 1, 2))
    assert CONFIG.human_mode_enabled is False
    assert '❌' in keyboard['inline_keyboard'][3][0]['text']
    menu.save_config.assert_called_once()


@pytest.mark.parametrize('category', menu.ALERT_CATEGORIES)
def test_notification_toggle(manager, category):
    _, keyboard = asyncio.run(menu.handle_callback(manager, f'notif_{category}_toggle', 1, 2))
    assert getattr(CONFIG, f'tg_alert_{category}_enabled') is True
    assert keyboard == menu.build_notif_menu(manager)
    assert len(keyboard['inline_keyboard']) == 6
    menu.save_config.assert_called_once()


@pytest.mark.parametrize('data,builder', [('back', menu.build_main_menu), ('notif', menu.build_notif_menu)])
def test_navigation(manager, data, builder):
    assert asyncio.run(menu.handle_callback(manager, data, 1, 2)) == ('', builder(manager))


def test_unknown(manager):
    popup, keyboard = asyncio.run(menu.handle_callback(manager, 'notif_untrusted_toggle', 1, 2))
    assert popup and keyboard is None
    menu.save_config.assert_not_called()


def test_live_summary(manager, monkeypatch):
    snapshot = {'accounts': [{'daily_limit': 100, 'hourly_rate': 4}],
                'totals': {'applied_today': 12}}
    reader = Mock(return_value=snapshot)
    monkeypatch.setattr(menu, 'build_status_snapshot', reader)
    for command in ('status', 'today', 'status'):
        popup, keyboard = asyncio.run(menu.handle_callback(manager, command, 1, 2))
        assert '12/100' in popup and '4/час' in popup
        assert len(popup) <= 200 and keyboard == menu.build_main_menu(manager)
    assert reader.call_count == 3
