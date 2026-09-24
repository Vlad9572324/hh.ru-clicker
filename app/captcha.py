"""Human-only HH challenge handling; never solves or retries a request."""
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from app.storage import _atomic_write_json

PATH = Path('data/hh_challenges.json')
LOCK = threading.RLock()


def account_key(acc):
    value = acc.get('user_id') or acc.get('resume_hash')
    if not value:
        raise ValueError('Missing account identity')
    return str(value)


def safe_url(value):
    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) < 32 for c in value) or '\\' in value:
        return ''
    try:
        u = urlsplit(value)
        host = (u.hostname or '').lower()
        if u.scheme != 'https' or not (host == 'hh.ru' or host.endswith('.hh.ru')) or u.username or u.password or u.port not in (None, 443):
            return ''
        return value
    except ValueError:
        return ''


def parse(status, payload):
    if status not in (400, 403) or not isinstance(payload, dict):
        return None
    errors = payload.get('errors', [])
    if not isinstance(errors, list):
        return None
    for error in errors[:30]:
        if isinstance(error, dict) and any(error.get(k) == 'captcha_required' for k in ('type', 'value')):
            return {'captcha_url': safe_url(error.get('captcha_url')),
                    'fallback_url': safe_url(error.get('fallback_url')), 'error_type': 'captcha_required'}
    return None


def _read():
    data = json.loads(PATH.read_text()) if PATH.exists() else {}
    if not isinstance(data, dict) or any(not isinstance(v, dict) for v in data.values()):
        raise ValueError('Invalid challenge storage')
    return data


def current(acc):
    with LOCK:
        return dict(_read().get(account_key(acc), {}))


def active(acc):
    try:
        with LOCK:
            data = _read()
            return bool(data) and bool(data.get(account_key(acc)))
    except Exception:
        return True


def hold(acc, details):
    callback = acc.get('_on_challenge')
    if callable(callback):
        callback()
    new_challenge = False
    with LOCK:
        data = _read()
        key = account_key(acc)
        if key not in data:
            new_challenge = True
        if key not in data or (not (data[key].get('captcha_url') or data[key].get('fallback_url'))
                               and (safe_url(details.get('captcha_url')) or safe_url(details.get('fallback_url')))):
            data[key] = {'id': uuid.uuid4().hex, 'created_at': datetime.now(timezone.utc).isoformat(),
                         'captcha_url': safe_url(details.get('captcha_url')),
                         'fallback_url': safe_url(details.get('fallback_url'))}
        _atomic_write_json(PATH, data)
    # UI лог: показать что HH запросил капчу для этого аккаунта (только на первый).
    if new_challenge:
        try:
            from app.instances import bot as _bot
            _bot._add_log(acc.get('short', ''), acc.get('color', 'yellow'),
                          '🔐 HH запросил капчу — ожидание ответа (TG/GUI)', 'warning')
        except Exception:
            pass


def capture(acc, status, payload):
    details = parse(status, payload)
    if details is not None:
        hold(acc, details)
    return details


def browser_url(record):
    url = safe_url(record.get('captcha_url'))
    if not url:
        return safe_url(record.get('fallback_url'))
    u = urlsplit(url)
    # Stay on HH after the human check. No callback can auto-resume automation.
    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k.lower() != 'backurl']
    query.append(('backurl', 'https://hh.ru/'))
    return urlunsplit((u.scheme, u.netloc, u.path, urlencode(query), u.fragment))


def clear(acc, expected_id):
    with LOCK:
        data = _read()
        key = account_key(acc)
        if not data.get(key) or data[key].get('id') != expected_id:
            raise ValueError('Challenge changed')
        del data[key]
        _atomic_write_json(PATH, data)
