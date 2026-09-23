"""Telegram delivery is opt-in and each HH event is delivered only once."""

import app.telegram_notify as telegram_notify


def test_send_once_delivers_once_and_persists_dedup(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(telegram_notify, "_NOTIFICATIONS_FILE", tmp_data_dir / "telegram_notifications.json")
    monkeypatch.setenv("HH_TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("HH_TELEGRAM_CHAT_ID", "12345")
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    monkeypatch.setattr(telegram_notify.requests, "post", lambda url, **kwargs: calls.append((url, kwargs)) or Response())

    assert telegram_notify.send_once("message:1", "Please reply") is True
    assert telegram_notify.send_once("message:1", "Please reply") is False
    assert len(calls) == 1
    assert calls[0][1]["json"]["chat_id"] == "12345"


def test_credentials_can_be_loaded_from_ignored_local_file(tmp_data_dir, monkeypatch):
    credentials = tmp_data_dir / "telegram.env"
    credentials.write_text("HH_TELEGRAM_BOT_TOKEN=file-token\nHH_TELEGRAM_CHAT_ID=-100123\n", encoding="utf-8")
    monkeypatch.setattr(telegram_notify, "_CREDENTIALS_FILE", credentials)
    monkeypatch.delenv("HH_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("HH_TELEGRAM_CHAT_ID", raising=False)

    assert telegram_notify.is_configured() is True
    assert telegram_notify._credentials() == ("file-token", "-100123")
