"""Route tests for the HH AI Hedi dashboard API."""

from fastapi.testclient import TestClient

import app.routes.hedi as route
from app.instances import bot
from app.routes import app


class FakeClient:
    mode = "mobile"

    def __init__(self):
        self.sent = []

    def start_hedi(self):
        return "hedi-42"

    def fetch_thread(self, chat_id):
        return {"messages": [{"sender": "employer", "text": "Привет", "msg_id": "1"}]}

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))
        return True


def _setup(monkeypatch, acc):
    fake = FakeClient()
    monkeypatch.setattr(bot, "_get_apply_acc", lambda idx: acc if idx == 0 else None)
    monkeypatch.setattr(route, "get_client", lambda account: fake)
    route._chat_ids.clear()
    return TestClient(app), fake


def test_hedi_success(monkeypatch):
    client, fake = _setup(monkeypatch, {"mode": "mobile", "name": "test"})
    assert client.get("/api/account/0/hedi/start").json()["chat_id"] == "hedi-42"
    history = client.get("/api/account/0/hedi/history").json()
    assert history["messages"][0]["text"] == "Привет"
    response = client.post("/api/account/0/hedi/send", json={"text": " Найди Python "})
    assert response.status_code == 200
    assert fake.sent == [("hedi-42", "Найди Python")]


def test_hedi_requires_mobile(monkeypatch):
    client, _ = _setup(monkeypatch, {"mode": "web"})
    response = client.get("/api/account/0/hedi/start")
    assert response.status_code == 400
    assert response.json()["detail"] == "hedi requires mobile mode"


def test_hedi_account_not_found(monkeypatch):
    client, _ = _setup(monkeypatch, {"mode": "mobile"})
    response = client.get("/api/account/99/hedi/start")
    assert response.status_code == 404


def test_hedi_rejects_empty_message(monkeypatch):
    client, _ = _setup(monkeypatch, {"mode": "mobile"})
    response = client.post("/api/account/0/hedi/send", json={"text": "  "})
    assert response.status_code == 422
