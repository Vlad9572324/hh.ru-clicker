"""Отправка workflow-transition кнопки robot-chat через mobile API."""

import json

import responses

from app import oauth
from app.hh_client_mobile import MobileHHClient
from app.hh_client_web import WebHHClient
from app.hh_mobile_transport import MOBILE_BASE


ACC = {"name": "a1", "mode": "mobile", "cookies": {}, "resume_hash": "rh1"}


@responses.activate
def test_send_workflow_event_posts_expected_payload(monkeypatch):
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda acc: "token")
    responses.add(
        responses.POST,
        MOBILE_BASE + "/chats/777/event",
        status=204,
    )

    assert MobileHHClient(ACC).send_workflow_event(
        "777", "APPLICANT_READY", {"answer_id": "ready"}
    ) is True

    request = responses.calls[0].request
    assert request.method == "POST"
    assert json.loads(request.body) == {
        "event_type": "APPLICANT_READY",
        "event_params": {"answer_id": "ready"},
    }
    assert request.headers["Authorization"] == "Bearer token"


def test_web_workflow_event_is_safe_fallback():
    assert WebHHClient(ACC).send_workflow_event("777", "APPLICANT_READY", {}) is False
