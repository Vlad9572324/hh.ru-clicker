"""
Settings and raw config/accounts routes.
"""

from typing import Union

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.config import CONFIG, accounts_data, _CONFIG_KEYS, save_config, save_accounts


router = APIRouter()


class ConfigUpdate(BaseModel):
    key: str
    value: Union[bool, int, float, str]


def _safe_cast(key: str, value):
    """Cast `value` to the type of `CONFIG.<key>`. Raises ValueError on mismatch.
    Prevents type confusion (e.g. dict where int expected) и сохраняет инварианты Config.
    """
    old_val = getattr(CONFIG, key)
    expected = type(old_val)
    if expected is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str) and value.lower() in ("true", "false", "1", "0", "yes", "no"):
            return value.lower() in ("true", "1", "yes")
        raise ValueError(f"{key} expects bool, got {type(value).__name__}")
    if expected in (int, float):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return expected(value)
        if isinstance(value, str):
            return expected(value)
        raise ValueError(f"{key} expects {expected.__name__}, got {type(value).__name__}")
    if expected is str:
        return str(value)
    if expected in (list, dict):
        if not isinstance(value, expected):
            raise ValueError(f"{key} expects {expected.__name__}, got {type(value).__name__}")
        return value
    if isinstance(value, expected):
        return value
    raise ValueError(f"{key}: cannot cast {type(value).__name__} to {expected.__name__}")


@router.post("/api/settings")
async def api_settings(update: ConfigUpdate):
    if update.key not in _CONFIG_KEYS:
        return {"ok": False, "error": "Unknown key"}
    try:
        setattr(CONFIG, update.key, _safe_cast(update.key, update.value))
    except (ValueError, TypeError) as e:
        return {"ok": False, "error": str(e)}
    save_config()
    return {"ok": True, "key": update.key, "value": getattr(CONFIG, update.key)}


@router.get("/api/raw/config")
async def api_raw_config_get():
    """Вернуть текущий config как объект."""
    cfg = {k: getattr(CONFIG, k) for k in _CONFIG_KEYS}
    cfg["questionnaire_templates"] = CONFIG.questionnaire_templates
    cfg["letter_templates"] = CONFIG.letter_templates
    cfg["url_pool"] = CONFIG.url_pool
    return cfg


@router.post("/api/raw/config")
async def api_raw_config_set(request: Request):
    """Перезаписать config из JSON-объекта. Только разрешённые ключи + строгий кастинг типов."""
    try:
        data = await request.json()
    except Exception:
        return {"ok": False, "error": "Невалидный JSON"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "Ожидается объект"}
    errors = {}
    for key, value in data.items():
        if key in _CONFIG_KEYS:
            try:
                setattr(CONFIG, key, _safe_cast(key, value))
            except (ValueError, TypeError) as e:
                errors[key] = str(e)
        elif key == "questionnaire_templates" and isinstance(value, list):
            CONFIG.questionnaire_templates = value
        elif key == "letter_templates" and isinstance(value, list):
            CONFIG.letter_templates = value
        elif key == "url_pool" and isinstance(value, list):
            CONFIG.url_pool = value
        else:
            errors[key] = "unknown_or_wrong_type"
    save_config()
    return {"ok": not errors, "errors": errors}


@router.get("/api/raw/accounts")
async def api_raw_accounts_get():
    """Вернуть accounts без значений cookies (только ключи)."""
    safe = []
    for acc in accounts_data:
        a = {k: v for k, v in acc.items() if k != "cookies"}
        a["cookies"] = {k: "***" for k in acc.get("cookies", {})}
        safe.append(a)
    return safe


@router.post("/api/raw/accounts")
async def api_raw_accounts_set(request: Request):
    """Перезаписать accounts. Значение cookies '***' сохраняет старое."""
    try:
        data = await request.json()
    except Exception:
        return {"ok": False, "error": "Невалидный JSON"}
    if not isinstance(data, list):
        return {"ok": False, "error": "Ожидается массив"}
    old_by_name = {a.get("name", ""): a for a in accounts_data}
    merged = []
    for acc in data:
        if not isinstance(acc, dict):
            continue
        name = acc.get("name", "")
        old = old_by_name.get(name, {})
        new_cookies = acc.get("cookies", {})
        merged_cookies = {
            k: (old.get("cookies", {}).get(k, "") if v == "***" else v)
            for k, v in new_cookies.items()
        }
        for k, v in old.get("cookies", {}).items():
            if k not in merged_cookies:
                merged_cookies[k] = v
        acc = dict(acc)
        acc["cookies"] = merged_cookies
        merged.append(acc)
    # Atomic swap: clear()+extend() — non-atomic, readers могут увидеть [] между ними.
    accounts_data[:] = merged
    save_accounts()
    # Обновляем in-memory acc dict для уже-работающих AccountState'ов:
    # если имя совпадает — переписываем cookies/letter/urls/use_oauth.
    # Воркеры тут же подхватят свежие куки на следующем HTTP-запросе. Полная
    # пересборка account_states тут небезопасна — убъёт running threads.
    try:
        from app.instances import bot as _bot
        from app.logging_utils import log_debug
        by_name = {a.get("name", ""): a for a in merged}
        for state in _bot.account_states:
            new_acc = by_name.get(state.name)
            if new_acc:
                # Replace вместо update — иначе удалённые в JSON поля (use_oauth, letter)
                # остаются stale в state.acc (r11-1 #8). Сохраняем lock-ref defensive.
                cookies_lock = state.acc.get("_cookies_lock")
                state.acc.clear()
                state.acc.update(new_acc)
                if cookies_lock is not None:
                    state.acc["_cookies_lock"] = cookies_lock
                state.cookies_expired = False
    except Exception as e:
        log_debug(f"api_raw_accounts_set live-sync error: {e}")
    return {
        "ok": True,
        "count": len(merged),
        "warning": "Добавление/удаление аккаунтов требует перезапуска бота.",
    }
