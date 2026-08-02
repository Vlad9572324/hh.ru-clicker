"""Тест: send_response_async режет письмо до letter_max_length."""
import asyncio

import app.hh_apply as hh_apply


class _FakeFormData:
    instances = []

    def __init__(self):
        self.fields = {}
        _FakeFormData.instances.append(self)

    def add_field(self, name, value):
        self.fields[name] = value


class _FakeResp:
    status = 200

    async def text(self):
        return '{"status":"ok"}'


class _FakePostCtx:
    async def __aenter__(self):
        return _FakeResp()

    async def __aexit__(self, *a):
        return False


class _FakeSession:
    def __init__(self, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def post(self, *a, **kw):
        return _FakePostCtx()


def test_send_response_async_truncates_letter_to_max_length(monkeypatch):
    acc = {"name": "T", "cookies": {"_xsrf": "x"}, "resume_hash": "h", "letter": "x" * 500}

    async def _no_ai_letter(*a, **kw):
        return ""

    monkeypatch.setattr(hh_apply, "generate_hh_ai_letter", _no_ai_letter)
    monkeypatch.setattr(hh_apply.aiohttp, "FormData", _FakeFormData)
    monkeypatch.setattr(hh_apply.aiohttp, "ClientSession", _FakeSession)
    _FakeFormData.instances.clear()

    result, _info = asyncio.run(hh_apply.send_response_async(acc, "42", letter_max_length=100))

    letter = _FakeFormData.instances[0].fields["letter"]
    assert result == "sent"
    assert len(letter) <= 100 and letter == letter.rstrip()
