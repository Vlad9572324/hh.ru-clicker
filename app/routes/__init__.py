"""
FastAPI app creation and route registration.
"""

import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# Singleton bot/manager are created in app.instances so every router module
# can import them without pulling in the package __init__ (avoids circular imports).
from app.instances import bot, manager  # re-exported for back-compat
from app.logging_utils import log_debug

app = FastAPI(title="HH Bot Dashboard")

STATIC_DIR = Path("static")
STATIC_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── API key middleware ──────────────────────────────────────────────────────
# Закрывает все "attacker reaches localhost" сценарии: token exfil через
# /api/account/{idx}/oauth_token, config poison через /api/raw/config, DoS
# через /api/llm_run_now и т.д. Один middleware вместо отдельных проверок.
#
# Активируется если установлен `HH_BOT_API_KEY` env. Без env — пропускает всё
# (backward compat для локального dev на 127.0.0.1).
_API_KEY = os.environ.get("HH_BOT_API_KEY", "").strip()
_PUBLIC_PATHS = ("/", "/static/", "/favicon.ico")  # GET-only публичные пути


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    # Если ключ не задан — auth выключен (опасно, но не ломает существующие deployments).
    if not _API_KEY:
        return await call_next(request)
    path = request.url.path
    if request.method == "GET" and any(path == p or path.startswith(p) for p in _PUBLIC_PATHS):
        return await call_next(request)
    # WS upgrade проверяется в websocket_endpoint отдельно (не идёт через middleware).
    presented = request.headers.get("X-API-Key", "") or request.query_params.get("api_key", "")
    if not presented or not secrets.compare_digest(presented, _API_KEY):
        log_debug(f"auth_denied path={path} method={request.method} ip={request.client.host if request.client else '?'}")
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
    return await call_next(request)


def api_key_required() -> str:
    """Helper для WS handshake: вернуть текущий API key (или '' если выключено)."""
    return _API_KEY

# -- Register routers (imported after app is created) --
from app.routes.core import router as core_router          # noqa: E402
from app.routes.accounts import router as accounts_router  # noqa: E402
from app.routes.sessions import router as sessions_router  # noqa: E402
from app.routes.data import router as data_router          # noqa: E402
from app.routes.apply import router as apply_router        # noqa: E402
from app.routes.settings import router as settings_router  # noqa: E402
from app.routes.llm import router as llm_router            # noqa: E402
from app.routes.debug import router as debug_router        # noqa: E402

app.include_router(core_router)
app.include_router(accounts_router)
app.include_router(sessions_router)
app.include_router(data_router)
app.include_router(apply_router)
app.include_router(settings_router)
app.include_router(llm_router)
app.include_router(debug_router)
