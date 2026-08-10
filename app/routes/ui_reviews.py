"""UI full coverage: employer reviews to rate — кого можно оценить.

Mobile-эндпоинт HH (проверен live-пробой, см. scratchpad deepdive
report_qwen.md):

    GET {MOBILE_BASE}/employer_reviews/employers_to_rate
    -> {"status": "EMPLOYERS_CAN_BE_REVIEWED", "items": [{employer_id,
       employer_name, position, target, logo_urls, ...}, ...]}

UI-потребитель: static/js/features/reviews_badge.js (badge "⭐ Оценить: N"
в header + попап со списком по аккаунтам).
"""

import asyncio

from fastapi import APIRouter

from app.hh_mobile_transport import MobileAPIError
from app.instances import bot
from app.mobile_employer_reviews import fetch_employers_to_rate

router = APIRouter()


@router.get("/api/account/{idx}/reviews_to_rate")
async def api_reviews_to_rate(idx: int):
    """Работодатели, которых юзер может оценить (mobile
    GET /employer_reviews/employers_to_rate), для аккаунта idx.

    Возврат: {"ok": True, "count", "status", "items": [...]} либо
    {"ok": False, "error": ...}.
    """
    acc = bot._get_apply_acc(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, fetch_employers_to_rate, acc)
    except MobileAPIError as e:
        return {"ok": False, "error": str(e)}
    return result
