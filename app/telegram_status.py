"""Periodic Telegram summaries with persisted daily event counters."""
import asyncio
import json
from collections import defaultdict
from contextlib import nullcontext
from datetime import datetime
from functools import wraps
from html import escape
import threading
from zoneinfo import ZoneInfo

from app import storage, telegram_notify
from app.config import CONFIG
from app.logging_utils import log_debug

_MSK = ZoneInfo('Europe/Moscow')
_EVENTS_FILE = storage.DATA_DIR / 'telegram_status_events.json'


def install_status_tracking(bot_manager):
    """Observe existing manager log events without changing captcha handling."""
    if hasattr(bot_manager, '_telegram_status_events'):
        return
    events = {'day': datetime.now(_MSK).date(), 'accounts': defaultdict(dict)}
    try:
        saved = json.loads(_EVENTS_FILE.read_text(encoding='utf-8'))
        if saved.get('day') == events['day'].isoformat():
            events['accounts'].update(saved['accounts'])
    except (OSError, ValueError, TypeError, KeyError):
        pass
    lock = threading.Lock()
    bot_manager._telegram_status_events = events
    bot_manager._telegram_status_lock = lock
    original = bot_manager._add_log

    @wraps(original)
    def tracked(acc_short, acc_color, message, level='info', *args, **kwargs):
        original(acc_short, acc_color, message, level, *args, **kwargs)
        if level != 'error' and 'HH запросил капчу' not in message:
            return
        with lock:
            today = datetime.now(_MSK).date()
            if events['day'] != today:
                events.update(day=today, accounts=defaultdict(dict))
            account = events['accounts'][acc_short]
            if 'HH запросил капчу' in message:
                account['captcha_count'] = account.get('captcha_count', 0) + 1
            if level == 'error':
                account['errors_today'] = account.get('errors_today', 0) + 1
                account['last_error'] = message
            try:
                storage._atomic_write_json(_EVENTS_FILE, {
                    'day': today.isoformat(), 'accounts': dict(events['accounts'])})
            except OSError:
                log_debug('telegram status: cannot persist counters')
    bot_manager._add_log = tracked


def build_status_snapshot(bot_manager) -> dict:
    now = datetime.now(_MSK)
    applied = defaultdict(list)
    storage._load_cache()
    with storage._cache_lock:
        for name, records in (storage._cache_applied or {}).items():
            for record in records.values():
                try:
                    stamp = datetime.fromisoformat(record.get('at', '')).astimezone(_MSK)
                except (ValueError, TypeError):
                    continue
                applied[name].append(stamp)
    with getattr(bot_manager, '_telegram_status_lock', nullcontext()):
        events = getattr(bot_manager, '_telegram_status_events', {})
        counts = {k: dict(v) for k, v in events.get('accounts', {}).items()} if events.get('day') == now.date() else {}
    accounts = []
    errors = 0
    states = list(bot_manager.account_states) + list(getattr(bot_manager, 'temp_states', {}).values())
    for state in states:
        with getattr(state, '_state_lock', nullcontext()):
            if getattr(state, '_deleted', False):
                continue
            stats = counts.get(state.short, {})
            stamps = applied[state.name]
            today = sum(stamp.date() == now.date() for stamp in stamps)
            limits = [v for v in (CONFIG.daily_apply_limit, CONFIG.hh_daily_limit) if v > 0]
            limit = min(limits) if limits else 200
            reason = getattr(state, 'paused_reason', None)
            if reason == 'challenge':
                status = '🚫 challenge'
            elif getattr(state, 'limit_exceeded', False) or reason == 'limit' or getattr(state, 'status', '') == 'limit' or today >= limit:
                status = '🔴 лимит'
            elif CONFIG.automation_paused or getattr(state, 'paused', False) or getattr(state, 'hard_stopped', False) or getattr(state, 'status', 'idle') in ('idle', 'stopped'):
                status = '⏸ пауза'
            else:
                status = '🟢 работает'
            vacancy = ' / '.join(filter(None, (getattr(state, 'current_vacancy_title', ''), getattr(state, 'current_vacancy_company', ''))))
            accounts.append(dict(short=state.short, state=status, applied_today=today,
                                 daily_limit=limit, hourly_rate=float(sum(0 <= (now - stamp).total_seconds() < 3600 for stamp in stamps)),
                                 current_vacancy=vacancy or None, last_error=stats.get('last_error'),
                                 captcha_count=stats.get('captcha_count', 0)))
            errors += stats.get('errors_today', 0)
    return {'accounts': accounts, 'totals': {
        'applied_today': sum(a['applied_today'] for a in accounts),
        'captcha_today': sum(a['captcha_count'] for a in accounts), 'errors_today': errors}}


def build_status_html(snapshot, previous_snapshot=None) -> str:
    lines = [f'📊 <b>Свод</b> ({snapshot.get("interval_min", CONFIG.telegram_status_interval_min)} мин)', '']
    for account in snapshot['accounts']:
        count, limit = account['applied_today'], account['daily_limit']
        percent = f' ({count / limit:.0%})' if limit else ''
        lines.extend([f'{account["state"]} <b>{escape(str(account["short"]))}</b>',
                      f'⏱ Отклики: {count}/{limit}{percent}',
                      f'🎯 Rate: ~{account["hourly_rate"]:.0f}/час'])
        if account.get('current_vacancy'):
            lines.append(f'🏢 Сейчас: <i>{escape(str(account["current_vacancy"])[:240])}</i>')
        lines.append(f'🤖 Капч за день: {account["captcha_count"]}')
        if account.get('last_error'):
            lines.append(f'⚠️ {escape(str(account["last_error"])[:240])}')
        lines.append('')
    total = snapshot['totals']
    lines.append(f'📈 <b>Итого</b>: {total["applied_today"]} откликов / {total["captcha_today"]} капч / {total["errors_today"]} ошибки')
    # send_once truncates at 4000 characters; preserve complete HTML blocks.
    while len('\n'.join(lines)) > 3900 and len(lines) > 3:
        lines.pop(-2)
    return '\n'.join(lines)


def should_send(previous, current) -> bool:
    if previous is None:
        return bool(current['accounts'])
    fields = ('short', 'state', 'applied_today', 'captcha_count', 'last_error')
    signature = lambda snapshot: [tuple(a.get(k) for k in fields) for a in snapshot['accounts']]
    return signature(previous) != signature(current) or any(
        current['totals'].get(k, 0) > previous['totals'].get(k, 0)
        for k in ('captcha_today', 'errors_today'))


async def status_heartbeat(bot_manager, telegram_bot, interval_min):
    """Use send_once's persisted deduplication; telegram_bot is lifecycle context."""
    previous = None
    while True:
        await asyncio.sleep(max(10, min(120, interval_min)) * 60)
        interval_min = CONFIG.telegram_status_interval_min
        if not CONFIG.telegram_status_enabled:
            continue
        try:
            current = await asyncio.to_thread(build_status_snapshot, bot_manager)
            current['interval_min'] = max(10, min(120, interval_min))
            if should_send(previous, current):
                key = f'status:{int(datetime.now().timestamp() // 3600)}'
                sent = await asyncio.to_thread(telegram_notify.send_once, key,
                                             build_status_html(current, previous), parse_mode='HTML')
                if sent:
                    previous = current
        except Exception as exc:
            log_debug(f'telegram status: {type(exc).__name__}')
