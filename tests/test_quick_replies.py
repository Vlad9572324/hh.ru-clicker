"""Тесты fetch_quick_replies: форматы ответа HH и graceful-деградация."""
from types import SimpleNamespace

import app.hh_chat as hh_chat

ACC = {"cookies": {}}


def _hh(body, status=200, bad_json=False):
    def _json():
        if bad_json:
            raise ValueError("bad json")
        return body
    resp = SimpleNamespace(status_code=status, text="", json=_json)
    return SimpleNamespace(get=lambda *a, **kw: resp)


def test_fetch_quick_replies_parses_response_formats(monkeypatch):
    fetch = hh_chat.fetch_quick_replies

    monkeypatch.setattr(hh_chat, "HH", _hh({"quick_replies": [{"text": "Привет!"}]}))
    assert fetch(ACC, "c1", "m1") == ["Привет!"]

    monkeypatch.setattr(hh_chat, "HH", _hh({"items": ["str1", "str2"]}))
    assert fetch(ACC, "c1", "m1") == ["str1", "str2"]

    # Голый список — тоже валидный формат
    monkeypatch.setattr(hh_chat, "HH", _hh(["a", "b"]))
    assert fetch(ACC, "c1", "m1") == ["a", "b"]

    # dict без text — пропускаем
    monkeypatch.setattr(hh_chat, "HH", _hh({"quick_replies": [{"nope": 1}]}))
    assert fetch(ACC, "c1", "m1") == []

    # Пустые items
    monkeypatch.setattr(hh_chat, "HH", _hh({"items": []}))
    assert fetch(ACC, "c1", "m1") == []


def test_fetch_quick_replies_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(hh_chat, "HH", _hh({}, status=500))
    assert hh_chat.fetch_quick_replies(ACC, "c1", "m1") == []

    monkeypatch.setattr(hh_chat, "HH", _hh(None, bad_json=True))
    assert hh_chat.fetch_quick_replies(ACC, "c1", "m1") == []
