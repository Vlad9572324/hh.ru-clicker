"""
Core routes: startup, index, websocket, global pause, broadcast loop.
"""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app.logging_utils import log_debug
from app.config import CONFIG, _CONFIG_KEYS, save_config, _url_entry
from app.instances import bot, manager


router = APIRouter()


# ============================================================
# STARTUP
# ============================================================

@router.on_event("startup")
async def startup():
    from app.config import load_accounts
    load_accounts()
    bot.start()
    asyncio.create_task(broadcast_loop())


# ============================================================
# INDEX
# ============================================================

@router.get("/")
async def index():
    return FileResponse("static/index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


# ============================================================
# WEBSOCKET
# ============================================================

_DEFAULT_WS_ORIGIN_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "[::1]", "::1"}


def _allowed_ws_hosts() -> set:
    """Loopback + кастомные хосты из HH_BOT_ALLOWED_ORIGINS (через запятую).
    Нужно для случаев `HH_BOT_HOST=0.0.0.0` + доступ с LAN 192.168.x.x или dev-hostname.
    """
    import os
    extra = os.environ.get("HH_BOT_ALLOWED_ORIGINS", "")
    extra_hosts = {h.strip().lower() for h in extra.split(",") if h.strip()}
    return _DEFAULT_WS_ORIGIN_HOSTS | extra_hosts


def _ws_origin_allowed(origin: str) -> bool:
    """CSWSH-защита: bind 127.0.0.1 не спасает от того, что произвольный сайт
    из браузера откроет ws://localhost:8000/ws. Проверяем Origin вручную.
    Если bind на 0.0.0.0 — добавить хосты через env HH_BOT_ALLOWED_ORIGINS."""
    if not origin:
        # WS-клиент без Origin (curl, скрипт) — пускаем; браузер всегда выставит.
        return True
    from urllib.parse import urlparse
    try:
        host = urlparse(origin).hostname or ""
    except Exception:
        return False
    return host.lower() in _allowed_ws_hosts()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    origin = ws.headers.get("origin", "")
    if not _ws_origin_allowed(origin):
        await ws.close(code=4403)  # policy violation
        log_debug(f"WS: rejected origin {origin!r}")
        return
    # API-key check (если HH_BOT_API_KEY задан) — closes /api/llm_run_now,
    # set_config, account_pause WS spam from a local attacker.
    # Constant-time compare против timing-side-channel (r12-1 #8).
    import os
    import secrets as _secrets
    _api_key = os.environ.get("HH_BOT_API_KEY", "").strip()
    if _api_key:
        presented = ws.headers.get("x-api-key", "") or ws.query_params.get("api_key", "") or ""
        if not presented or not _secrets.compare_digest(str(presented), str(_api_key)):
            await ws.close(code=4401)  # auth required
            log_debug("WS: rejected — missing/wrong api key")
            return
    await manager.connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            cmd = data.get("type", "")

            if cmd == "pause_toggle":
                bot.toggle_pause()
            elif cmd == "account_pause":
                try:
                    idx = int(data.get("idx", -1))
                except (ValueError, TypeError):
                    continue
                bot.toggle_account_pause(idx)
            elif cmd == "account_llm":
                try:
                    idx = int(data.get("idx", -1))
                except (ValueError, TypeError):
                    continue
                bot.toggle_account_llm(idx)
            elif cmd == "account_oauth":
                try:
                    idx = int(data.get("idx", -1))
                except (ValueError, TypeError):
                    continue
                bot.toggle_account_oauth(idx)
            elif cmd == "set_config":
                key = data.get("key")
                value = data.get("value")
                if key == "allowed_schedules" and isinstance(value, list):
                    CONFIG.allowed_schedules = [s for s in value if isinstance(s, str)]
                    save_config()
                    bot._add_log("", "", f"⚙️ Формат работы: {CONFIG.allowed_schedules or 'все'}", "info")
                elif key == "auto_apply_tests":
                    CONFIG.auto_apply_tests = bool(value)
                    save_config()
                    bot._add_log("", "", f"⚙️ Авто-тесты: {'ВКЛ' if CONFIG.auto_apply_tests else 'ВЫКЛ'}", "info")
                elif key and key in _CONFIG_KEYS:
                    from app.routes.settings import _safe_cast
                    try:
                        setattr(CONFIG, key, _safe_cast(key, value))
                        save_config()
                        bot._add_log("", "", f"⚙️ {key} = {value}", "info")
                    except (ValueError, TypeError) as e:
                        log_debug(f"set_config {key} type error: {e}")
            elif cmd == "set_questionnaire":
                templates = data.get("templates")
                default = data.get("default_answer")
                if isinstance(templates, list):
                    CONFIG.questionnaire_templates = templates
                if isinstance(default, str):
                    CONFIG.questionnaire_default_answer = default
                save_config()
                bot._add_log("", "", f"\U0001f4dd Шаблоны опроса обновлены ({len(CONFIG.questionnaire_templates)} шт.)", "info")
            elif cmd == "set_letter_templates":
                templates = data.get("templates")
                if isinstance(templates, list):
                    CONFIG.letter_templates = templates
                    save_config()
                    bot._add_log("", "", f"✉️ Шаблоны писем обновлены ({len(templates)} шт.)", "info")
            elif cmd == "set_url_pool":
                pool = data.get("urls")
                if isinstance(pool, list):
                    normalized = []
                    for u in pool:
                        entry = _url_entry(u)
                        if entry["url"]:
                            normalized.append(entry)
                    CONFIG.url_pool = normalized
                    save_config()
                    bot._add_log("", "", f"\U0001f517 Пул URL обновлён ({len(CONFIG.url_pool)} шт.)", "info")
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


# ============================================================
# GLOBAL PAUSE
# ============================================================

@router.post("/api/pause")
async def api_pause():
    bot.toggle_pause()
    return {"paused": bot.paused}


# ============================================================
# BROADCAST LOOP
# ============================================================

async def broadcast_loop():
    while True:
        try:
            if manager.active:
                snapshot = bot.get_state_snapshot()
                await manager.broadcast(snapshot)
        except Exception as e:
            log_debug(f"broadcast_loop error: {e}")
        await asyncio.sleep(0.3)
