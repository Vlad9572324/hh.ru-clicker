"""Interruptible per-account pacing. Hours use the worker's local timezone."""

from datetime import datetime, timedelta
import random
import re
import time

from app.config import CONFIG

# Independent generator: never reseed the process-wide random module.
_rng = random.Random()

# Average weekday budget: 68 attempts across the default 17-hour window.
TARGET_APPLIES_PER_HOUR = 4.0

HUMAN_CONFIG_KEYS = (
    'human_mode_enabled', 'human_active_hours',
    'human_apply_delay_min', 'human_apply_delay_max',
    'human_burst_size_min', 'human_burst_size_max',
    'human_burst_pause_min_sec', 'human_burst_pause_max_sec',
    'human_captcha_backoff_hours',
)


def _bounds(low, high, minimum=0):
    # Runtime settings arrive individually; tolerate temporarily reversed bounds.
    return sorted((max(minimum, low), max(minimum, high)))


def random_apply_delay() -> float:
    if _rng.random() < 0.1:
        return _rng.uniform(30, 60)
    low, high = _bounds(CONFIG.human_apply_delay_min, CONFIG.human_apply_delay_max)
    return low + (high - low) * _rng.betavariate(2, 5)


def random_burst_size() -> int:
    return _rng.randint(*_bounds(CONFIG.human_burst_size_min, CONFIG.human_burst_size_max, 1))


def random_burst_pause() -> float:
    if _rng.random() < 0.1:
        return _rng.uniform(600, 1200)
    return _rng.uniform(*_bounds(CONFIG.human_burst_pause_min_sec, CONFIG.human_burst_pause_max_sec))


def parse_active_hours(hours: str) -> tuple[int, int]:
    if not re.fullmatch(r'\d{2}-\d{2}', hours):
        raise ValueError('Active hours must use HH-HH')
    start, end = map(int, hours.split('-'))
    if not (0 <= start <= 23 and 0 <= end <= 24) or start == end:
        raise ValueError('Invalid or empty active window')
    return start, end


def is_active_hour(hours=None, now=None) -> bool:
    try:
        start, end = parse_active_hours(CONFIG.human_active_hours if hours is None else hours)
    except (ValueError, TypeError):
        return False  # Invalid runtime configuration must not enable sending.
    hour = (now or datetime.now()).hour
    return start <= hour < end if start < end else hour >= start or hour < end


def sleep_until_active_hour(state, stop_event) -> None:
    while CONFIG.human_mode_enabled and not stop_event.is_set() and not getattr(state, '_deleted', False):
        now = datetime.now()
        if is_active_hour(now=now):
            return
        try:
            start, _ = parse_active_hours(CONFIG.human_active_hours)
            next_start = now.replace(hour=start, minute=0, second=0, microsecond=0)
            if next_start <= now:
                next_start += timedelta(days=1)
            remaining = next_start.timestamp() - now.timestamp()
            state.status_detail = f'Активное окно с {next_start:%H:%M} (локальное время сервера)'
        except (ValueError, TypeError):
            remaining = 60
            state.status_detail = 'Некорректные активные часы: нужен формат HH-HH'
        # Recheck settings/deletion each minute while waiting for the next window.
        if stop_event.wait(min(60, max(0, remaining))):
            return


def adaptive_backoff_multiplier(state) -> float:
    last = max(getattr(state, '_last_captcha_at', 0) or 0,
               getattr(state, 'acc', {}).get('_last_captcha_at', 0) or 0)
    return 2.0 if last and 0 <= time.time() - last < CONFIG.human_captcha_backoff_hours * 3600 else 1.0


def weekend_variance() -> float:
    return 0.7 if datetime.now().weekday() >= 5 else 1.0


def delay_multiplier(state) -> float:
    """0.7 activity means longer delays, not 30% faster requests."""
    return adaptive_backoff_multiplier(state) / weekend_variance()
