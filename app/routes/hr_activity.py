"""
HR-activity badge для вакансий (feat1: ranking по активности HR).

GET /api/vacancy/{id}/hr_activity → данные из мобильного API HH
GET https://api.hh.ru/vacancies/{id}/employer_stats:
  - manager_inactive_minutes      — минут с последней активности HR
  - employer_responses_read_percent — % прочитанных откликов

Порог «живой HR»: inactive < 60 минут.

Конвенции репо:
  - ошибки: JSONResponse({"ok": False, "error": ...}, status_code=...)
  - токен: app.oauth._obtain_oauth_token(acc), нет токена → 400 no_oauth_token
  - HTTP к HH: только requests.get (тесты мокают через responses)
  - блокирующие вызовы через run_in_executor

Результат кэшируется per-vacancy на 10 минут (module-level dict +
time.monotonic), чтобы рендер списка вакансий не долбил HH.
"""

import asyncio
import re
import time

import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.hh_http import egress_proxies
from app.instances import bot
from app.oauth import _obtain_oauth_token

router = APIRouter()

LIVE_HR_THRESHOLD_MIN = 60   # минут — граница «живой HR» (из прототипа)
CACHE_TTL_SEC = 600          # 10 минут кэша per-vacancy
HH_TIMEOUT_SEC = 15

# vid -> (expires_monotonic, payload_dict)
_cache: dict = {}


def _err(status_code: int, error: str) -> JSONResponse:
    """Единый формат ошибок: {"ok": False, "error": ...} + HTTP-статус."""
    return JSONResponse({"ok": False, "error": error}, status_code=status_code)


def _to_int_or_none(v):
    """Мягкий каст значения HH к int|None (HH иногда отдаёт строки/floats)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        try:
            return int(v.strip())
        except ValueError:
            return None
    return None


def _fetch_employer_stats(token: str, vid: str):
    """Блокирующий GET к HH. Возвращает (stats_dict, None) или (None, error_str)."""
    url = f"https://api.hh.ru/vacancies/{vid}/employer_stats"
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "ru.hh.android/26.28.1",
        "x-force-app-access": "true",
    }
    try:
        r = requests.get(url, headers=headers, timeout=HH_TIMEOUT_SEC,
                         proxies=egress_proxies())
    except requests.RequestException as e:
        return None, f"network: {e}"
    if r.status_code != 200:
        return None, f"hh_http_{r.status_code}"
    try:
        data = r.json()
    except ValueError:
        return None, "bad_json"
    if not isinstance(data, dict):
        return None, "bad_json"
    return data, None


@router.get("/api/vacancy/{id}/hr_activity")
async def api_vacancy_hr_activity(id: str, account_idx: int = 0):
    """HR-активность по вакансии: live (🟢) / pipeline (🔴) / unknown (❔)."""
    # vid — только цифры: защищаем конструирование URL от path-injection.
    if not re.fullmatch(r"\d+", id or ""):
        return _err(404, "invalid_vacancy_id")
    idx_arg = account_idx

    acc = bot._get_apply_acc(idx_arg)

    if acc is None:


        return JSONResponse({"ok": False, "error": "account not found"}, status_code=404)

    # Кэш-хит — без OAuth и без HTTP к HH.
    now = time.monotonic()
    cached = _cache.get(id)
    if cached is not None and cached[0] > now:
        return cached[1]

    loop = asyncio.get_event_loop()
    token = await loop.run_in_executor(None, _obtain_oauth_token, acc)
    if not token:
        return _err(400, "no_oauth_token")

    stats, err = await loop.run_in_executor(None, _fetch_employer_stats, token, id)
    if err is not None:
        return _err(502, err)

    inactive = _to_int_or_none(stats.get("manager_inactive_minutes"))
    read_pct = _to_int_or_none(stats.get("employer_responses_read_percent"))
    live = inactive is not None and inactive < LIVE_HR_THRESHOLD_MIN
    if inactive is None:
        badge = "unknown"
    else:
        badge = "live" if live else "pipeline"

    payload = {
        "ok": True,
        "vacancy_id": id,
        "manager_inactive_minutes": inactive,
        "employer_responses_read_percent": read_pct,
        "live": live,
        "badge": badge,
    }
    _cache[id] = (time.monotonic() + CACHE_TTL_SEC, payload)
    return payload
