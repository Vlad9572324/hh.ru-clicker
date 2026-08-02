"""Тесты touch_resume: batch_update ветка и fallback на legacy touch при капче."""
import json
from types import SimpleNamespace

import app.hh_apply as hh_apply


def _acc():
    return {"cookies": {"_xsrf": "x"}, "resume_hash": "hash"}


def _resp(status, body=None):
    body = {} if body is None else body
    return SimpleNamespace(status_code=status, text=json.dumps(body), json=lambda: body)


def test_touch_resume_batch_update_success_branch(monkeypatch):
    monkeypatch.setattr(hh_apply, "_oauth_touch_resume", lambda acc: (False, "err"))
    urls = []

    def post(url, **kw):
        urls.append(url)
        return _resp(200, {})

    monkeypatch.setattr(hh_apply, "HH", SimpleNamespace(post=post))

    ok, msg = hh_apply.touch_resume(_acc())
    assert ok and "batch_update" in msg
    # legacy /applicant/resumes/touch не должен зваться
    assert not any("resumes/touch" in u for u in urls)


def test_touch_resume_batch_update_captcha_falls_through(monkeypatch):
    monkeypatch.setattr(hh_apply, "_oauth_touch_resume", lambda acc: (False, "err"))
    urls = []

    def post(url, **kw):
        urls.append(url)
        if "batch_update" in url:
            return _resp(200, {"hhcaptcha": {"isBot": True, "captchaState": "x"}})
        return _resp(200, {})

    monkeypatch.setattr(hh_apply, "HH", SimpleNamespace(post=post))

    ok, msg = hh_apply.touch_resume(_acc())
    assert (ok, msg) == (True, "Резюме поднято (web)!")
    # капча на batch_update → провалились в legacy touch, оба URL звались
    assert any("batch_update" in u for u in urls)
    assert any("resumes/touch" in u for u in urls)
