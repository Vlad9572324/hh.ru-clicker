"""
Per-account mode selector (feat7): "auto" | "web" | "mobile".

Mode сохраняется в accounts.json (поле "mode" — optional, см. app.config)
и определяет какой HH-клиент использует аккаунт (app.hh_client_factory):
  - "auto"   → Phase 0: бот сам выбирает (сейчас всегда WebHHClient)
  - "web"    → WebHHClient (cookies hh.ru)
  - "mobile" → MobileHHClient (OAuth api.hh.ru, Android-приложение)

Диапазон idx: только основные аккаунты — 0 <= idx < len(bot.account_states)
(они же accounts_data[idx]; AccountState.acc — тот же dict, что accounts_data[idx],
см. app.manager.load_accounts → AccountState(acc_data)). Браузерные temp-сессии
(idx >= len(account_states)) вне контракта этого endpoint'а — 404.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.config as config
from app.hh_client_factory import _normalize_mode, _MODE_MISSING
from app.instances import bot
from app.logging_utils import log_debug


router = APIRouter()

_ALLOWED_MODES = ["auto", "web", "mobile"]


def _effective_client(mode_norm: str) -> str:
    """Какой клиент реально выберет factory для нормализованного mode."""
    return "MobileHHClient" if _normalize_mode(mode_norm) == "mobile" else "WebHHClient"


def _resolve_acc(idx: int):
    """Dict аккаунта для idx или None (idx вне диапазона основных аккаунтов)."""
    if not isinstance(idx, int) or idx < 0:
        return None
    if idx >= len(bot.account_states):
        return None
    accounts = config.accounts_data
    if idx >= len(accounts):
        return None
    acc = accounts[idx]
    return acc if isinstance(acc, dict) else None


@router.get("/api/account/{idx}/mode")
async def api_account_mode_get(idx: int):
    """Текущий mode аккаунта (для инициализации dropdown в UI)."""
    acc = _resolve_acc(idx)
    if acc is None:
        return JSONResponse({"ok": False, "error": "invalid_idx"}, status_code=404)
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
    acc = _resolve_acc(idx)
    if acc is None:
        return JSONResponse({"ok": False, "error": "invalid_idx"}, status_code=404)

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
    # Defensive: bot.account_states[idx].acc обычно IS accounts_data[idx]
    # (manager.load_accounts), но если когда-нибудь разойдутся — пишем в оба.
    state = bot.account_states[idx]
    state_acc = getattr(state, "acc", None)
    if isinstance(state_acc, dict) and state_acc is not acc:
        state_acc["mode"] = norm

    config.save_accounts()
    log_debug(f"account_mode: idx={idx} mode={norm}")
    return {
        "ok": True,
        "mode": norm,
        "effective_client": _effective_client(norm),
    }
