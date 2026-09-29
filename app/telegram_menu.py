"""Inline Telegram controls backed by the live manager and shared configuration."""
import asyncio
import os
from urllib.parse import urlencode

from app.config import CONFIG, save_config
from app.telegram_status import build_status_html, build_status_snapshot

MENU_MAIN = [
    {'text': '📊 Статус', 'callback_data': 'status'},
    {'text': '⏸ Пауза', 'callback_data': 'pause_toggle'},
    {'text': '📈 Отклики сегодня', 'callback_data': 'today'},
    {'text': '🤖 Человеческий режим', 'callback_data': 'human_toggle'},
    {'text': '🔔 Настройки уведомлений', 'callback_data': 'notif'},
]
ALERT_CATEGORIES = {
    'interview': 'Приглашения на интервью',
    'offer': 'Предложения работы',
    'hr_question': 'Вопросы HR',
    'account_blocked': 'Блокировка аккаунта',
    'daily_limit': 'Дневной лимит',
}
BOT_COMMANDS = [
    {'command': 'captcha', 'description': 'Пропустили капчу? Открыть ручную проверку HH'},
    {'command': 'start', 'description': 'Подписаться и открыть меню'},
    {'command': 'stop', 'description': 'Отписаться'},
    {'command': 'status', 'description': 'Показать статус бота'},
    {'command': 'menu', 'description': 'Открыть меню'},
    {'command': 'pause', 'description': 'Приостановить бота'},
    {'command': 'resume', 'description': 'Продолжить бота'},
]


def build_main_menu(bot_manager):
    buttons = [dict(button) for button in MENU_MAIN]
    buttons[1]['text'] = '▶ Продолжить' if bot_manager.paused else '⏸ Пауза'
    buttons[3]['text'] += ': ' + ('✅' if CONFIG.human_mode_enabled else '❌')
    states = list(getattr(bot_manager, 'account_states', [])) + list(getattr(bot_manager, 'temp_states', {}).values())
    count = sum(1 for state in states if not getattr(state, '_deleted', False)
                and getattr(state, 'paused_reason', '') == 'challenge')
    buttons.append({'text': f'🔴 Нужна капча · {count} — открыть' if count else '🔐 Проверки HH',
                    'callback_data': 'captcha'})
    base = os.environ.get('HH_BOT_DASHBOARD_URL', 'http://localhost:8000').strip().rstrip('/')
    url = base + '/?' + urlencode({'key': os.environ.get('HH_BOT_API_KEY', '').strip()})
    buttons.append({'text': '🔐 Открыть дашборд', 'url': url})
    return {'inline_keyboard': [[button] for button in buttons]}


def build_notif_menu(bot_manager):
    rows = [[{'text': ('✅ ' if getattr(CONFIG, f'tg_alert_{category}_enabled') else '❌ ') + label,
              'callback_data': f'notif_{category}_toggle'}]
            for category, label in ALERT_CATEGORIES.items()]
    rows.append([{'text': '🔙 Назад', 'callback_data': 'back'}])
    return {'inline_keyboard': rows}


async def live_status(bot_manager):
    snapshot = await asyncio.to_thread(build_status_snapshot, bot_manager)
    return build_status_html(snapshot)


async def handle_callback(bot_manager, data, chat_id, message_id):
    if data == 'captcha':
        return 'Открываю текущие проверки HH', build_main_menu(bot_manager)
    if data in ('status', 'today'):
        snapshot = await asyncio.to_thread(build_status_snapshot, bot_manager)
        accounts = snapshot['accounts']
        summary = (f"📈 Сегодня: {snapshot['totals']['applied_today']}/"
                   f"{sum(a['daily_limit'] for a in accounts)} откликов\n"
                   f"Темп: {sum(a['hourly_rate'] for a in accounts):.0f}/час")
        if data == 'status':
            summary = snapshot.get('header', '') + '\n' + summary
        return summary[:200], build_main_menu(bot_manager)
    if data == 'pause_toggle':
        bot_manager.toggle_pause()
        return ('⏸ Пауза' if bot_manager.paused else '▶ Работает'), build_main_menu(bot_manager)
    if data == 'human_toggle':
        CONFIG.human_mode_enabled = not CONFIG.human_mode_enabled
        save_config()
        return 'Человеческий режим ' + ('включён' if CONFIG.human_mode_enabled else 'выключен'), build_main_menu(bot_manager)
    if data == 'notif':
        return '', build_notif_menu(bot_manager)
    for category in ALERT_CATEGORIES:
        if data == f'notif_{category}_toggle':
            attr = f'tg_alert_{category}_enabled'
            setattr(CONFIG, attr, not getattr(CONFIG, attr))
            save_config()
            return '', build_notif_menu(bot_manager)
    if data == 'back':
        return '', build_main_menu(bot_manager)
    return 'Неизвестная команда. Откройте /menu.', None
