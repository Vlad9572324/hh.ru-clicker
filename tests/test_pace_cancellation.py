from unittest.mock import Mock
from app.human_pace import interruptible_wait

import ast
import inspect
import textwrap
import threading
from datetime import datetime, timedelta, timezone

import pytest

from app import human_pace as pace
from app import manager as module
from app.config import CONFIG
from app.manager import BotManager
from app.state import AccountState


def test_pause_interrupts_wait_without_full_delay():
    event = Mock()
    event.is_set.return_value = False
    event.wait.return_value = False
    allowed = Mock(side_effect=[True, False])
    assert interruptible_wait(event, 3600, allowed) is False
    event.wait.assert_called_once()
    assert event.wait.call_args.args[0] <= 1


def test_stopped_never_waits():
    event = Mock()
    event.is_set.return_value = True
    assert interruptible_wait(event, 3600) is False
    event.wait.assert_not_called()


def test_global_pause_interrupts_active_window_wait(monkeypatch):
    monkeypatch.setattr(CONFIG, 'human_mode_enabled', True)
    monkeypatch.setattr(CONFIG, 'human_active_hours', '07-24')
    monkeypatch.setattr(pace, 'is_active_hour', lambda **kwargs: False)
    state = AccountState({'name': 'window-test', 'short': 'P', 'color': '', 'urls': []})
    bot = BotManager.__new__(BotManager)
    bot.paused = False
    bot._stop_event = Mock(spec=threading.Event)
    bot._stop_event.is_set.return_value = False
    def pause(seconds):
        assert seconds <= 1
        bot.paused = True
        return False
    bot._stop_event.wait.side_effect = pause
    monkeypatch.setattr(pace, 'reserve_attempt', Mock())
    assert bot._wait_human_pace(state) is False
    bot._stop_event.wait.assert_called_once()
    pace.reserve_attempt.assert_not_called()


@pytest.fixture
def dispatch(monkeypatch):
    state = AccountState({'name': 'dispatch-test', 'short': 'P', 'color': '', 'urls': []})
    bot = BotManager.__new__(BotManager)
    bot.paused = False
    bot._stop_event = threading.Event()
    bot._persist_pauses = Mock()
    monkeypatch.setattr(CONFIG, 'daily_apply_limit', 200)
    monkeypatch.setattr(CONFIG, 'hh_daily_limit', 200)
    monkeypatch.setattr(CONFIG, 'fresh_vacancies_mode', False)
    monkeypatch.setattr(CONFIG, 'remote_it_only', False)
    monkeypatch.setattr(CONFIG, 'human_mode_enabled', True)
    monkeypatch.setattr(pace, 'is_active_hour', lambda **kwargs: True)
    monkeypatch.setattr(module, 'quarantine_blocked', lambda *args: False)
    return bot, state


@pytest.mark.parametrize('counter', ['daily_sent', 'hh_today_applies'])
def test_count_updated_during_wait_blocks_dispatch_and_shows_limit(dispatch, counter):
    bot, state = dispatch
    assert bot._can_dispatch_apply(state, 'a')
    setattr(state, counter, 200)
    assert not bot._can_dispatch_apply(state, 'a')
    assert bot._recheck_apply_batch(state, ['a']) == []
    assert state.paused and state.paused_reason == 'limit' and state.hard_stopped
    assert '200/200' in state.status_detail
    bot._persist_pauses.assert_called_once()


def test_lowered_limit_recaps_ready_batch(dispatch, monkeypatch):
    bot, state = dispatch
    state.daily_sent = 98
    monkeypatch.setattr(CONFIG, 'daily_apply_limit', 100)
    assert bot._recheck_apply_batch(state, ['a', 'b', 'c']) == ['a', 'b']
    assert not state.paused


def test_fresh_reserve_updated_during_wait_blocks_old_but_not_fresh(dispatch, monkeypatch):
    bot, state = dispatch
    monkeypatch.setattr(CONFIG, 'fresh_vacancies_mode', True)
    monkeypatch.setattr(CONFIG, 'fresh_apply_reserve', 50)
    monkeypatch.setattr(CONFIG, 'fresh_vacancy_hours', 24)
    state.vacancy_meta = {'fresh': {'published_at': datetime.now(timezone.utc).isoformat()},
                          'old': {'published_at': (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()}}
    state.hh_today_applies = 149
    assert bot._can_dispatch_apply(state, 'old')
    state.hh_today_applies = 150
    assert not bot._can_dispatch_apply(state, 'old')
    assert bot._can_dispatch_apply(state, 'fresh')
    assert bot._recheck_apply_batch(state, ['old', 'fresh']) == ['fresh']
    assert state.fresh_reserved_skipped == 1
    assert not state.paused
    # Current-cycle deferral must not become persistent "already applied".
    state.hh_today_applies = 149
    assert bot._recheck_apply_batch(state, ['old']) == ['old']


def test_confirmed_oauth_results_in_current_batch_consume_slots(dispatch, monkeypatch):
    bot, state = dispatch
    state.hh_today_applies = 199
    assert bot._can_dispatch_apply(state, 'a')
    state._unaccounted_apply_successes = 1
    assert not bot._can_dispatch_apply(state, 'b')
    monkeypatch.setattr(CONFIG, 'fresh_vacancies_mode', True)
    monkeypatch.setattr(CONFIG, 'fresh_apply_reserve', 50)
    state.hh_today_applies = 149
    assert not bot._can_dispatch_apply(state, 'old')
    state._unaccounted_apply_successes = 0
    assert bot._can_dispatch_apply(state, 'old')


def test_mixed_batch_cannot_use_old_slot_consumed_by_fresh_response(dispatch, monkeypatch):
    bot, state = dispatch
    monkeypatch.setattr(CONFIG, 'fresh_vacancies_mode', True)
    monkeypatch.setattr(CONFIG, 'fresh_apply_reserve', 50)
    state.hh_today_applies = 149
    state.vacancy_meta = {'fresh': {'published_at': datetime.now(timezone.utc).isoformat()}}
    assert bot._recheck_apply_batch(state, ['fresh', 'old']) == ['fresh']


def test_actual_oauth_dispatch_sees_new_tracker_count_and_earlier_success(dispatch, monkeypatch):
    bot, state = dispatch
    state.use_oauth = True
    state.hh_today_applies = 197
    monkeypatch.setattr(CONFIG, 'human_mode_enabled', False)
    monkeypatch.setattr(CONFIG, 'response_delay', 0)
    attempts = []
    def submit(acc, vid, letter):
        if not acc['_mutation_guard']():
            return 'cancelled', {}
        attempts.append(vid)
        state.hh_today_applies = 199  # Another device/tracker updated during I/O.
        return 'sent', {}
    monkeypatch.setattr(module, '_oauth_apply', submit)
    tree = ast.parse(textwrap.dedent(inspect.getsource(BotManager._run_account_worker_inner)))
    branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                  and ast.unparse(n.test).startswith('state.use_oauth or'))
    code = compile(ast.fix_missing_locations(ast.Module(body=[branch], type_ignores=[])),
                   '<oauth-budget-dispatch>', 'exec')
    accounts = {vid: {'_mutation_guard': lambda v=vid: bot._can_dispatch_apply(state, v)}
                for vid in ['a', 'b', 'c']}
    env = dict(vars(module), self=bot, state=state, acc=state.acc, i=0,
               batch=['a', 'b', 'c'], filtered=['a', 'b', 'c'], attempt_accounts=accounts)
    exec(code, env)
    assert attempts == ['a']
    assert [result[0] for result in env['results']] == ['sent', 'cancelled', 'cancelled']


def test_window_closing_after_reservation_blocks_write(dispatch, monkeypatch):
    bot, state = dispatch
    assert bot._can_dispatch_apply(state, 'a')
    monkeypatch.setattr(pace, 'is_active_hour', lambda **kwargs: False)
    assert not bot._can_dispatch_apply(state, 'a')


def test_recheck_preserves_newer_challenge_pause(dispatch):
    bot, state = dispatch
    state.paused = True
    state.paused_reason = 'challenge'
    state.daily_sent = 200
    assert bot._recheck_apply_batch(state, ['a']) == []
    assert state.paused_reason == 'challenge'
    bot._persist_pauses.assert_not_called()


def test_real_worker_rechecks_budgets_after_wait_before_dispatch():
    tree = ast.parse(textwrap.dedent(inspect.getsource(BotManager._run_account_worker_inner)))
    loop = next(n for n in ast.walk(tree) if isinstance(n, ast.While)
                and ast.unparse(n.test) == 'i < len(filtered)')
    pacing = next(n for n in loop.body if isinstance(n, ast.If) and '_wait_human_pace' in ast.unparse(n))
    recheck = next(n for n in loop.body if isinstance(n, ast.Assign) and '_recheck_apply_batch' in ast.unparse(n))
    dispatch = next(n for n in loop.body if isinstance(n, ast.If) and ast.unparse(n.test).startswith('state.use_oauth or'))
    assert loop.body.index(pacing) < loop.body.index(recheck) < loop.body.index(dispatch)
    assert any('_can_dispatch_apply' in ast.unparse(n) for n in ast.walk(loop) if isinstance(n, ast.Lambda))


@pytest.mark.parametrize('cancel', ['stop', 'delete'])
def test_worker_crash_backoff_is_interruptible(dispatch, monkeypatch, cancel):
    bot, state = dispatch
    bot._run_account_worker_inner = Mock(side_effect=RuntimeError('synthetic error'))
    bot._add_log = Mock()
    monkeypatch.setattr(module, 'log_exception', Mock())
    bot._stop_event = Mock(spec=threading.Event)
    bot._stop_event.is_set.return_value = False
    def stop_or_delete(seconds):
        assert seconds <= 1
        if cancel == 'delete':
            state._deleted = True
            return False
        bot._stop_event.is_set.return_value = True
        return True
    bot._stop_event.wait.side_effect = stop_or_delete
    bot._run_account_worker(0, state)
    bot._run_account_worker_inner.assert_called_once_with(0, state)
    bot._stop_event.wait.assert_called_once()
    assert state.status_detail != 'Перезапущен после ошибки'
