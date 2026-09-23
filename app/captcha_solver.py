"""Fetch HH captcha images and submit human answers using the account HH transport."""
from app.oauth import _token_key
from app.captcha import account_key
from app.hh_http import HH


def _request(acc, method, path, **kwargs):
    cookies = acc.get('cookies') or {}
    headers = {'Referer': 'https://hh.ru/', 'X-Requested-With': 'XMLHttpRequest'}
    if isinstance(cookies, dict) and cookies.get('_xsrf'):
        headers['X-Xsrftoken'] = cookies['_xsrf']
    return HH.request(method, 'https://hh.ru' + path, cookies=cookies,
                      cookie_jar_key=_token_key(acc) or account_key(acc), headers=headers,
                      timeout=10, _skip_diag=True, **kwargs)


def fetch_captcha_image(acc: dict, lang: str = 'RU') -> tuple[str, bytes]:
    response = _request(acc, 'POST', '/captcha', params={'lang': lang})
    if response.status_code != 200:
        raise ValueError(f'http_{response.status_code}')
    key = response.json().get('key')
    if not isinstance(key, str) or not key:
        raise ValueError('missing_key')
    response = _request(acc, 'GET', '/captcha/picture', params={'key': key})
    if response.status_code != 200 or not response.content:
        raise ValueError(f'image_http_{response.status_code}')
    return key, response.content


def submit_captcha(acc: dict, captcha_text: str, captcha_key: str,
                   captcha_state: str, backurl: str = 'https://hh.ru/',
                   failurl: str = None) -> tuple[bool, str]:
    response = _request(acc, 'POST', '/account/captcha', allow_redirects=False,
                        params={'captchaText': captcha_text, 'captchaKey': captcha_key,
                                'captchaState': captcha_state, 'backurl': backurl,
                                'failurl': failurl or backurl})
    if response.status_code == 302:
        return True, ''
    try:
        body = response.json()
        if isinstance(body, dict):
            for field, reason in [('recaptcha', 'recaptcha'), ('hhcaptcha', 'isBot')]:
                if isinstance(body.get(field), dict) and body[field].get('isBot') is True:
                    return False, reason
    except (ValueError, TypeError):
        pass
    return False, f'http_{response.status_code}'
