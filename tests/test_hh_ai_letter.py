"""Тесты generate_hh_ai_letter (HH-Pro AI письмо). pytest-asyncio нет — asyncio.run."""
import asyncio
import json
from types import SimpleNamespace

import app.hh_apply as hh_apply


def _resp(status, body=None, text=None):
    body = {} if body is None else body
    return SimpleNamespace(
        status_code=status,
        text=text if text is not None else json.dumps(body),
        json=lambda: body,
    )


async def _no_sleep(_delay):
    pass


def test_generate_hh_ai_letter_service_already_used_returns_empty(monkeypatch):
    acc = {"cookies": {"_xsrf": "x"}}

    def _get_fail(*a, **kw):
        raise AssertionError("HH.get не должен вызываться после service_already_used")

    fake_hh = SimpleNamespace(
        post=lambda *a, **kw: _resp(400, text='{"error":"service_already_used"}'),
        get=_get_fail,
    )
    monkeypatch.setattr(hh_apply, "HH", fake_hh)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    assert asyncio.run(hh_apply.generate_hh_ai_letter(acc, "hash", "42")) == ""


def test_generate_hh_ai_letter_polls_until_letter(monkeypatch):
    acc = {"cookies": {"_xsrf": "x"}}
    poll = iter([_resp(200, {}), _resp(200, {"generatedLetter": "Текст"})])
    fake_hh = SimpleNamespace(
        post=lambda *a, **kw: _resp(202),
        get=lambda *a, **kw: next(poll),
    )
    monkeypatch.setattr(hh_apply, "HH", fake_hh)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    # Ключ именно generatedLetter — реальный формат HH
    assert asyncio.run(hh_apply.generate_hh_ai_letter(acc, "hash", "42")) == "Текст"
