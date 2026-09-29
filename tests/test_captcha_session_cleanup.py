from unittest.mock import Mock

import pytest

from app import captcha_solver


@pytest.mark.parametrize('stage', ['prime_http', 'prime_network', 'xsrf', 'key', 'image'])
def test_failed_image_fetch_closes_unreturned_session(monkeypatch, stage):
    session = Mock()
    monkeypatch.setattr(captcha_solver, '_make_session', lambda: session)
    monkeypatch.setattr(captcha_solver, 'egress_proxies', lambda: {})
    session.get.side_effect = [
        TimeoutError() if stage == 'prime_network' else Mock(status_code=500 if stage == 'prime_http' else 200),
        Mock(status_code=500 if stage == 'image' else 200, content=b'png'),
    ]
    session.cookies.get.return_value = '' if stage == 'xsrf' else 'test'
    session.post.return_value = Mock(status_code=500 if stage == 'key' else 200,
                                     json=lambda: {'key': 'test'})
    with pytest.raises((ValueError, TimeoutError)):
        captcha_solver.fetch_captcha_image({}, 'https://hh.ru/account/captcha?state=test')
    session.close.assert_called_once()


def test_manual_submit_referer_preserves_opaque_state():
    from urllib.parse import parse_qs, urlsplit
    session = Mock()
    session.cookies.get.return_value = 'test'
    session.post.return_value = Mock(status_code=429, headers={}, json=lambda: {})
    captcha_solver.submit_captcha(session, 'human', 'key', 'opaque+value&suffix',
                                  'https://hh.ru/?return=test', require_confirmation=True)
    query = parse_qs(urlsplit(session.post.call_args.kwargs['headers']['Referer']).query)
    assert query['state'] == ['opaque+value&suffix']
    assert query['backurl'] == ['https://hh.ru/?return=test']
