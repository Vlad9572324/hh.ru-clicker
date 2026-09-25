"""Multi-user Telegram broadcast: держит список chat_id-подписчиков.

Юзеры добавляются через `/start` в боте, удаляются через `/stop`.
Admin chat_id (из ENV HH_TELEGRAM_CHAT_ID / CONFIG.telegram_chat_id) всегда
включён неявно и не может быть удалён `/stop`.

Файл `data/telegram_subscribers.json`:
    {"subscribers": ["1037556703", "2345678"], "added_at": {...}}
"""
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.logging_utils import log_debug
from app.storage import _atomic_write_json


_PATH = Path("data/telegram_subscribers.json")
_LOCK = threading.RLock()


def _resolved_path() -> Path:
    """Актуальный путь: учитывает monkeypatch app.storage.DATA_DIR в тестах."""
    try:
        from app.storage import DATA_DIR as _D
        return Path(_D) / "telegram_subscribers.json"
    except Exception:
        return _PATH


def _admin_chat_id() -> str:
    """Admin из ENV или CONFIG.telegram_chat_id — приемник по умолчанию."""
    for key in ("TELEGRAM_CHAT_ID", "HH_TELEGRAM_CHAT_ID"):
        v = os.environ.get(key, "").strip()
        if v:
            return v
    try:
        from app.config import CONFIG
        return str(getattr(CONFIG, "telegram_chat_id", "") or "").strip()
    except Exception:
        return ""


def _read() -> dict:
    if not _resolved_path().exists():
        return {"subscribers": [], "added_at": {}}
    try:
        data = json.loads(_resolved_path().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"subscribers": [], "added_at": {}}
        subs = data.get("subscribers") or []
        return {"subscribers": [str(s) for s in subs if s],
                "added_at": data.get("added_at") or {}}
    except Exception as e:
        log_debug(f"telegram_subscribers read error: {e}")
        return {"subscribers": [], "added_at": {}}


def list_all() -> list[str]:
    """Все chat_ids для рассылки: admin + подписавшиеся, без дубликатов."""
    with _LOCK:
        data = _read()
        chats = list(data["subscribers"])
        admin = _admin_chat_id()
        if admin and admin not in chats:
            chats.insert(0, admin)
        return chats


def add(chat_id) -> bool:
    """Добавить подписчика. Возвращает True если новый, False если уже был."""
    chat_id = str(chat_id).strip()
    if not chat_id:
        return False
    with _LOCK:
        data = _read()
        if chat_id in data["subscribers"]:
            return False
        data["subscribers"].append(chat_id)
        data["added_at"][chat_id] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _atomic_write_json(_resolved_path(), data)
        return True


def remove(chat_id) -> bool:
    """Удалить подписчика. Admin неудаляем."""
    chat_id = str(chat_id).strip()
    if not chat_id or chat_id == _admin_chat_id():
        return False
    with _LOCK:
        data = _read()
        if chat_id not in data["subscribers"]:
            return False
        data["subscribers"].remove(chat_id)
        data["added_at"].pop(chat_id, None)
        _atomic_write_json(_resolved_path(), data)
        return True


def is_known(chat_id) -> bool:
    """Проверить, что chat_id уже в списке (admin или подписчик)."""
    return str(chat_id).strip() in list_all()
