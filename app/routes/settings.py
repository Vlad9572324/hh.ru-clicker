"""
Settings and raw config/accounts routes.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Union

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import CONFIG, accounts_data, _CONFIG_KEYS, save_config, save_accounts
from app.storage import load_browser_sessions, save_browser_sessions, DATA_DIR
from app.logging_utils import log_debug


router = APIRouter()


class ConfigUpdate(BaseModel):
    key: str
    # Pydantic union resolves left-to-right; bool(300000)=True раньше int → коэрсия
    # рушит integer config keys. Порядок: int → float → bool → str (kimi-r14-4 #5).
    value: Union[int, float, bool, str]


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


_RAW_LIST_KEYS = {
    "questionnaire_templates", "letter_templates", "url_pool",
    "allowed_schedules", "title_include_keywords", "title_exclude_keywords",
    "llm_profiles",
}
_RAW_LLM_KEYS = {
    "llm_enabled", "llm_auto_send", "llm_use_cover_letter", "llm_use_resume",
    "llm_api_key", "llm_base_url", "llm_model", "llm_applicant_gender", "llm_profile_mode",
    "llm_system_prompt", "llm_openclaw_enabled", "llm_openclaw_agent",
    "llm_openclaw_model", "llm_openclaw_timeout",
}
_RAW_EXTRA_KEYS = {"auto_apply_tests"}


def _all_raw_config_keys():
    """Все ключи которые покажем/примем в raw editor: whitelist + LLM + lists."""
    return set(_CONFIG_KEYS) | _RAW_LIST_KEYS | _RAW_LLM_KEYS | _RAW_EXTRA_KEYS


@router.get("/api/raw/config")
async def api_raw_config_get():
    """Вернуть текущий config как объект — с llm_api_key и всеми LLM-ключами,
    чтобы юзер видел актуальные значения и мог бэкапить вручную."""
    out = {}
    for k in sorted(_all_raw_config_keys()):
        if hasattr(CONFIG, k):
            out[k] = getattr(CONFIG, k)
    return out


@router.post("/api/raw/config")
async def api_raw_config_set(request: Request, force: int = 0):
    """Перезаписать config из JSON-объекта. Принимает все известные ключи
    (включая llm_*). Строгий кастинг типов.
    Защита: если пустой list/string затирает непустой существующий → пропуск
    (если не передан ?force=1). Иначе один случайный «💾 Сохранить» при stale-state
    сносит llm_profiles/letter_templates/cookies."""
    try:
        data = await request.json()
    except Exception:
        return {"ok": False, "error": "Невалидный JSON"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "Ожидается объект"}
    errors = {}
    preserved = []  # ключи которые НЕ перезаписали из-за защиты
    allowed = _all_raw_config_keys()
    for key, value in data.items():
        if key not in allowed:
            errors[key] = "unknown_or_wrong_type"
            continue
        if key in _RAW_LIST_KEYS:
            if not isinstance(value, list):
                errors[key] = "expected list"
                continue
            current = getattr(CONFIG, key, None) or []
            if not force and not value and current:
                preserved.append(key)
                continue
            setattr(CONFIG, key, value)
            continue
        if key in _RAW_LLM_KEYS or key in _RAW_EXTRA_KEYS or key in _CONFIG_KEYS:
            try:
                casted = _safe_cast(key, value)
            except (ValueError, TypeError) as e:
                errors[key] = str(e)
                continue
            current = getattr(CONFIG, key, None)
            # Защита от затирания непустых строк (например llm_api_key, llm_system_prompt)
            if not force and isinstance(casted, str) and not casted and isinstance(current, str) and current:
                preserved.append(key)
                continue
            setattr(CONFIG, key, casted)
    save_config()
    return {"ok": not errors, "errors": errors, "preserved": preserved}


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
            if not new_acc:
                continue
            # In-place mutation (НЕ replace reference): workers держат ссылку на
            # state.acc и stale dict иначе (r13-1 #5). Cookies_lock сохраняем явно.
            # Pop+update должны быть атомарными — иначе reader увидит частично-
            # очищенный dict (например, отсутствие cookies в момент HTTP-запроса).
            # Держим state._state_lock на всю последовательность (kimi-r14-1 #5).
            with state._state_lock:
                cookies_lock = state.acc.get("_cookies_lock")
                keep_keys = set(new_acc.keys()) | {"_cookies_lock"}
                for k in list(state.acc.keys()):
                    if k not in keep_keys:
                        state.acc.pop(k, None)
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


# ============================================================
# BACKUP / RESTORE — единый JSON со всем (включая cookies/API-keys).
# ============================================================

_BACKUP_FILES = ("config.json", "accounts.json", "browser_sessions.json", "oauth_tokens.json")


def _load_json_file(name: str):
    p = Path(DATA_DIR) / name
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log_debug(f"backup: failed to load {name}: {e}")
        return None


@router.get("/api/backup")
async def api_backup_download():
    """Скачать полный бэкап data/ (config + accounts + browser_sessions + oauth_tokens)
    одним JSON-файлом. Содержит cookies/llm_api_key — храни в безопасном месте."""
    bundle = {
        "version": 1,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
    }
    for fname in _BACKUP_FILES:
        bundle[fname] = _load_json_file(fname)
    body = json.dumps(bundle, ensure_ascii=False, indent=2).encode("utf-8")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    headers = {
        "Content-Disposition": f'attachment; filename="hh-backup-{stamp}.json"',
        "Cache-Control": "no-store",
    }
    return Response(content=body, media_type="application/json", headers=headers)


# Поля внутри каждого файла бэкапа, которые НЕЛЬЗЯ затирать пустым list/string
# без явного ?force=1 — если в бэкапе они пустые, а на диске не пустые → пропуск.
# Это защита от случайного «💾 Сохранить» когда редактор показывал stale-state
# (юзер открыл, не дождался автозагрузки, нажал save → потерял llm_profiles).
_PROTECTED_FIELDS = {
    "config.json": {
        "llm_profiles", "letter_templates", "questionnaire_templates",
        "url_pool", "allowed_schedules",
        "llm_api_key", "llm_base_url", "llm_model", "llm_system_prompt",
    },
}


def _merge_preserve(payload, current, protected: set, path: str = "") -> tuple:
    """Если payload[k] — пустой list/string, а current[k] — непустой — оставляем current.
    Возвращает (merged, preserved_keys)."""
    preserved = []
    if not isinstance(payload, dict) or not isinstance(current, dict):
        return payload, preserved
    out = dict(payload)
    for k in protected:
        new_v = payload.get(k)
        old_v = current.get(k)
        if old_v and not new_v and (isinstance(new_v, (list, str)) or new_v is None):
            out[k] = old_v
            preserved.append(f"{path}{k}")
    return out, preserved


@router.post("/api/backup")
async def api_backup_restore(request: Request, force: int = 0):
    """Восстановить из бэкапа. Принимает JSON, сделанный GET /api/backup.
    Перезаписывает ВСЕ data/*.json файлы. Защита: пустые list/string не затирают
    непустые существующие (для llm_profiles, letter_templates и т.д.) если ?force=0."""
    try:
        data = await request.json()
    except Exception:
        return {"ok": False, "error": "Невалидный JSON"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "Ожидается объект"}
    restored = []
    errors = {}
    preserved_all = []
    for fname in _BACKUP_FILES:
        if fname not in data:
            continue
        payload = data[fname]
        if payload is None:
            continue
        # Защита: для известных файлов сохраняем непустые поля если входящие пустые.
        if not force and fname in _PROTECTED_FIELDS:
            current = _load_json_file(fname) or {}
            payload, preserved_keys = _merge_preserve(
                payload, current, _PROTECTED_FIELDS[fname], path=f"{fname}/"
            )
            preserved_all.extend(preserved_keys)
        try:
            p = Path(DATA_DIR) / fname
            tmp = p.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            tmp.replace(p)
            restored.append(fname)
        except Exception as e:
            errors[fname] = str(e)

    # Reload live state from disk so user не должен рестартовать руками.
    try:
        from app.config import load_config as _load_config, load_accounts as _load_accounts
        _load_config()
        _load_accounts()
        from app.instances import bot as _bot
        _bot.temp_sessions[:] = load_browser_sessions()
    except Exception as e:
        log_debug(f"backup restore: live-reload error: {e}")

    return {
        "ok": not errors,
        "restored": restored,
        "preserved": preserved_all,
        "errors": errors,
        "warning": "Аккаунты/cookies применены. Для новых аккаунтов нужен перезапуск бота.",
    }


@router.delete("/api/backup")
async def api_backup_wipe():
    """Полная очистка: удалить все data/*.json (config, accounts, browser_sessions,
    oauth_tokens). После — in-memory state сбрасывается до дефолтов."""
    cleared = []
    errors = {}
    for fname in _BACKUP_FILES:
        p = Path(DATA_DIR) / fname
        try:
            if p.exists():
                p.unlink()
                cleared.append(fname)
        except Exception as e:
            errors[fname] = str(e)
    # Сброс in-memory state.
    try:
        from app.config import load_config as _load_config, load_accounts as _load_accounts
        from app.instances import bot as _bot
        accounts_data.clear()
        _bot.temp_sessions.clear()
        # Не вызываем _load_*  — файлов уже нет; CONFIG останется в текущем виде
        # но без диска (а save_config создаст новый чистый файл на следующем save).
    except Exception as e:
        log_debug(f"backup wipe: in-memory clear error: {e}")
    return {
        "ok": not errors,
        "cleared": cleared,
        "errors": errors,
        "warning": "In-memory очищено. Перезапуск бота не требуется.",
    }
