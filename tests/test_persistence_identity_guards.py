"""Account identity and all-before-any validation of persistence routes."""
import asyncio
import threading
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import config, instances, storage
from app.routes import sessions, settings


class Request:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


def _state(name):
    return SimpleNamespace(name=name, short=name, color='blue',
        acc={'name': name, 'short': name, 'resume_hash': name + '-resume',
             'cookies': {'hhtoken': name + '-cookie'}},
        _state_lock=threading.Lock(), _deleted=False, paused=False)


@pytest.fixture
def raw_runtime(monkeypatch):
    first, second = _state('A'), _state('B')
    rows = [deepcopy(first.acc), deepcopy(second.acc)]
    manager = SimpleNamespace(account_states=[first, second], temp_states={})
    save = Mock()
    monkeypatch.setattr(instances, 'bot', manager)
    monkeypatch.setattr(settings, 'accounts_data', rows)
    monkeypatch.setattr(settings, 'save_accounts', save)
    return manager, rows, save


def test_raw_new_account_cannot_desynchronize_persistent_and_live_indices(raw_runtime):
    manager, rows, save = raw_runtime
    before = deepcopy(rows)
    result = asyncio.run(settings.api_raw_accounts_set(Request([
        {'name': 'NEW', 'cookies': {}, 'resume_hash': 'new-resume'}, *deepcopy(rows)])))
    assert result['ok'] is False
    assert 'карточк' in result['error']
    assert rows == before
    assert [state.name for state in manager.account_states] == ['A', 'B']
    save.assert_not_called()


@pytest.mark.parametrize('entry', [None, 'bad', {}, {'name': 'C'},
    {'name': 'A', 'cookies': None}, {'name': 'A', 'cookies': []},
    {'name': 'A', 'cookies': {'hhtoken': 1}}])
def test_raw_bad_entry_does_not_silently_delete_other_accounts(raw_runtime, entry):
    manager, rows, save = raw_runtime
    before = deepcopy(rows)
    result = asyncio.run(settings.api_raw_accounts_set(Request([deepcopy(rows[0]), entry])))
    assert result['ok'] is False
    assert rows == before
    assert len(manager.account_states) == 2
    assert all(not state._deleted for state in manager.account_states)
    save.assert_not_called()


def test_raw_duplicate_names_are_rejected_without_partial_changes(raw_runtime):
    manager, rows, save = raw_runtime
    before = deepcopy(rows)
    result = asyncio.run(settings.api_raw_accounts_set(Request([deepcopy(rows[0]), deepcopy(rows[0])])))
    assert result['ok'] is False
    assert rows == before
    assert len(manager.account_states) == 2
    save.assert_not_called()


def test_raw_existing_accounts_can_be_reordered_and_masked_cookies_preserved(raw_runtime):
    manager, rows, save = raw_runtime
    original_states = list(manager.account_states)
    body = [deepcopy(rows[1]), deepcopy(rows[0])]
    for account in body:
        account['cookies']['hhtoken'] = '***'
    result = asyncio.run(settings.api_raw_accounts_set(Request(body)))
    assert result['ok'] is True
    assert manager.account_states == list(reversed(original_states))
    assert [row['name'] for row in rows] == ['B', 'A']
    assert [row['cookies']['hhtoken'] for row in rows] == ['B-cookie', 'A-cookie']
    save.assert_called_once()


@pytest.mark.parametrize('body', [
    {}, {'version': 1}, {'config.json': None}, {'unknown.json': {}},
    {'accounts.json': {}}, {'accounts.json': [None]},
    {'accounts.json': [{'cookies': 'invalid'}]},
    {'accounts.json': [{'name': []}]},
    {'browser_sessions.json': 'invalid'},
    {'browser_sessions.json': [{'urls': 'not-a-list'}]},
    {'config.json': []}, {'config.json': {'llm_profiles': {}}},
    {'oauth_tokens.json': []}, {'oauth_tokens.json': {'resume': 'token'}},
    {'oauth_tokens.json': {'resume': {'access_token': []}}},
    # A valid earlier file must not be written before validating later files.
    {'config.json': {}, 'accounts.json': [None]},
])
def test_invalid_backup_is_rejected_before_quiescing_or_writing(monkeypatch, body):
    state = _state('A')
    manager = SimpleNamespace(account_states=[state], temp_states={}, temp_sessions=[])
    write, quiesce = Mock(), Mock()
    monkeypatch.setattr(instances, 'bot', manager)
    monkeypatch.setattr(storage, '_atomic_write_json', write)
    monkeypatch.setattr(settings, '_quiesce_runtime', quiesce)
    result = asyncio.run(settings.api_backup_restore(Request(body)))
    assert result['ok'] is False
    assert manager.account_states == [state]
    assert state._deleted is False
    write.assert_not_called()
    quiesce.assert_not_called()


def test_valid_empty_account_backup_remains_an_explicit_restore(monkeypatch):
    manager = SimpleNamespace(account_states=[], temp_states={}, temp_sessions=[])
    writer, quiesce = Mock(), Mock()
    monkeypatch.setattr(instances, 'bot', manager)
    monkeypatch.setattr(storage, '_atomic_write_json', writer)
    monkeypatch.setattr(settings, '_quiesce_runtime', quiesce)
    monkeypatch.setattr(config, 'load_config', Mock())
    monkeypatch.setattr(config, 'load_accounts', Mock())
    monkeypatch.setattr(settings, 'load_browser_sessions', Mock(return_value=[]))
    result = asyncio.run(settings.api_backup_restore(Request({'accounts.json': []})))
    assert result['ok'] is True
    assert result['restored'] == ['accounts.json']
    writer.assert_called_once()
    quiesce.assert_called_once()


@pytest.mark.parametrize('delete_idx,refresh_idx', [(0, 0), (0, 1), (1, 1)])
def test_session_refresh_rechecks_identity_after_concurrent_delete(monkeypatch, delete_idx, refresh_idx):
    first = {'name': 'A', 'resume_hash': 'A-own', 'cookies': {}}
    second = {'name': 'B', 'resume_hash': 'B-own', 'cookies': {}}
    target = [first, second][refresh_idx]
    target_before = deepcopy(target)
    untouched = [first, second][1 - refresh_idx]
    untouched_before = deepcopy(untouched)
    manager = SimpleNamespace(account_states=[], temp_states={},
        temp_sessions=[first, second], _activate_lock=threading.Lock())
    monkeypatch.setattr(sessions, 'bot', manager)
    monkeypatch.setattr(sessions, 'save_browser_sessions', Mock())
    release = threading.Event()

    async def run():
        started = asyncio.Event()
        loop = asyncio.get_running_loop()
        def profiler(raw):
            loop.call_soon_threadsafe(started.set)
            assert release.wait(3)
            return {'ok': True, 'name': target_before['name'] + '-fresh',
                    'resume_hash': target_before['resume_hash'] + '-fresh',
                    'all_resumes': [{'title': 'Engineer'}]}
        monkeypatch.setattr(sessions, '_validate_and_profile', profiler)
        refresh = asyncio.create_task(sessions.api_session_refresh(refresh_idx))
        await asyncio.wait_for(started.wait(), 1)
        await sessions.api_session_delete(delete_idx)
        release.set()
        result = await refresh
        if delete_idx == refresh_idx:
            assert result['status'] == 'error'
            assert target == target_before
        else:
            assert result['status'] == 'ok'
            assert manager.temp_sessions[0] is target
            assert target['resume_hash'] == target_before['resume_hash'] + '-fresh'
        assert untouched == untouched_before
    try:
        asyncio.run(run())
    finally:
        release.set()
