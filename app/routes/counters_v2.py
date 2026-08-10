"""
feat4: extended user counters для header-dashboard.

GET /api/account/{idx}/counters_v2
    1. GET https://api.hh.ru/me                    → uuid = data["id"]
       (кэш uuid per-аккаунт на 60 минут, module-level dict)
    2. GET https://api.hh.ru/counters/user?uuid=<uuid>

Успех:
    {"ok": true, "user_id": "...", "counters": {
        "unread_chats": int|null, "unread_negotiations": int|null,
        "new_resume_views": int|null, "new_notifications": int|null,
        "resumes_count": int|null, "rejected_employer_reviews": int|null}}

Ошибки (единый формат {"ok": false, "error": ...}):
    404 invalid_idx — аккаунт не найден
    400 no_oauth_token — нет OAuth-токена
    502 me_http_<code> / counters_http_<code> — HH ответил не 200
    502 me_http_0 / counters_http_0 — сетевая ошибка
"""

import asyncio
import time

import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.hh_http import egress_proxies
from app.instances import bot
from app.logging_utils import log_debug
from app.oauth import _obtain_oauth_token


router = APIRouter()

_HH_API = "https://api.hh.ru"
_UA = "ru.hh.android/26.28.1"
_UUID_TTL_SECONDS = 60 * 60  # кэш uuid — 60 минут

# Ключи counters/user, которые отдаём фронту. Отсутствующие/не-числовые → null.
_COUNTER_KEYS = (
    "unread_chats",
    "unread_negotiations",
    "new_resume_views",
    "new_notifications",
    "resumes_count",
    "rejected_employer_reviews",
)

# Кэш uuid per-аккаунт: key → (uuid, expires_at_monotonic).
# Ключ — resume_hash (стабильный идентификатор аккаунта, переживает idx-сдвиги).
_uuid_cache: dict = {}


def _err(status_code: int, error: str) -> JSONResponse:
    """Единый формат ошибок: {"ok": False, "error": ...} + HTTP-статус."""
    return JSONResponse({"ok": False, "error": error}, status_code=status_code)


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": _UA,
        "x-force-app-access": "true",
    }


def _cache_key(idx: int, acc: dict) -> str:
    return acc.get("resume_hash") or f"idx:{idx}"


def _get_cached_uuid(key: str):
    entry = _uuid_cache.get(key)
    if not entry:
        return None
    uuid, expires_at = entry
    if time.monotonic() >= expires_at:
        _uuid_cache.pop(key, None)
        return None
    return uuid


def _fetch_counters_v2(idx: int, acc: dict, token: str) -> dict:
    """Синхронная часть (зовётся через run_in_executor): /me → uuid → counters/user."""
    headers = _headers(token)
    key = _cache_key(idx, acc)

    uuid = _get_cached_uuid(key)
    if uuid is None:
        try:
            r = requests.get(f"{_HH_API}/me", headers=headers, timeout=15,
                             proxies=egress_proxies())
        except requests.RequestException as e:
            log_debug(f"counters_v2: /me request error: {e}")
            return {"error": "me_http_0"}
        if r.status_code != 200:
            return {"error": f"me_http_{r.status_code}"}
        try:
            data = r.json()
        except ValueError:
            return {"error": "me_http_bad_json"}
        uuid = str(data.get("id", "")) if isinstance(data, dict) else ""
        if not uuid:
            return {"error": "me_http_no_id"}
        _uuid_cache[key] = (uuid, time.monotonic() + _UUID_TTL_SECONDS)

    try:
        r = requests.get(
            f"{_HH_API}/counters/user",
            params={"uuid": uuid},
            headers=headers,
            timeout=15,
            proxies=egress_proxies(),
        )
    except requests.RequestException as e:
        log_debug(f"counters_v2: /counters/user request error: {e}")
        return {"error": "counters_http_0"}
    if r.status_code != 200:
        return {"error": f"counters_http_{r.status_code}"}
    try:
        data = r.json()
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}

    counters = {}
    for k in _COUNTER_KEYS:
        v = data.get(k)
        # bool — subclass of int, но counters всегда числовые; guard на всякий случай.
        counters[k] = v if isinstance(v, int) and not isinstance(v, bool) else None

    return {"ok": True, "user_id": uuid, "counters": counters}


@router.get("/api/account/{idx}/counters_v2")
async def api_account_counters_v2(idx: int):
    """Extended counters аккаунта для header-dashboard (💬/📮/👁️/🔔)."""
    idx_arg = idx

    acc = bot._get_apply_acc(idx_arg)

    if acc is None:


        return JSONResponse({"ok": False, "error": "account not found"}, status_code=404)

    loop = asyncio.get_event_loop()
    token = await loop.run_in_executor(None, _obtain_oauth_token, acc)
    if not token:
        return _err(400, "no_oauth_token")

    result = await loop.run_in_executor(None, _fetch_counters_v2, idx, acc, token)
    if "error" in result:
        return _err(502, result["error"])
    return result
