"""Тест: флаг _active_search_forced выставляется только при успешном PUT."""
from types import SimpleNamespace

import app.hh_resume as hh_resume
from app.state import AccountState

ACC = {"cookies": {"_xsrf": "x"}}


def _state():
    return AccountState({"name": "Test", "short": "T", "color": "red", "urls": []})


def _force_active_search(state, acc):
    # Инлайн-логика из manager._run_account_worker_inner: флаг только при ok,
    # иначе retry на следующем перезапуске воркера
    if not state._active_search_forced:
        r = hh_resume.set_job_search_status(acc, "active_search")
        if r.get("ok"):
            state._active_search_forced = True
    return state._active_search_forced


def test_worker_forces_active_search_only_on_success(monkeypatch):
    put_ok = SimpleNamespace(put=lambda *a, **kw: SimpleNamespace(status_code=200, text=""))
    monkeypatch.setattr(hh_resume, "HH", put_ok)
    assert _force_active_search(_state(), ACC) is True

    put_fail = SimpleNamespace(put=lambda *a, **kw: SimpleNamespace(status_code=500, text="boom"))
    monkeypatch.setattr(hh_resume, "HH", put_fail)
    assert _force_active_search(_state(), ACC) is False
