"""Every authenticated HH call for one account must present one device."""
from unittest.mock import Mock

from app import oauth
from app.hh_mobile_transport import mobile_headers
from app.ws_client import HHWebSocketClient

ACC = {'user_id': '1', 'resume_hash': 'r1',
       'device_identity': {'device_uuid': '11111111-2222-3333-4444-555555555555',
                           'model': 'Pixel 8', 'android_release': '15',
                           'app_version_name': '26.32.11480'}}


def device(headers):
    return {k: headers.get(k) for k in ('User-Agent', 'X-Device-Uuid', 'x-hh-app-active')}


def test_rest_calls_share_mobile_request_identity(monkeypatch):
    monkeypatch.setattr(oauth, '_obtain_oauth_token', lambda acc: 'tok')
    expected = device(mobile_headers(ACC, 'tok'))
    assert expected['X-Device-Uuid'] == ACC['device_identity']['device_uuid']
    assert device(oauth._oauth_headers(ACC)) == expected

    post = Mock(return_value=Mock(status_code=201, content=b'', json=Mock(side_effect=ValueError)))
    monkeypatch.setattr(oauth.HH, 'post', post)
    monkeypatch.setattr(oauth, 'ensure_mutation_allowed', lambda acc: None)
    oauth._oauth_apply(ACC, '123')
    assert device(post.call_args.kwargs['headers']) == expected


def test_websocket_handshake_uses_account_identity():
    client = HHWebSocketClient('tok', lambda e: None, user_agent='UA-acc', device_uuid='uuid-acc')
    assert client._user_agent == 'UA-acc'
    assert HHWebSocketClient('tok', lambda e: None)._user_agent.startswith('ru.hh.android/')


def test_apply_429_is_throttle_not_daily_quota(monkeypatch):
    monkeypatch.setattr(oauth, '_obtain_oauth_token', lambda acc: 'tok')
    monkeypatch.setattr(oauth, 'ensure_mutation_allowed', lambda acc: None)
    response = Mock(status_code=429, headers={'Retry-After': '120'}, content=b'{}')
    response.json.return_value = {}
    monkeypatch.setattr(oauth.HH, 'post', Mock(return_value=response))
    result, info = oauth._oauth_apply(ACC, '123')
    assert result == 'limit'
    assert info == {'http_429': True, 'retry_after_seconds': 120}
