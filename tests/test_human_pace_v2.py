"""Pacing probabilities, durable rate cuts and HTTP Retry-After contracts."""
import asyncio
from datetime import datetime, timezone
from email.utils import format_datetime
import random
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import human_pace as pace
from app.config import CONFIG, Config


@pytest.fixture
def rng(monkeypatch):
    value = Mock()
    value.uniform.side_effect = lambda low, high: (low + high) / 2
    monkeypatch.setattr(pace, '_rng', value)
    return value


def test_conservative_defaults():
    config = Config()
    assert (config.human_apply_delay_min, config.human_apply_delay_max) == (15, 45)
    assert (config.human_burst_size_min, config.human_burst_size_max) == (2, 4)
    assert (config.human_burst_pause_min_sec, config.human_burst_pause_max_sec) == (600, 1500)
    assert config.human_captcha_backoff_hours == 4
    assert pace.TARGET_APPLIES_PER_HOUR == 2.5


@pytest.mark.parametrize('draw,expected', [(0, True), (.299999, True), (.3, False), (.99999, False)])
def test_warm_up_probability_and_request_contract(monkeypatch, rng, draw, expected):
    rng.random.return_value = draw
    started = []
    def thread(*, target, **kwargs):
        assert kwargs['daemon'] is True
        return SimpleNamespace(start=lambda: (started.append(True), target()))
    monkeypatch.setattr(pace.threading, 'Thread', thread)
    response = Mock()
    get = Mock(return_value=response)
    monkeypatch.setattr(pace.HH, 'get', get)
    wait = Mock()
    acc = {'user_id': 'warm-account', 'resume_hash': 'resume', 'cookies': {'token': 'test'}, '_human_wait': wait}
    assert pace.warm_up_read_vacancy(acc, '123') is None
    assert bool(started) is expected
    assert get.call_count == int(expected)
    assert wait.call_count == int(expected)
    if expected:
        args, kwargs = get.call_args
        assert args == ('https://hh.ru/vacancy/123',)
        assert kwargs['cookies'] == acc['cookies']
        assert kwargs['cookie_jar_key']
        assert kwargs['timeout'] == 5
        assert kwargs['allow_redirects'] is False
        assert 'Mozilla/' in kwargs['headers']['User-Agent']
        assert 5 <= wait.call_args.args[0] <= 15
        response.close.assert_called_once()
        response.json.assert_not_called()


def test_warm_up_does_not_wait_for_response(monkeypatch, rng):
    rng.random.return_value = 0
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    response = Mock()
    response.close.side_effect = finished.set
    def get(*args, **kwargs):
        entered.set()
        release.wait(2)
        return response
    monkeypatch.setattr(pace.HH, 'get', get)
    try:
        pace.warm_up_read_vacancy({'resume_hash': 'test', '_human_wait': lambda seconds: None}, '123')
        assert entered.wait(1)
        assert not finished.is_set()
    finally:
        release.set()
        assert finished.wait(2)


def test_warm_up_network_failure_is_best_effort(monkeypatch, rng):
    rng.random.return_value = 0
    monkeypatch.setattr(pace.threading, 'Thread', lambda **kw: SimpleNamespace(start=kw['target']))
    monkeypatch.setattr(pace.HH, 'get', Mock(side_effect=TimeoutError))
    wait = Mock()
    pace.warm_up_read_vacancy({'resume_hash': 'test', '_human_wait': wait}, '123')
    wait.assert_called_once_with(10)


def test_warm_up_honours_cancellation(monkeypatch, rng):
    rng.random.return_value = 0
    get = Mock()
    monkeypatch.setattr(pace.HH, 'get', get)
    pace.warm_up_read_vacancy({'resume_hash': 'test', '_mutation_guard': lambda: False}, '123')
    get.assert_not_called()


@pytest.mark.parametrize('draw,expected', [(0, True), (.049999, True), (.05, False), (.99999, False)])
def test_skip_threshold(rng, draw, expected):
    rng.random.return_value = draw
    assert pace.random_skip_vacancy() is expected


@pytest.mark.parametrize('draw,expected', [(0, 2700), (.099999, 2700), (.1, None), (.99999, None)])
def test_long_idle_threshold(rng, draw, expected):
    rng.random.return_value = draw
    assert pace.long_idle_burst() == expected
    if expected is not None:
        rng.uniform.assert_called_once_with(1800, 3600)
    else:
        rng.uniform.assert_not_called()


def test_generated_delays_stay_in_bounds(monkeypatch):
    monkeypatch.setattr(pace, '_rng', random.Random(123))
    pauses = [pace.long_idle_burst() for _ in range(1000)]
    assert any(p is None for p in pauses)
    assert any(p is not None for p in pauses)
    assert all(p is None or 1800 <= p <= 3600 for p in pauses)
    assert all(0 <= pace.account_start_jitter() <= 300 for _ in range(1000))
    assert pace.post_captcha_cooldown_sec() == 1800


@pytest.mark.parametrize('age,expected', [(0, 3), (14399, 3), (14400, 1.5), (86399, 1.5), (86400, 1), (90000, 1), (-1, 1)])
@pytest.mark.parametrize('persisted', [False, True])
def test_post_captcha_rate_cut(monkeypatch, age, expected, persisted):
    monkeypatch.setattr(pace.time, 'time', lambda: 200000)
    monkeypatch.setattr(CONFIG, 'human_captcha_backoff_hours', 4)
    state = (SimpleNamespace(acc={'_last_captcha_at': 200000 - age}) if persisted
             else SimpleNamespace(_last_captcha_at=200000 - age))
    assert pace.post_captcha_rate_cut(state) == expected
    assert pace.post_captcha_rate_cut(SimpleNamespace()) == 1


def test_captcha_and_weekend_cut_extend_saved_interval(monkeypatch):
    monkeypatch.setattr(CONFIG, 'human_apply_delay_max', 45)
    monkeypatch.setattr(CONFIG, 'human_apply_delay_min', 15)
    monkeypatch.setattr(CONFIG, 'human_captcha_backoff_hours', 4)
    monkeypatch.setattr(pace.time, 'time', lambda: 200000)
    monkeypatch.setattr(pace, 'weekend_variance', lambda: .7)
    state = SimpleNamespace(acc={'user_id': 'cut'}, _last_captcha_at=199999)
    assert pace.delay_multiplier(state) == pytest.approx(3 / .7)
    assert pace.reserve_attempt(state.acc, now=1000) == 0
    remaining = pace.reserve_attempt(state.acc, now=1100, multiplier=pace.delay_multiplier(state))
    assert remaining == pytest.approx(1440 * 3 / .7 - 100)


@pytest.mark.parametrize('value,expected', [('0', 0), (' 123 ', 123), ('-5', 60), ('1.5', 60), ('invalid', 60), ('', 60)])
def test_retry_after_seconds_and_invalid_values(value, expected):
    assert pace.respect_retry_after({'rEtRy-AfTeR': value}, default_sec=60) == expected
    assert pace.respect_retry_after({}) == 0
    assert pace.respect_retry_after(None, default_sec=60) == 60


@pytest.mark.parametrize('offset,expected', [(90, 90), (1, 1), (-5, 0)])
def test_retry_after_http_date(monkeypatch, offset, expected):
    now = 2000000000
    monkeypatch.setattr(pace.time, 'time', lambda: now + .25)
    header = format_datetime(datetime.fromtimestamp(now + offset, timezone.utc), usegmt=True)
    assert pace.respect_retry_after({'Retry-After': header}) == expected


def test_mobile_429_waits_once_without_resubmitting(monkeypatch):
    from app import mobile_apply
    from app.hh_mobile_transport import MobileAPIError
    error = MobileAPIError(429, {})
    error.headers = {'Retry-After': '87'}
    request = Mock(side_effect=error)
    sleep = Mock()
    monkeypatch.setattr(mobile_apply, 'mobile_request', request)
    monkeypatch.setattr(mobile_apply.time, 'sleep', sleep)
    result = mobile_apply.submit_response({'resume_hash': 'test'}, '123', 'test')
    assert result['http_status'] == 429
    sleep.assert_called_once_with(87)
    request.assert_called_once()


@pytest.mark.skip(reason="requires hh_mobile_transport patch, out of scope")
def test_mobile_429_preserves_retry_after_from_http(monkeypatch):
    import responses
    from app import mobile_apply, oauth
    monkeypatch.setattr(oauth, '_obtain_oauth_token', lambda acc: 'test-token')
    sleep = Mock()
    monkeypatch.setattr(mobile_apply.time, 'sleep', sleep)
    with responses.RequestsMock() as http:
        http.add(responses.POST, 'https://api.hh.ru/negotiations', status=429,
                 json={'errors': []}, headers={'Retry-After': '37'})
        result = mobile_apply.submit_response({'resume_hash': 'test'}, '123', 'test')
        assert result['http_status'] == 429
        assert len(http.calls) == 1
    sleep.assert_called_once_with(37)


def test_web_preflight_429_waits_and_returns_retry(monkeypatch):
    from app import hh_apply
    response = Mock(status_code=429, text='', headers={'Retry-After': '12'})
    request = Mock(return_value=response)
    sleep = Mock()
    monkeypatch.setattr(hh_apply.HH, 'get', request)
    monkeypatch.setattr(hh_apply.time, 'sleep', sleep)
    result = hh_apply._check_vacancy_before_apply({'resume_hash': 'test'}, '123')
    assert result == {'ok': False, 'reason': 'rate_limit', 'skip_reason': 'retry', 'retry_after_seconds': 12}
    sleep.assert_called_once_with(12)
    request.assert_called_once()


def test_web_apply_429_uses_async_wait(monkeypatch):
    from app import hh_apply
    monkeypatch.setattr(CONFIG, 'hh_ai_letter_first_try', False)
    monkeypatch.setattr(hh_apply, '_aio_egress_kwargs', lambda: ({}, {}))
    response = AsyncMock(status=429, headers={'Retry-After': '23'})
    response.text.return_value = '{}'
    response.__aenter__.return_value = response
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.post = Mock(return_value=response)
    monkeypatch.setattr(hh_apply.aiohttp, 'ClientSession', Mock(return_value=session))
    sleep = AsyncMock()
    monkeypatch.setattr(hh_apply.asyncio, 'sleep', sleep)
    result = asyncio.run(hh_apply.send_response_async({'name': 'test', 'resume_hash': 'test', 'cookies': {'_xsrf': 'test'}}, '123'))
    assert result[0] != 'sent'
    sleep.assert_awaited_once_with(23)
    session.post.assert_called_once()
