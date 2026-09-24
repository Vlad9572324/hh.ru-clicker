"""Exercise worker dispatch and pacing with no HTTP or real sleeps."""
import ast
import copy
import inspect
import textwrap
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import manager as module
from app import human_pace as pace
from app.config import CONFIG
from app.manager import BotManager
from app.state import AccountState


@pytest.fixture
def harness(monkeypatch):
    state = AccountState({'name': 'pace-test', 'short': 'P', 'color': '', 'urls': []})
    bot = BotManager.__new__(BotManager)
    bot.paused = False
    bot._stop_event = Mock(spec=threading.Event)
    bot._stop_event.is_set.return_value = False
    bot._stop_event.wait.return_value = False
    bot._can_mutate = Mock(return_value=True)
    bot._activity_vacancy = Mock()
    bot._persist_pauses = Mock()
    monkeypatch.setattr(CONFIG, 'human_mode_enabled', True)
    monkeypatch.setattr(pace, 'random_apply_delay', Mock(return_value=10))
    monkeypatch.setattr(pace, 'random_burst_size', Mock(return_value=3))
    monkeypatch.setattr(pace, 'random_burst_pause', Mock(return_value=180))
    monkeypatch.setattr(pace, 'delay_multiplier', Mock(return_value=1))
    monkeypatch.setattr(module.time, 'monotonic', lambda: 1000)
    monkeypatch.setattr(module, 'set_activity', Mock())
    return bot, state


def test_burst_spans_batches_and_obeys_average_budget(harness):
    bot, state = harness
    for _ in range(3):
        bot._wait_human_pace(state)
    assert [c.args[0] for c in bot._stop_event.wait.call_args_list] == [10, 10, 10, 2700]
    pace.random_burst_pause.assert_called_once()
    assert state._human_burst_count == state._human_burst_target == 0


def test_backoff_and_weekend_slow_all_waits(harness, monkeypatch):
    bot, state = harness
    monkeypatch.setattr(pace, 'delay_multiplier', lambda state: 2 / .7)
    state._human_burst_target = 1
    state._human_burst_started = 1000
    bot._wait_human_pace(state)
    assert [c.args[0] for c in bot._stop_event.wait.call_args_list] == pytest.approx([10 * 2 / .7, 900 * 2 / .7])


def test_shutdown_interrupts_before_burst_pause(harness):
    bot, state = harness
    state._human_burst_target = 1
    bot._stop_event.wait.return_value = True
    bot._wait_human_pace(state)
    bot._stop_event.wait.assert_called_once_with(10)
    pace.random_burst_pause.assert_not_called()


def test_disabled_or_paused_does_not_wait(harness, monkeypatch):
    bot, state = harness
    monkeypatch.setattr(CONFIG, 'human_mode_enabled', False)
    bot._wait_human_pace(state)
    monkeypatch.setattr(CONFIG, 'human_mode_enabled', True)
    bot._can_mutate.return_value = False
    bot._wait_human_pace(state)
    bot._stop_event.wait.assert_not_called()


def test_challenge_callback_stamps_both_state_and_account(harness, monkeypatch):
    bot, state = harness
    monkeypatch.setattr(module.time, 'time', lambda: 12345)
    bot._bind_mutation_guard(state)
    state.acc['_on_challenge']()
    assert state._last_captcha_at == state.acc['_last_captcha_at'] == 12345
    assert state.paused and state.paused_reason == 'challenge'
    bot._persist_pauses.assert_called_once_with(wait=True)


@pytest.mark.parametrize('oauth', [False, True])
def test_real_worker_dispatch_uses_serial_attempts_and_pacing(harness, monkeypatch, oauth):
    # Isolate actual dispatch from the worker's collection/preflight/storage work,
    # following the existing worker-branch integration tests in this repository.
    bot, state = harness
    state.use_oauth = oauth
    monkeypatch.setattr(CONFIG, 'use_oauth_apply', False)
    monkeypatch.setattr(pace, 'sleep_until_active_hour', Mock())
    calls = []
    async def submit(vid, **kwargs):
        calls.append(vid)
        return ('sent', {})
    monkeypatch.setattr(module, 'get_client', lambda acc: SimpleNamespace(submit_response=submit))
    monkeypatch.setattr(module, '_oauth_apply', lambda acc, vid, letter: (calls.append(vid) or ('sent', {})))
    tree = ast.parse(textwrap.dedent(inspect.getsource(BotManager._run_account_worker_inner)))
    loop = next(n for n in ast.walk(tree) if isinstance(n, ast.While) and ast.unparse(n.test) == 'i < len(filtered)')
    dispatch = next(n for n in loop.body if isinstance(n, ast.If) and ast.unparse(n.test).startswith('state.use_oauth or'))
    pacing = next(n for n in loop.body if isinstance(n, ast.If) and ast.unparse(n.test) == 'CONFIG.human_mode_enabled and results')
    # Execute the real window gate and batch-size assignment before dispatch.
    nodes = copy.deepcopy(loop.body[:2])
    setup = ast.parse('batch = filtered[i:i + batch_size]').body
    nodes += setup + [copy.deepcopy(dispatch), copy.deepcopy(pacing)]
    code = compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), '<human-worker-dispatch>', 'exec')
    env = dict(vars(module), self=bot, state=state, acc=state.acc,
               filtered=['a', 'b', 'c'], attempt_accounts={v: {} for v in 'abc'})
    for i in range(3):
        env['i'] = i
        exec(code, env)
        assert env['batch_size'] == 1
    assert calls == ['a', 'b', 'c']
    assert pace.sleep_until_active_hour.call_count == 3
    assert [c.args[0] for c in bot._stop_event.wait.call_args_list] == [10, 10, 10, 2700]
