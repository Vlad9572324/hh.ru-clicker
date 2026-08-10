"""
Autologin bridge: mobile OAuth-токен → одноразовый URL web-сессии hh.ru.

POST /api/account/{idx}/autologin_url
  1. OAuth-токен аккаунта (нет токена → 400 no_oauth_token)
  2. GET https://api.hh.ru/me → hhid (кэш 30 минут per-аккаунт)
  3. GET https://api.hh.ru/autologin_key/<hhid> → одноразовый ключ
  4. Ответ: {"ok": true, "url": "https://hh.ru/?loginkey=<KEY>", ...}

ВАЖНО: бот НЕ ходит по loginkey-URL сам — URL отдаётся пользователю
(открыть в браузере / скопировать). Ключ ОДНОРАЗОВЫЙ: сам URL не кэшируется,
повторный запрос получает новый ключ. Значение ключа не попадает в логи.
"""

import asyncio
import time

import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.instances import bot
from app.logging_utils import log_debug
from app.oauth import _obtain_oauth_token


router = APIRouter()

_HH_API = "https://api.hh.ru"
_LOGIN_URL_TMPL = "https://hh.ru/?loginkey={key}"
_HH_HEADERS_BASE = {
    "User-Agent": "ru.hh.android/26.28.1",
    "x-force-app-access": "true",
    "Accept": "application/json",
}
_TIMEOUT = 15
_HHID_TTL = 30 * 60  # 30 минут

# Кэш hhid per-аккаунт: resume_hash → (hhid, monotonic deadline).
# Сам loginkey НЕ кэшируется — ключ одноразовый.
_hhid_cache: dict = {}


def _extract_loginkey(payload):
    """Достаёт ключ из произвольного JSON-ответа (как в прототипе):
    известные ключи dict, вложенный data, единственный строковой value,
    либо просто строка."""
    if isinstance(payload, str):
        return payload.strip() or None
    if isinstance(payload, dict):
        for k in ("key", "autologin_key", "loginkey", "login_key", "autologinKey"):
            if k in payload and isinstance(payload[k], str):
                return payload[k]
        if "data" in payload and isinstance(payload["data"], (str, dict)):
            return _extract_loginkey(payload["data"])
        # dict с единственным строковым значением — берём его
        str_vals = [v for v in payload.values() if isinstance(v, str)]
        if len(str_vals) == 1:
            return str_vals[0]
    return None


def _auth_headers(token: str) -> dict:
    return {**_HH_HEADERS_BASE, "Authorization": f"Bearer {token}"}


def _fetch_hhid(token: str, cache_key: str):
    """GET /me → hhid (кэш 30 минут). Возвращает (hhid|None, error|None)."""
    now = time.monotonic()
    cached = _hhid_cache.get(cache_key)
    if cached and cached[1] > now:
        return cached[0], None
    try:
        r = requests.get(f"{_HH_API}/me", headers=_auth_headers(token), timeout=_TIMEOUT)
    except requests.RequestException as e:
        log_debug(f"autologin: /me request error: {type(e).__name__}")
        return None, "me_request_failed"
    if r.status_code != 200:
        # Логируем только статус — без тела (в теле могут быть персональные данные).
        log_debug(f"autologin: /me HTTP {r.status_code}")
        return None, "me_failed"
    try:
        hhid = str(r.json()["id"])
    except Exception:
        log_debug("autologin: /me — нет id в ответе")
        return None, "me_no_id"
    if not hhid:
        return None, "me_no_id"
    _hhid_cache[cache_key] = (hhid, now + _HHID_TTL)
    return hhid, None


def _fetch_autologin_key(token: str, hhid: str):
    """GET /autologin_key/<hhid> → одноразовый ключ.
    Возвращает (key|None, error|None)."""
    url = f"{_HH_API}/autologin_key/{hhid}"
    try:
        r = requests.get(url, headers=_auth_headers(token), timeout=_TIMEOUT)
    except requests.RequestException as e:
        log_debug(f"autologin: autologin_key request error: {type(e).__name__}")
        return None, "autologin_request_failed"
    # В лог только статус — значение ключа логировать нельзя (одноразовый секрет).
    log_debug(f"autologin: autologin_key HTTP {r.status_code}")
    if r.status_code != 200:
        return None, "autologin_failed"
    try:
        payload = r.json()
    except ValueError:
        payload = None
    key = _extract_loginkey(payload) if payload is not None else (r.text.strip() or None)
    if not key:
        return None, "no_key_in_response"
    return key, None


def _build_autologin_url(acc: dict):
    """Синхронная часть (выполняется в executor): token → hhid → key → url.
    Возвращает (url|None, error|None)."""
    token = _obtain_oauth_token(acc)
    if not token:
        return None, "no_oauth_token"
    cache_key = acc.get("resume_hash") or str(id(acc))
    hhid, err = _fetch_hhid(token, cache_key)
    if err:
        return None, err
    key, err = _fetch_autologin_key(token, hhid)
    if err:
        return None, err
    # Безопасность: URL возвращается только целиком; отдельно ключ не отдаём.
    return _LOGIN_URL_TMPL.format(key=key), None


@router.post("/api/account/{idx}/autologin_url")
async def api_autologin_url(idx: int):
    """Одноразовый URL для входа в web-версию hh.ru без пароля (autologin bridge)."""
    if idx < 0 or idx >= len(bot.account_states):
        return JSONResponse({"ok": False, "error": "invalid_idx"}, status_code=404)
    acc = bot.account_states[idx].acc
    loop = asyncio.get_event_loop()
    try:
        url, err = await loop.run_in_executor(None, _build_autologin_url, acc)
    except Exception as e:
        log_debug(f"autologin: unexpected error: {type(e).__name__}")
        return JSONResponse({"ok": False, "error": "internal_error"}, status_code=502)
    if err == "no_oauth_token":
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=502)
    return {"ok": True, "url": url, "note": "одноразовый ключ"}
