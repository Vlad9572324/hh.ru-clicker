from unittest.mock import Mock
import pytest
import requests
from app.captcha_solver import verify_manual_completion


RETURN = 'https://hh.ru/?manual_captcha_return=synthetic'
CHALLENGE = 'https://hh.ru/account/captcha?state=synthetic'


@pytest.mark.parametrize('status,location,ok', [
    (302, RETURN, True), (303, '/?manual_captcha_return=synthetic', True),
    (302, 'https://hh.ru/', False), (302, '/account/login', False),
    (302, '', False), (200, RETURN, False), (404, '', False), (429, '', False),
])
def test_readonly_completion_requires_exact_return(status, location, ok):
    session = Mock()
    session.get.return_value = Mock(status_code=status, headers={'Location': location})
    assert verify_manual_completion(session, CHALLENGE, RETURN)[0] is ok
    session.get.assert_called_once_with(CHALLENGE, timeout=10, allow_redirects=False)
    session.post.assert_not_called()


def test_timeout_is_not_retried():
    session = Mock()
    session.get.side_effect = requests.Timeout()
    assert verify_manual_completion(session, CHALLENGE, RETURN)[0] is False
    session.get.assert_called_once()
    session.post.assert_not_called()


def test_opaque_state_is_urlencoded_not_interpolated(monkeypatch):
    from app import captcha_solver
    session = Mock()
    session.proxies = {}
    session.get.return_value = Mock(status_code=200)
    monkeypatch.setattr(captcha_solver, '_make_session', lambda: session)
    monkeypatch.setattr(captcha_solver, 'egress_proxies', lambda: {})
    captcha_solver._prime_session('https://hh.ru/account/captcha?state=a%2Bb%26c&backurl=https%3A%2F%2Fhh.ru%2F')
    assert session.get.call_args.args == ('https://hh.ru/account/captcha',)
    assert session.get.call_args.kwargs['params']['state'] == 'a+b&c'
