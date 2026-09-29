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


def _quiesce_runtime(bot) -> None:
    """Остановить account/temp workers без глобального stop_event manager-а."""
    states = list(bot.account_states) + list(bot.temp_states.values())
    for state in states:
        state._deleted = True
        state.paused = True
        ws = getattr(state, "_ws_client", None)
        if ws:
            try:
                ws.stop()
            except Exception:
                pass
    for state in states:
        for worker in getattr(state, "_workers", []):
            try:
                worker.join(timeout=5)
            except Exception:
                pass
    bot.account_states.clear()
    bot.temp_states.clear()


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
    # Validate the whole replacement before touching either persistent or live
    # accounts. Silently skipping malformed entries used to delete accounts.
    names = []
    for acc in data:
        if not isinstance(acc, dict):
            return {"ok": False, "error": "Каждый аккаунт должен быть объектом. Изменения не сохранены."}
        name = acc.get("name")
        if not isinstance(name, str) or not name.strip():
            return {"ok": False, "error": "У каждого аккаунта должно быть непустое имя."}
        if not isinstance(acc.get("cookies", {}), dict):
            return {"ok": False, "error": "Cookies должны быть объектом. Изменения не сохранены."}
        if any(not isinstance(value, str) for value in acc.get("cookies", {}).values()):
            return {"ok": False, "error": "Значения cookies должны быть строками."}
        names.append(name)
    if len(set(names)) != len(names):
        return {"ok": False, "error": "Имена аккаунтов должны быть уникальными. Изменения не сохранены."}
    from app.instances import bot as _bot
    old_by_name = {a.get("name", ""): a for a in accounts_data}
    live_by_name = {state.name: state for state in _bot.account_states}
    if any(name not in old_by_name or name not in live_by_name for name in names):
        return {"ok": False, "error": "Через JSON можно изменить, удалить или переставить существующие аккаунты. "
                "Для добавления или переименования используйте карточку аккаунта. Изменения не сохранены."}
    if len(old_by_name) != len(accounts_data) or len(live_by_name) != len(_bot.account_states):
        return {"ok": False, "error": "Обнаружены повторяющиеся имена аккаунтов. Сначала исправьте их в карточках."}
    merged = []
    for acc in data:
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
        retained_states = {}
        for state in _bot.account_states:
            new_acc = by_name.get(state.name)
            if not new_acc:
                state._deleted = True
                state.paused = True
                ws = getattr(state, "_ws_client", None)
                if ws:
                    try:
                        ws.stop()
                    except Exception:
                        pass
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
            retained_states[state.name] = state
        _bot.account_states[:] = [retained_states[a.get("name", "")] for a in merged
                                 if a.get("name", "") in retained_states]
    except Exception as e:
        log_debug(f"api_raw_accounts_set live-sync error: {e}")
    return {
        "ok": True,
        "count": len(merged),
        "warning": "Изменения и удаления применены. Новые аккаунты добавляются через карточку аккаунта.",
    }


# ============================================================
# BACKUP / RESTORE — единый JSON со всем (включая cookies/API-keys).
# Доступ ВСЕГДА требует API-key — проверка в middleware (app/routes/__init__.py,
# _ALWAYS_AUTH_PREFIXES), даже при пустом HH_BOT_API_KEY.
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


def _backup_payload_error(name, payload):
    """Validate file shapes without mutating live config or quiescing workers."""
    if name in ("accounts.json", "browser_sessions.json"):
        if not isinstance(payload, list) or any(not isinstance(acc, dict) for acc in payload):
            return "Ожидается массив объектов аккаунтов"
        for acc in payload:
            if not isinstance(acc.get("cookies", {}), dict):
                return "Cookies должны быть объектом"
            if any(not isinstance(v, str) for v in acc.get("cookies", {}).values()):
                return "Значения cookies должны быть строками"
            for field in ("name", "short", "color", "resume_hash", "letter"):
                if field in acc and not isinstance(acc[field], str):
                    return f"Поле {field} должно быть строкой"
            if "urls" in acc and (not isinstance(acc["urls"], list)
                                  or any(not isinstance(url, str) for url in acc["urls"])):
                return "Поле urls должно быть массивом строк"
    elif name == "config.json":
        if not isinstance(payload, dict):
            return "Ожидается объект настроек"
        for key, value in payload.items():
            if key in _RAW_LIST_KEYS and not isinstance(value, list):
                return f"Поле {key} должно быть массивом"
            if key == "mobile_auth" and not isinstance(value, dict):
                return "Поле mobile_auth должно быть объектом"
            if key in _RAW_LLM_KEYS | _RAW_EXTRA_KEYS | set(_CONFIG_KEYS):
                try:
                    _safe_cast(key, value)
                except (ValueError, TypeError, OverflowError):
                    return f"Неверный тип настройки {key}"
    elif name == "oauth_tokens.json":
        if not isinstance(payload, dict) or any(not isinstance(token, dict) for token in payload.values()):
            return "Ожидается объект записей OAuth"
        for token in payload.values():
            if any(field in token and not isinstance(token[field], str)
                   for field in ("access_token", "refresh_token")):
                return "Токены OAuth должны быть строками"
    return ""


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
    payloads = {name: data[name] for name in _BACKUP_FILES
                if name in data and data[name] is not None}
    if not payloads:
        return {"ok": False, "error": "В файле нет данных бэкапа для восстановления. Аккаунты не изменены."}
    invalid = {name: error for name, payload in payloads.items()
               if (error := _backup_payload_error(name, payload))}
    if invalid:
        return {"ok": False, "error": "Бэкап повреждён или имеет неверный формат. Изменения не применены.",
                "errors": invalid, "restored": []}
    restored = []
    errors = {}
    preserved_all = []
    from app.instances import bot as _bot
    _quiesce_runtime(_bot)
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
            # Аудит 2026-08-17 #9: раньше restore писал через фиксированный
            # `<name>.tmp` — тот же путь, что и обычные save_* writers → гонка
            # unlink/replace могла удалить чужой tmp или откатить только что
            # сохранённые изменения. Используем _atomic_write_json (fsync +
            # tmp.replace) для durability и не пересекаемся с writers по имени.
            from app.storage import _atomic_write_json as _atomic_write
            p = Path(DATA_DIR) / fname
            _atomic_write(p, payload)
            restored.append(fname)
        except Exception as e:
            errors[fname] = str(e)

    # Reload live state from disk so user не должен рестартовать руками.
    try:
        from app.config import load_config as _load_config, load_accounts as _load_accounts
        _load_config()
        _load_accounts()
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
    from app.instances import bot as _bot
    _quiesce_runtime(_bot)
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
        from app.config import CONFIG as _CONFIG, Config as _ConfigCls, save_config as _save_config
        accounts_data.clear()
        _bot.temp_sessions.clear()
        save_browser_sessions([], wait=True)
        # Аудит 2026-08-17 #32: раньше файл удаляли, но CONFIG в памяти жил
        # → первый же save_config() возвращал llm_api_key/llm_profiles на диск.
        # Заменяем sensitive-поля CONFIG на дефолтные (из свежего Config()) и
        # атомарно сохраняем очищенное состояние, чтобы утечка была невозможна.
        _defaults = _ConfigCls()
        _SENSITIVE = (
            "llm_api_key", "llm_base_url", "llm_model", "llm_profiles",
            "llm_system_prompt", "hh_proxy_url",
        )
        for _f in _SENSITIVE:
            if hasattr(_defaults, _f):
                setattr(_CONFIG, _f, getattr(_defaults, _f))
        _CONFIG.llm_enabled = False
        _CONFIG.llm_auto_send = False
        _save_config()  # запишем чистый файл
    except Exception as e:
        log_debug(f"backup wipe: in-memory clear error: {e}")
    return {
        "ok": not errors,
        "cleared": cleared,
        "errors": errors,
        "warning": "In-memory очищено. Перезапуск бота не требуется.",
    }
