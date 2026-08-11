"""
Per-account mode selector (feat7): "auto" | "web" | "mobile".

Mode сохраняется в accounts.json либо browser_sessions.json (поле "mode")
и определяет какой HH-клиент использует аккаунт (app.hh_client_factory):
  - "auto"   → Phase 0: бот сам выбирает (сейчас всегда WebHHClient)
  - "web"    → WebHHClient (cookies hh.ru)
  - "mobile" → MobileHHClient (OAuth api.hh.ru, Android-приложение)

idx использует общий диапазон snapshot: сначала основные аккаунты, затем
браузерные temp-сессии.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.config as config
from app.hh_client_factory import _normalize_mode, _MODE_MISSING
from app.instances import bot
from app.logging_utils import log_debug
from app.storage import save_browser_sessions


router = APIRouter()

_ALLOWED_MODES = ["auto", "web", "mobile"]


def _effective_client(mode_norm: str) -> str:
    """Какой клиент реально выберет factory для нормализованного mode."""
    return "MobileHHClient" if _normalize_mode(mode_norm) == "mobile" else "WebHHClient"


def _resolve_acc(idx: int):
    """Вернуть (dict, kind, local_idx) для глобального snapshot-индекса."""
    if not isinstance(idx, int) or idx < 0:
        return None
    main_count = len(bot.account_states)
    if idx < main_count:
        accounts = config.accounts_data
        if idx >= len(accounts) or not isinstance(accounts[idx], dict):
            return None
        return accounts[idx], "account", idx
    temp_idx = idx - main_count
    sessions = bot.temp_sessions
    if temp_idx < 0 or temp_idx >= len(sessions) or not isinstance(sessions[temp_idx], dict):
        return None
    return sessions[temp_idx], "session", temp_idx


@router.get("/api/account/{idx}/mode")
async def api_account_mode_get(idx: int):
    """Текущий mode аккаунта (для инициализации dropdown в UI)."""
    resolved = _resolve_acc(idx)
    if resolved is None:
        return JSONResponse({"ok": False, "error": "invalid_idx"}, status_code=404)
    acc, _, _ = resolved
    # Поля "mode" может не быть — тогда нормализуется дефолт
    # CONFIG.default_client_mode (см. _normalize_mode / _MODE_MISSING).
    mode_norm = _normalize_mode(acc.get("mode", _MODE_MISSING))
    return {
        "ok": True,
        "mode": mode_norm,
        "effective_client": _effective_client(mode_norm),
    }


@router.put("/api/account/{idx}/mode")
async def api_account_mode_put(idx: int, request: Request):
    """Сменить mode аккаунта: body {"mode": "auto"|"web"|"mobile"}."""
    resolved = _resolve_acc(idx)
    if resolved is None:
        return JSONResponse({"ok": False, "error": "invalid_idx"}, status_code=404)
    acc, kind, local_idx = resolved

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
    if not isinstance(body, dict):
        body = {}

    raw_mode = body.get("mode")
    norm = raw_mode.strip().lower() if isinstance(raw_mode, str) else None
    if norm not in _ALLOWED_MODES:
        return JSONResponse(
            {"ok": False, "error": "invalid_mode", "allowed": list(_ALLOWED_MODES)},
            status_code=400,
        )

    acc["mode"] = norm
    state = (
        bot.account_states[local_idx]
        if kind == "account"
        else bot.temp_states.get(local_idx)
    )
    state_acc = getattr(state, "acc", None)
    if isinstance(state_acc, dict) and state_acc is not acc:
        state_acc["mode"] = norm

    if kind == "account":
        config.save_accounts()
    else:
        save_browser_sessions(bot.temp_sessions)
    log_debug(f"account_mode: idx={idx} kind={kind} mode={norm}")
    return {
        "ok": True,
        "mode": norm,
        "effective_client": _effective_client(norm),
    }
