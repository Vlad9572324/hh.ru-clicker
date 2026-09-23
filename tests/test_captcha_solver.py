"""Verify captcha HTTP requests use the shared account transport and exact query parameters."""
from unittest.mock import Mock
import pytest
from app import captcha_solver as solver


@pytest.mark.parametrize('status,body,expected', [
    (302, {}, (True, '')), (200, {'hhcaptcha': {'isBot': True}}, (False, 'isBot')),
    (403, {'recaptcha': {'isBot': True}}, (False, 'recaptcha')),
    (500, {}, (False, 'http_500')),
])
def test_submit(monkeypatch, status, body, expected):
    request = Mock(return_value=Mock(status_code=status, json=lambda: body))
    monkeypatch.setattr(solver.HH, 'request', request)
    acc = {'user_id': 'test-account', 'cookies': {}}
    assert solver.submit_captcha(acc, 'a & б', 'test-key', 'test-state') == expected
    args, kw = request.call_args
    assert args == ('POST', 'https://hh.ru/account/captcha')
    assert kw['params'] == dict(captchaText='a & б', captchaKey='test-key',
                               captchaState='test-state', backurl='https://hh.ru/', failurl='https://hh.ru/')
    assert kw['allow_redirects'] is False
    assert kw['cookie_jar_key'] == (solver._token_key(acc) or 'test-account')
    assert kw['cookies'] == acc['cookies']
    assert kw['_skip_diag'] is True


def test_image(monkeypatch):
    request = Mock(side_effect=[Mock(status_code=200, json=lambda: {'key': 'test-key'}),
                               Mock(status_code=200, content=b'png')])
    monkeypatch.setattr(solver.HH, 'request', request)
    assert solver.fetch_captcha_image({'user_id': 'test-account'}) == ('test-key', b'png')
    assert request.call_args_list[0].kwargs['params'] == {'lang': 'RU'}
    assert request.call_args_list[1].args == ('GET', 'https://hh.ru/captcha/picture')
    assert request.call_args_list[1].kwargs['params'] == {'key': 'test-key'}
