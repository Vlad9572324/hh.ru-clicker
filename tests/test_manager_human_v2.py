"""Run the worker's real dispatch branches with isolated HTTP and clocks."""
import ast
import copy
import inspect
import textwrap
import threading
from unittest.mock import Mock

import pytest

from app import human_pace as pace, manager as module
from app.config import CONFIG
from app.manager import BotManager
from app.state import AccountState


@pytest.fixture
def worker(monkeypatch):
    state = AccountState({'name': 'human-v2', 'short': 'V2', 'color': '', 'resume_hash': 'test', 'user_id': 'v2', 'urls': []})
    bot = BotManager.__new__(BotManager)
    bot.paused = False
    bot.account_states = [state]
    bot.temp_states = {}
    bot._stop_event = threading.Event()
    bot._persist_pauses = Mock()
    bot._add_log = Mock()
    bot._activity_vacancy = Mock()
    bot._maybe_roll_daily_counter = Mock(return_value=False)
    monkeypatch.setattr(CONFIG, 'human_mode_enabled', True)
    monkeypatch.setattr(CONFIG, 'use_oauth_apply', False)
    monkeypatch.setattr(CONFIG, 'remote_it_only', False)
    monkeypatch.setattr(CONFIG, 'fresh_vacancies_mode', False)
    monkeypatch.setattr(CONFIG, 'daily_apply_limit', 100)
    monkeypatch.setattr(CONFIG, 'hh_daily_limit', 200)
    monkeypatch.setattr(CONFIG, 'response_delay', 0)
    monkeypatch.setattr(pace, 'sleep_until_active_hour', Mock())
    monkeypatch.setattr(pace, 'is_active_hour', lambda: True)
    monkeypatch.setattr(pace, 'random_apply_delay', lambda: 20)
    monkeypatch.setattr(pace, 'delay_multiplier', lambda state: 1)
    monkeypatch.setattr(pace, 'interruptible_wait', lambda event, seconds, allowed: not event.is_set() and allowed())
    monkeypatch.setattr(module, 'set_activity', Mock())
    monkeypatch.setattr(module, 'cycle_outcome', Mock())
    bot._bind_mutation_guard(state)
    return bot, state


def run_dispatch_loop(bot, state, vacancies):
    # Collection/storage/accounting are covered elsewhere. Execute the actual
    # window, skip, pace, pre-send recheck and HTTP dispatch from the worker.
    tree = ast.parse(textwrap.dedent(inspect.getsource(BotManager._run_account_worker_inner)))
    loop = next(node for node in ast.walk(tree) if isinstance(node, ast.While)
                and ast.unparse(node.test) == 'i < len(filtered)')
    source = lambda node: ast.unparse(node)
    batch = next(node for node in loop.body if isinstance(node, ast.Assign)
                 and source(node).startswith('batch = _cap_apply_batch'))
    skip = next(node for node in loop.body if isinstance(node, ast.If) and 'random_skip_vacancy' in source(node.test))
    accounts = next(node for node in loop.body if isinstance(node, ast.Assign)
                    and source(node).startswith('attempt_accounts ='))
    guards = next(node for node in loop.body if isinstance(node, ast.For)
                  and 'attempt_accounts.items()' in source(node))
    pacing = next(node for node in loop.body if isinstance(node, ast.If) and '_wait_human_pace' in source(node))
    recheck = next(node for node in loop.body if isinstance(node, ast.Assign) and '_recheck_apply_batch' in source(node))
    dispatch = next(node for node in loop.body if isinstance(node, ast.If) and source(node.test).startswith('state.use_oauth or'))
    loop.body = copy.deepcopy(loop.body[:2] + [batch, skip, accounts, guards, pacing, recheck, dispatch])
    loop.body += ast.parse('i += batch_size').body
    code = compile(ast.fix_missing_locations(ast.Module(body=[loop], type_ignores=[])), '<human-v2-worker>', 'exec')
    env = dict(vars(module), self=bot, state=state, acc=state.acc, i=0, filtered=vacancies)
    exec(code, env)


@pytest.mark.parametrize('oauth', [False, True])
def test_warm_up_precedes_each_apply(worker, monkeypatch, oauth):
    bot, state = worker
    state.use_oauth = oauth
    events = []
    monkeypatch.setattr(pace, 'random_skip_vacancy', lambda: False)
    monkeypatch.setattr(pace, 'reserve_attempt', lambda *a, **kw: events.append('reserve') or 0)
    monkeypatch.setattr(pace, 'warm_up_read_vacancy', lambda acc, vid: events.append(('warm', vid)))
    monkeypatch.setattr(module, '_oauth_apply', lambda acc, vid, letter: (events.append(('apply', vid)) or ('sent', {})))
    async def submit(vid, **kwargs):
        events.append(('apply', vid))
        return 'sent', {}
    monkeypatch.setattr(module, 'get_client', lambda acc: Mock(submit_response=submit))
    run_dispatch_loop(bot, state, ['1', '2'])
    assert events == ['reserve', ('warm', '1'), ('apply', '1'), 'reserve', ('warm', '2'), ('apply', '2')]


def test_skip_happens_before_reserving_or_applying(worker, monkeypatch):
    bot, state = worker
    state.use_oauth = True
    monkeypatch.setattr(pace, 'random_skip_vacancy', Mock(side_effect=[True, False]))
    reserve, warm, apply = Mock(return_value=0), Mock(), Mock(return_value=('sent', {}))
    monkeypatch.setattr(pace, 'reserve_attempt', reserve)
    monkeypatch.setattr(pace, 'warm_up_read_vacancy', warm)
    monkeypatch.setattr(module, '_oauth_apply', apply)
    run_dispatch_loop(bot, state, ['1', '2'])
    assert apply.call_count == reserve.call_count == warm.call_count == 1
    assert apply.call_args.args[1] == '2'
    assert warm.call_args.args[1] == '2'
    bot._add_log.assert_called_once_with(state.short, state.color, 'human: пропуск случайной вакансии', 'info')
    module.cycle_outcome.assert_called_once_with(state, '1', 'skipped', 'human_skip')


@pytest.mark.parametrize('cancel', ['stop', 'pause', 'delete', 'window', 'limit'])
def test_reading_cancellation_never_sends(worker, monkeypatch, cancel):
    bot, state = worker
    state.use_oauth = True
    monkeypatch.setattr(pace, 'random_skip_vacancy', lambda: False)
    monkeypatch.setattr(pace, 'reserve_attempt', lambda *args, **kwargs: 0)
    def warm(acc, vid):
        if cancel == 'stop': bot._stop_event.set()
        elif cancel == 'pause': state.paused = True
        elif cancel == 'delete': state._deleted = True
        elif cancel == 'window': monkeypatch.setattr(pace, 'is_active_hour', lambda: False)
        else: state.daily_sent = 100
    monkeypatch.setattr(pace, 'warm_up_read_vacancy', warm)
    apply = Mock()
    monkeypatch.setattr(module, '_oauth_apply', apply)
    run_dispatch_loop(bot, state, ['1'])
    apply.assert_not_called()


def test_disabled_mode_has_no_human_skips_or_reading(worker, monkeypatch):
    bot, state = worker
    state.use_oauth = True
    monkeypatch.setattr(CONFIG, 'human_mode_enabled', False)
    skip, warm = Mock(), Mock()
    apply = Mock(return_value=('sent', {}))
    monkeypatch.setattr(pace, 'random_skip_vacancy', skip)
    monkeypatch.setattr(pace, 'warm_up_read_vacancy', warm)
    monkeypatch.setattr(module, '_oauth_apply', apply)
    run_dispatch_loop(bot, state, ['1', '2'])
    assert apply.call_count == 2
    skip.assert_not_called()
    warm.assert_not_called()


def test_resume_wake_cannot_bypass_post_captcha_cooldown(worker, monkeypatch):
    bot, state = worker
    now = [10000.0]
    monkeypatch.setattr(pace.time, 'time', lambda: now[0])
    state.acc['_on_challenge']()
    assert state.paused_reason == 'challenge'
    state._captcha_wake = Mock(spec=threading.Event)
    bot.resume_challenge_account('v2')
    assert not state.paused
    assert not bot._can_mutate(state)
    state._captcha_wake.set.assert_called_once()
    waits = []
    def wait(*, timeout):
        assert 0 < timeout <= 1
        assert not bot._can_mutate(state)
        waits.append(timeout)
        # First call consumes the resume notification immediately.
        if len(waits) == 2:
            now[0] += pace.post_captcha_cooldown_sec()
    state._captcha_wake.wait.side_effect = wait
    assert bot._wait_post_captcha_cooldown(state)
    assert len(waits) == 2
    assert bot._can_mutate(state)


@pytest.mark.parametrize('cancel', ['stop', 'delete', 'pause'])
def test_cooldown_is_interruptible(worker, monkeypatch, cancel):
    bot, state = worker
    monkeypatch.setattr(pace.time, 'time', lambda: 10000)
    state.acc['_last_captcha_at'] = 9990
    state._captcha_wake = Mock(spec=threading.Event)
    def wait(**kwargs):
        if cancel == 'stop': bot._stop_event.set()
        elif cancel == 'delete': state._deleted = True
        else: state.paused = True
    state._captcha_wake.wait.side_effect = wait
    assert not bot._wait_post_captcha_cooldown(state)
    state._captcha_wake.wait.assert_called_once()


def test_start_jitter_once_even_after_worker_restart(worker, monkeypatch):
    bot, state = worker
    now = [1000.0]
    jitter = Mock(return_value=120)
    monkeypatch.setattr(pace, 'account_start_jitter', jitter)
    monkeypatch.setattr(pace.time, 'monotonic', lambda: now[0])
    def wait(event, seconds, allowed):
        assert allowed()
        now[0] += seconds
        return True
    monkeypatch.setattr(pace, 'interruptible_wait', wait)
    assert bot._wait_account_start_jitter(state)
    assert now[0] == 1120
    assert bot._wait_account_start_jitter(state)
    jitter.assert_called_once()


@pytest.mark.parametrize('idle,delay', [(None, 900), (2400, 2400)])
def test_long_idle_replaces_normal_burst_pause(worker, monkeypatch, idle, delay):
    bot, state = worker
    normal = Mock(return_value=900)
    wait = Mock(return_value=True)
    monkeypatch.setattr(pace, 'random_burst_size', lambda: 2)
    monkeypatch.setattr(pace, 'long_idle_burst', lambda: idle)
    monkeypatch.setattr(pace, 'random_burst_pause', normal)
    monkeypatch.setattr(pace, 'interruptible_wait', wait)
    assert bot._wait_human_burst(state)
    wait.assert_not_called()
    assert bot._wait_human_burst(state)
    assert wait.call_args.args[:2] == (bot._stop_event, delay)
    assert normal.call_count == int(idle is None)
    if idle:
        assert 'human: отвлёкся на 40 мин' in bot._add_log.call_args.args
