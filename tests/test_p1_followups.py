import asyncio

import pytest

from app import mobile_apply, mobile_touch_resume
from app.hh_client_fallback import FallbackHHClient
from app.hh_mobile_transport import MobileAPIError
from app.mobile_job_search_status import normalize_job_search_status


def test_apk_negotiation_visibility_schema(monkeypatch):
    captured = {}

    def fake_request(acc, method, path, **kwargs):
        captured.update(kwargs)
        return {"id": "n1"}

    monkeypatch.setattr(mobile_apply, "mobile_request", fake_request)
    result = mobile_apply.submit_response(
        {}, "v1", "r1", source_label="vacancy_search_for_you",
        required_applicant_visibility_id="visible-to-listed",
    )
    assert result["ok"] is True
    assert captured["params"]["source_label"] == "vacancy_search_for_you"
    assert captured["form"]["required_applicant_visibility_id"] == "visible-to-listed"
    assert captured["form"]["enable_applicant_visibility_in_country"] == "true"


def test_touch_cooldown_blocks_second_http_call(monkeypatch):
    acc = {}
    calls = []
    now = 1_000.0
    monkeypatch.setattr(mobile_touch_resume.time, "time", lambda: now)

    def limited(*args, **kwargs):
        calls.append(1)
        raise MobileAPIError(429, {"errors": [{"value": "touch_limit_exceeded"}]})

    monkeypatch.setattr(mobile_touch_resume, "mobile_request", limited)
    first = mobile_touch_resume.touch_resume(acc, "r1")
    second = mobile_touch_resume.touch_resume(acc, "r1")
    assert first == second == {"ok": False, "error": "touch_limit_active", "next_at": 15400.0}
    assert len(calls) == 1


def test_status_alias_is_normalized_before_fallback():
    calls = []

    class Mobile:
        acc = {}
        def set_job_search_status(self, status):
            calls.append(("mobile", status))
            raise MobileAPIError(401, {})

    class Web:
        def set_job_search_status(self, status):
            calls.append(("web", status))
            return {"ok": True, "status": status}

    result = FallbackHHClient(Mobile(), Web()).set_job_search_status("considering")
    assert normalize_job_search_status("considering") == "looking_for_offers"
    assert result["status"] == "looking_for_offers"
    assert calls == [("mobile", "looking_for_offers"), ("web", "looking_for_offers")]
