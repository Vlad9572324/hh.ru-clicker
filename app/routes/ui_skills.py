"""UI full coverage: skill verifications — доступные тесты верификации навыков.

Mobile-эндпоинты HH (проверены live-пробами, см. scratchpad deepdive
report_kimi.md / probe_qwen_r2_final.json):

    GET {MOBILE_BASE}/skill_verifications/methods             -> доступные тесты
    GET {MOBILE_BASE}/skill_verifications/skills              -> навыки юзера + статусы
    GET {MOBILE_BASE}/verification_methods/skills/{skill_id}  -> syllabus теста

Транспорт — app.mobile_skill_verifications (поверх mobile_request).
Синхронные mobile-вызовы уводятся в executor, чтобы не блокировать
event loop (стиль app/routes/accounts.py). MobileAPIError (fallback-
статусы 0/401/403/5xx) возвращается фронту как {"ok": False, "error"} —
web-flow повтор здесь, в UI-роуте, не нужен.
"""

import asyncio

from fastapi import APIRouter

from app.hh_mobile_transport import MobileAPIError
from app.instances import bot
from app.mobile_skill_verifications import (
    fetch_skill_verification_methods,
    fetch_skill_verification_skills,
    fetch_verification_syllabus,
)


router = APIRouter()


@router.get("/api/account/{idx}/skill_verifications/methods")
async def api_skill_verification_methods(idx: int):
    """Доступные тесты верификации навыков аккаунта."""
    acc = bot._get_apply_acc(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None, fetch_skill_verification_methods, acc)
    except MobileAPIError as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/account/{idx}/skill_verifications/skills")
async def api_skill_verification_skills(idx: int):
    """Навыки юзера и их статусы верификации."""
    acc = bot._get_apply_acc(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None, fetch_skill_verification_skills, acc)
    except MobileAPIError as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/account/{idx}/skill_verification/{skill_id}")
async def api_skill_verification_syllabus(idx: int, skill_id: int):
    """Syllabus теста для навыка skill_id (id из verification_objects)."""
    acc = bot._get_apply_acc(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None, fetch_verification_syllabus, acc, skill_id)
    except MobileAPIError as e:
        return {"ok": False, "error": str(e)}
