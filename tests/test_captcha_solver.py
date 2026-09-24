"""Verify captcha uses a persistent session with X-Xsrftoken and correct params."""
from unittest.mock import Mock
import pytest
from app import captcha_solver as solver


def _fake_session(prime_status=200, xsrf='xsrf-token-123', post_status=200,
                  key_body=None, image_status=200, image=b'\x89PNG_ok'):
    """Build a Mock imitating requests.Session with cookie jar."""
    session = Mock()
    session.cookies = Mock()
    cookies_map = {'_xsrf': xsrf} if xsrf else {}
    session.cookies.get = lambda k, default='': cookies_map.get(k, default)
    session.headers = {}
    session.proxies = {}
    session.get = Mock(side_effect=[
        Mock(status_code=prime_status),                                   # prime page
        Mock(status_code=image_status, content=image),                    # image
    ])
    session.post = Mock(return_value=Mock(status_code=post_status,
                                          json=lambda: key_body or {'key': 'CK-1'}))
    return session


def test_fetch_captcha_image_happy_path(monkeypatch):
    session = _fake_session()
    monkeypatch.setattr(solver, '_make_session', lambda: session)
    monkeypatch.setattr(solver, 'egress_proxies', lambda: {})
    url = 'https://hh.ru/account/captcha?state=STATE-1&backurl=https%3A%2F%2Fhh.ru%2F'
    got_sess, key, img, state, backurl = solver.fetch_captcha_image({'user_id': 'x'}, url)
    assert got_sess is session and key == 'CK-1' and img == b'\x89PNG_ok'
    assert state == 'STATE-1' and backurl == 'https://hh.ru/'
    # POST /captcha должен иметь X-Xsrftoken
    args, kw = session.post.call_args
    assert args[0] == 'https://hh.ru/captcha'
    assert kw['headers']['X-Xsrftoken'] == 'xsrf-token-123'
    assert kw['params'] == {'lang': 'RU'}


def test_fetch_captcha_image_missing_state():
    with pytest.raises(ValueError, match='missing_state'):
        solver.fetch_captcha_image({}, 'https://hh.ru/account/captcha')


def test_fetch_captcha_image_missing_xsrf(monkeypatch):
    session = _fake_session(xsrf='')
    monkeypatch.setattr(solver, '_make_session', lambda: session)
    monkeypatch.setattr(solver, 'egress_proxies', lambda: {})
    with pytest.raises(ValueError, match='missing_xsrf_cookie'):
        solver.fetch_captcha_image({}, 'https://hh.ru/account/captcha?state=X')


@pytest.mark.parametrize('status,body,expected', [
    (302, {}, (True, '')),                              # 302 без Location = HH принял (JS-redirect в body)
    (200, {}, (True, '')),
    (200, {'hhcaptcha': {'isBot': True}}, (False, 'isBot')),
    (403, {'recaptcha': {'isBot': True}}, (False, 'recaptcha')),
    (500, {}, (False, 'http_500')),
])
def test_submit_captcha(status, body, expected):
    session = Mock()
    session.cookies = Mock()
    session.cookies.get = lambda k, default='': 'xsrf-x' if k == '_xsrf' else default
    session.post = Mock(return_value=Mock(status_code=status, headers={}, json=lambda: body))
    got = solver.submit_captcha(session, 'text-1', 'CK-1', 'STATE-1', 'https://hh.ru/back', 'https://hh.ru/fail')
    assert got == expected
    args, kw = session.post.call_args
    assert args[0] == 'https://hh.ru/account/captcha'
    assert kw['params']['captchaText'] == 'text-1'
    assert kw['params']['captchaKey'] == 'CK-1'
    assert kw['params']['captchaState'] == 'STATE-1'
    assert kw['params']['backurl'] == 'https://hh.ru/back'
    assert kw['params']['failurl'] == 'https://hh.ru/fail'
    assert kw['allow_redirects'] is False
    assert kw['headers']['X-Xsrftoken'] == 'xsrf-x'


@pytest.mark.parametrize('location,expected', [
    ('https://hh.ru/', (True, '')),
    ('/', (True, '')),
    ('/vacancies/12345', (True, '')),                                     # редирект на HH-контент = success
    ('https://hh.ru/account/captcha?state=test', (False, 'isBot')),       # обратно на captcha = failure
    ('/account/captcha?state=other', (False, 'isBot')),                   # relative path тоже
    ('', (True, '')),                                                     # пустой Location = HH принял (JS-redirect)
])
def test_redirect_matches_distinct_success_or_failure(location, expected):
    session = Mock()
    session.cookies.get.return_value = 'synthetic'
    session.post.return_value = Mock(status_code=302, headers={'Location': location})
    assert solver.submit_captcha(session, 'human', 'key', 'test',
        'https://hh.ru/', 'https://hh.ru/account/captcha?state=test') == expected


def test_diagnostic_contains_only_safe_metadata(monkeypatch):
    from app import logging_utils
    logs = []
    monkeypatch.setattr(logging_utils, 'log_debug', logs.append)
    session = Mock()
    session.cookies.get.return_value = 'PRIVATE_COOKIE'
    session.post.return_value = Mock(status_code=200, headers={}, json=lambda: {
        'hhcaptcha': {'isBot': False}, 'token': 'PRIVATE_TOKEN'})
    result = solver.submit_captcha(session, 'PRIVATE_ANSWER', 'PRIVATE_KEY', 'PRIVATE_STATE')
    assert result == (True, '')  # 200 без isBot маркера теперь success (lenient)
    assert session.hh_captcha_diagnostic == {'http_status': 200, 'format': 'json',
        'hhcaptcha_isBot': False, 'redirect_present': False}
    assert logs and 'PRIVATE' not in str(logs)
