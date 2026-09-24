"""Fetch HH captcha images and submit human answers using a session cookie jar.

Разведан live-flow:
1. GET  https://hh.ru/account/captcha?state=<state>&backurl=<url>
   → HH ставит DDoS-Guard __ddg*, _xsrf, hhtoken, hhuid, hhrole cookies в session.
2. POST https://hh.ru/captcha?lang=RU  (Referer + X-Xsrftoken=<_xsrf>)
   → {"key": "<captchaKey>"}
3. GET  https://hh.ru/captcha/picture?key=<captchaKey>  → PNG bytes.
4. POST https://hh.ru/account/captcha?captchaText=X&captchaKey=Y&captchaState=Z&backurl=...
   → 302 redirect на backurl = успех.

Ключевые открытия (проверено 2026-09-23):
- Bearer OAuth токен НЕ помогает (endpoint web-only).
- `_xsrf` cookie + `X-Xsrftoken` header обязательны — иначе 403 с HTML captcha_required.
- Все запросы должны идти В ОДНОЙ session (persistent cookie jar).
- HH.request с shared cookie_jar_key НЕ подходит: state пересекается с обычным трафиком.
  Используем свой requests.Session per-challenge.
"""
import requests
from urllib.parse import parse_qs, urlsplit, urljoin

from app.hh_http import egress_proxies

_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36')


def _make_session():
    s = requests.Session()
    s.headers.update({'User-Agent': _UA,
                      'Accept-Language': 'ru,en-US;q=0.9,en;q=0.8'})
    return s


def _prime_session(captcha_url: str) -> tuple[requests.Session, str, str]:
    """GET captcha page → session with DDoS-Guard + _xsrf cookies.

    Returns (session, state, backurl) parsed from captcha_url.
    """
    parts = urlsplit(captcha_url)
    query = parse_qs(parts.query)
    state = query.get('state', [''])[0]
    backurl = query.get('backurl', ['https://hh.ru/'])[0]
    if not state:
        raise ValueError('missing_state')

    session = _make_session()
    proxies = egress_proxies()
    session.proxies.update(proxies or {})
    response = session.get(f'https://hh.ru/account/captcha?state={state}&backurl={backurl}',
                           timeout=15, allow_redirects=True)
    if response.status_code != 200:
        raise ValueError(f'prime_http_{response.status_code}')
    return session, state, backurl


def fetch_captcha_image(acc: dict, captcha_url: str, lang: str = 'RU'):
    """Load HH captcha for a given challenge URL. Returns (session, captcha_key, image_bytes, state, backurl).

    Session is reusable for submit_captcha (same cookie jar / DDoS-Guard tokens).
    ``acc`` is accepted for signature compatibility but not used (captcha flow
    is stateless w.r.t. account — HH state param already carries account identity).
    """
    session, state, backurl = _prime_session(captcha_url)
    xsrf = session.cookies.get('_xsrf', '')
    if not xsrf:
        raise ValueError('missing_xsrf_cookie')
    headers = {
        'Referer': f'https://hh.ru/account/captcha?state={state}&backurl={backurl}',
        'X-Requested-With': 'XMLHttpRequest',
        'X-Xsrftoken': xsrf,
        'Accept': 'application/json, text/plain, */*',
    }
    r = session.post('https://hh.ru/captcha', params={'lang': lang},
                     headers=headers, timeout=10, allow_redirects=False)
    if r.status_code != 200:
        raise ValueError(f'get_key_http_{r.status_code}')
    key = r.json().get('key')
    if not isinstance(key, str) or not key:
        raise ValueError('missing_key')
    r = session.get('https://hh.ru/captcha/picture', params={'key': key},
                    headers={'Referer': headers['Referer']},
                    timeout=10, allow_redirects=False)
    if r.status_code != 200 or not r.content:
        raise ValueError(f'image_http_{r.status_code}')
    return session, key, r.content, state, backurl


def submit_captcha(session: requests.Session, captcha_text: str, captcha_key: str,
                   captcha_state: str, backurl: str = 'https://hh.ru/',
                   failurl: str = None):
    """POST /account/captcha with user's text. Returns (ok: bool, reason: str).

    Uses SAME session that fetched the image (DDoS-Guard state must match).
    """
    xsrf = session.cookies.get('_xsrf', '')
    headers = {
        'Referer': f'https://hh.ru/account/captcha?state={captcha_state}&backurl={backurl}',
        'X-Requested-With': 'XMLHttpRequest',
        'X-Xsrftoken': xsrf,
        'Accept': 'application/json, text/plain, */*',
    }
    r = session.post('https://hh.ru/account/captcha', params={
        'captchaText': captcha_text,
        'captchaKey': captcha_key,
        'captchaState': captcha_state,
        'backurl': backurl,
        'failurl': failurl or backurl,
    }, headers=headers, timeout=10, allow_redirects=False)
    # Whitelisted metadata only: never log URLs, cookies, answers or raw bodies.
    try:
        diagnostic_body = r.json()
    except (ValueError, TypeError):
        diagnostic_body = None
    diagnostic = {'http_status': r.status_code,
                  'format': 'json' if diagnostic_body is not None else 'non_json'}
    for field in ('hhcaptcha', 'recaptcha'):
        value = diagnostic_body.get(field) if isinstance(diagnostic_body, dict) else None
        if isinstance(value, dict) and isinstance(value.get('isBot'), bool):
            diagnostic[field + '_isBot'] = value['isBot']
    diagnostic['redirect_present'] = bool(r.headers.get('Location'))
    session.hh_captcha_diagnostic = diagnostic
    from app.logging_utils import log_debug
    import json
    log_debug('captcha_result_metadata ' + json.dumps(diagnostic, sort_keys=True))
    # 200/400/403 с JSON {hhcaptcha:{isBot:true}} = точный failure signal.
    try:
        body = r.json()
        if isinstance(body, dict):
            if isinstance(body.get('recaptcha'), dict) and body['recaptcha'].get('isBot') is True:
                return False, 'recaptcha'
            if isinstance(body.get('hhcaptcha'), dict) and body['hhcaptcha'].get('isBot') is True:
                return False, 'isBot'
    except (ValueError, TypeError):
        pass
    # Redirect analysis. HH шлёт 302 БЕЗ Location (JS-redirect в body) как самый
    # частый success signal. Явный редирект на /account/captcha или /account/login
    # = failure (HH нас не пустил / session мёртв). Всё остальное = success:
    # если HH реально не принял, следующий request упрётся в новый captcha_required
    # и бот снова начнёт flow — никакого ущерба.
    _FAIL_PATHS = ('/account/captcha', '/account/login')
    if r.status_code in (302, 303):
        from app.captcha import safe_url
        location = r.headers.get('Location', '')
        location = urljoin('https://hh.ru/account/captcha', location) if location else ''
        if location and safe_url(location):
            from urllib.parse import urlsplit as _split
            if _split(location).path in _FAIL_PATHS:
                return False, 'isBot'
        # Любой другой 302 = HH принял ответ (включая пустой Location).
        return True, ''
    # 200 без явного isBot маркера — тоже success. HH иногда так подтверждает.
    if r.status_code == 200:
        return True, ''
    return False, f'http_{r.status_code}'
