"""
Possible job offers panel (HH рекомендации).

GET /api/account/{idx}/hh_recommendations
    → GET https://api.hh.ru/vacancies/possible_job_offers (OAuth Bearer)

Возвращает список вакансий, которые сам HH подобрал под резюме аккаунта.
Read-only: один GET на публичное API, никаких побочных эффектов.
"""

import asyncio

import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.instances import bot
from app.oauth import _obtain_oauth_token

router = APIRouter()

HH_OFFERS_URL = "https://api.hh.ru/vacancies/possible_job_offers"

# Заголовки мобильного приложения HH — обязательный набор для api.hh.ru
# (тот же набор, что в прототипе proto_ranking_hr_activity.py).
_HH_HEADERS = {
    "User-Agent": "ru.hh.android/26.28.1",
    "x-force-app-access": "true",
}


def _fetch_offers(token: str):
    """Синхронный запрос к HH (выполняется в executor-потоке).

    Возвращает (status_code, parsed_json_or_None).
    Сетевые ошибки пробрасываются наверх как requests.RequestException.
    """
    headers = {**_HH_HEADERS, "Authorization": f"Bearer {token}"}
    r = requests.get(HH_OFFERS_URL, headers=headers, timeout=20)
    if r.status_code != 200:
        return r.status_code, None
    try:
        return 200, r.json()
    except ValueError:
        return 200, None


@router.get("/api/account/{idx}/hh_recommendations")
async def api_hh_recommendations(idx: int):
    """Список рекомендованных HH вакансий для аккаунта idx."""
    if idx < 0 or idx >= len(bot.account_states):
        return JSONResponse(
            {"ok": False, "error": "account not found"}, status_code=404
        )
    acc = bot.account_states[idx].acc

    loop = asyncio.get_event_loop()
    token = await loop.run_in_executor(None, _obtain_oauth_token, acc)
    if not token:
        return JSONResponse(
            {"ok": False, "error": "no_oauth_token"}, status_code=400
        )

    try:
        status, data = await loop.run_in_executor(None, _fetch_offers, token)
    except requests.RequestException as e:
        return JSONResponse(
            {"ok": False, "error": f"hh request failed: {e}"}, status_code=502
        )

    if status != 200:
        return JSONResponse(
            {"ok": False, "error": f"hh returned HTTP {status}"}, status_code=502
        )
    if not isinstance(data, dict) or not isinstance(data.get("possible_job_offers"), list):
        return JSONResponse(
            {"ok": False, "error": "unexpected hh response"}, status_code=502
        )

    offers = []
    for off in data["possible_job_offers"]:
        if not isinstance(off, dict):
            continue
        vid = off.get("vacancy_id")
        if vid is None:
            continue
        offers.append({
            "vacancy_id": str(vid),
            "name": off.get("vacancy_name") or "",
            "employer": off.get("employer_name") or "",
            "url": f"https://hh.ru/vacancy/{vid}",
        })

    return {"ok": True, "found": len(offers), "offers": offers}
