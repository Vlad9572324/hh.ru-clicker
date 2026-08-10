"""
Pre-flight check "чего не хватает в резюме" перед откликом на вакансию.

GET /api/account/{idx}/vacancy/{vacancy_id}/data_inconsistency
  -> мобильное API HH: GET https://api.hh.ru/resume_profile/data_inconsistency
     ?vacancy_id=X&resume_id=Y&flow=vacancy_response

Ответ 200: {ok, ready, required, humanized, skipped}.
Ошибки проверки (HH не 200 / сеть / битый JSON) НЕ блокируют отклик:
возвращаем ok=false + ready=true, UI просто пропускает такой результат.
"""

import asyncio
import re

import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.instances import bot
from app.oauth import _obtain_oauth_token

router = APIRouter()

HH_API_BASE = "https://api.hh.ru"
HH_UA = "ru.hh.android/26.28.1"

# Человекочитаемые расшифровки кодов required_additional_data (из прототипа)
FIELD_RU = {
    "WORK_FORMAT": "формат работы (удалёнка/офис/гибрид)",
    "ADDRESS_COORDINATES": "координаты адреса (геопозиция места работы)",
    "PREFERRED_WORK_AREAS": "предпочитаемые рабочие районы/локации",
    "PHOTO": "фотография в резюме",
    "SALARY": "ожидаемая зарплата",
    "EDUCATION": "образование",
    "EXPERIENCE": "опыт работы",
    "BIRTH_DATE": "дата рождения",
    "GENDER": "пол",
    "CONTACTS": "контакты",
    "ABOUT": "описание/обо мне",
    "SKILLS": "навыки",
    "LANGUAGE": "владение языками",
    "EMPLOYMENT_TYPE": "тип занятости",
    "SCHEDULE_TYPE": "график работы",
    "SALARY_WHITE": "указать ожидаемую зарплату (белый доход)",
    "DRIVING_LICENSE": "водительские права",
    "PERSONAL_QUALITIES": "личные качества",
    "RECOMMENDATIONS": "рекомендации",
    "CITIZENSHIP": "гражданство",
    "WORK_PERMIT": "разрешение на работу",
    "TRAVEL_TIME": "допустимое время в пути до работы",
}


def _humanize(code: str) -> str:
    return FIELD_RU.get(code, code)


def _extract_vacancy_id(raw: str) -> str:
    """Принимает ссылку или числовой ID — возвращает числовой ID ('' если не нашли)."""
    s = str(raw or "").strip()
    if not s:
        return ""
    m = re.search(r"/vacancy/(\d+)", s) or re.match(r"^(\d+)$", s)
    return m.group(1) if m else ""


def _fetch_data_inconsistency(token: str, vacancy_id: str, resume_id: str):
    """Синхронный GET к мобильному API HH. Возвращает (status_code|None, json|text)."""
    try:
        r = requests.get(
            f"{HH_API_BASE}/resume_profile/data_inconsistency",
            params={
                "vacancy_id": vacancy_id,
                "resume_id": resume_id,
                "flow": "vacancy_response",
            },
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": HH_UA,
                "x-force-app-access": "true",
            },
            timeout=15,
        )
    except requests.RequestException as e:
        return None, f"request error: {e}"
    if r.status_code != 200:
        return r.status_code, (r.text or "")[:500]
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, (r.text or "")[:500]


@router.get("/api/account/{idx}/vacancy/{vacancy_id}/data_inconsistency")
async def api_data_inconsistency(idx: int, vacancy_id: str):
    """Pre-flight: какие поля резюме не дают откликнуться на вакансию."""
    if not (0 <= idx < len(bot.account_states)):
        return JSONResponse({"ok": False, "error": "Invalid idx"}, status_code=404)

    vid = _extract_vacancy_id(vacancy_id)
    if not vid:
        return JSONResponse({"ok": False, "error": "invalid_vacancy_id"}, status_code=400)

    acc = bot.account_states[idx].acc
    resume_id = acc.get("resume_hash", "")
    if not resume_id:
        # Резюме просто не выбрано — не блокируем отклик.
        return {
            "ok": True, "skipped": True, "reason": "no_resume",
            "ready": True, "required": [], "humanized": [],
        }

    loop = asyncio.get_event_loop()
    token = await loop.run_in_executor(None, _obtain_oauth_token, acc)
    if not token:
        return JSONResponse({"ok": False, "error": "no_oauth_token"}, status_code=400)

    status, data = await loop.run_in_executor(
        None, _fetch_data_inconsistency, token, vid, resume_id
    )

    if status != 200:
        label = f"HTTP {status}" if status is not None else "NETWORK_ERROR"
        # Ошибка проверки НЕ блокирует отклик: ready=true, UI пропустит.
        return {
            "ok": False, "error": f"{label}: {data}",
            "ready": True, "required": [], "humanized": [], "skipped": False,
        }

    inc = data.get("data_inconsistency") if isinstance(data, dict) else None
    required = inc.get("required_additional_data") if isinstance(inc, dict) else None
    if not isinstance(required, list):
        required = []
    required = [str(x) for x in required]
    humanized = [_humanize(x) for x in required]

    return {
        "ok": True,
        "ready": not required,
        "required": required,
        "humanized": humanized,
        "skipped": False,
    }
