"""Telegram alerts for HH events that need a human response.

Credentials deliberately stay outside the dashboard configuration. Supply them
through the environment or the ignored ``data/telegram.env`` file.
"""

import json
import os
import threading
from datetime import datetime
from pathlib import Path

import requests

from app.logging_utils import log_debug


_NOTIFICATIONS_FILE = Path("data") / "telegram_notifications.json"
_CREDENTIALS_FILE = Path("data") / "telegram.env"
_LOCK = threading.Lock()
_MAX_EVENTS = 2000


def _credentials() -> tuple[str, str]:
    """Read credentials from the process environment or ignored local file."""
    token = os.environ.get("HH_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("HH_TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        return token, chat_id
    try:
        for raw_line in _CREDENTIALS_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "HH_TELEGRAM_BOT_TOKEN":
                token = value.strip()
            elif key.strip() == "HH_TELEGRAM_CHAT_ID":
                chat_id = value.strip()
    except FileNotFoundError:
        pass
    except Exception as exc:
        log_debug(f"telegram notifications: cannot read credentials: {exc}")
    return token, chat_id


def is_configured() -> bool:
    """Return True only when both locally supplied Telegram credentials exist."""
    token, chat_id = _credentials()
    return bool(token and chat_id)


def _load_sent_events() -> dict:
    try:
        with _NOTIFICATIONS_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log_debug(f"telegram notifications: cannot load sent events: {exc}")
        return {}


def _save_sent_events(events: dict) -> None:
    _NOTIFICATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if len(events) > _MAX_EVENTS:
        events = dict(sorted(events.items(), key=lambda item: item[1])[-_MAX_EVENTS:])
    tmp = _NOTIFICATIONS_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(events, handle, ensure_ascii=False, indent=2)
    tmp.replace(_NOTIFICATIONS_FILE)


def send_once(event_id: str, message: str, parse_mode: str = None) -> bool:
    """Deliver an alert once, broadcasting to all subscribers (multi-user).

    Fans out to admin chat_id + все `/start`-подписчики (data/telegram_subscribers.json).
    Событие помечается delivered если хотя бы один chat_id принял; для остальных
    ошибки логируются но не блокируют.
    """
    token, admin = _credentials()
    if not token:
        return False

    event_id = str(event_id).strip()
    message = str(message).strip()[:4000]
    if not event_id or not message:
        return False

    from app.telegram_subscribers import list_all as _sub_list
    chats = _sub_list()
    if not chats and admin:
        chats = [admin]  # fallback: если subscribers.json пуст, шлём хотя бы admin
    if not chats:
        return False

    with _LOCK:
        sent_events = _load_sent_events()
        if event_id in sent_events:
            return False
        any_ok = False
        for cid in chats:
            try:
                payload = {"chat_id": cid, "text": message,
                           "disable_web_page_preview": True}
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                response = requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json=payload, timeout=15,
                )
                response.raise_for_status()
                if response.json().get("ok"):
                    any_ok = True
                else:
                    log_debug(f"telegram broadcast to {cid}: rejected")
            except Exception as exc:
                log_debug(f"telegram broadcast to {cid} failed: {type(exc).__name__}")
        if not any_ok:
            return False
        sent_events[event_id] = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            _save_sent_events(sent_events)
        except Exception as exc:
            log_debug(f"telegram notifications: cannot save sent event: {exc}")
            return False
    return True
