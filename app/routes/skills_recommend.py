"""
Skills gap badge: что HH рекомендует добавить в резюме (feat3).

POST /api/account/{idx}/skills_recommend
  → POST https://api.hh.ru/skills_profile/predictions/recommended_skills/resume
    (safe POST — только ML-предсказание, ничего не меняет)
  → GET  https://api.hh.ru/career_platform/profile?profession_description=true
    (skills уже в профиле; шаг опциональный — при сбое have=[] и gap=recommended)

Ответ: {"ok": true, "recommended": [...], "have": [...], "gap": [...],
        "resume_hash": ..., "editor_url": "https://hh.ru/resume/<rh>"}
"""

import asyncio

import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.instances import bot
from app.oauth import _obtain_oauth_token

router = APIRouter()

_PREDICT_URL = "https://api.hh.ru/skills_profile/predictions/recommended_skills/resume"
_PROFILE_URL = "https://api.hh.ru/career_platform/profile"
_UA = "ru.hh.android/26.28.1"
_PROFILE_TIMEOUT = 30
_PREDICT_TIMEOUT = 60  # ML-предсказание может считаться долго


def _err(status_code: int, error: str) -> JSONResponse:
    """Единый формат ошибок: {"ok": False, "error": ...} + HTTP-статус."""
    return JSONResponse({"ok": False, "error": error}, status_code=status_code)


def _norm(name) -> str:
    """Нормализация имени skill для сравнения."""
    return " ".join((name or "").strip().lower().split())


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": _UA,
        "x-force-app-access": "true",
    }


def _extract_names(data) -> list:
    """Ответ HH: dict с ключом "skills" (список dict с name либо строк) либо просто список."""
    if isinstance(data, dict) and isinstance(data.get("skills"), list):
        items = data["skills"]
    elif isinstance(data, list):
        items = data
    else:
        return []
    names = []
    for it in items:
        if isinstance(it, dict) and it.get("name"):
            names.append(str(it["name"]))
        elif isinstance(it, str) and it.strip():
            names.append(it)
    return names


def _fetch_recommended(token: str, resume_hash: str) -> tuple:
    """POST recommended_skills/resume.

    Body сначала {"resume_id": rh}; если 400/422 — retry с {"resumeId": rh}.
    Возвращает (names, error): error пустая строка при успехе.
    """
    last_status = None
    for body in ({"resume_id": resume_hash}, {"resumeId": resume_hash}):
        resp = requests.post(
            _PREDICT_URL, headers=_headers(token), json=body,
            timeout=_PREDICT_TIMEOUT,
        )
        if resp.status_code in (400, 422):
            last_status = resp.status_code
            continue
        if resp.status_code != 200:
            return [], f"hh_http_{resp.status_code}"
        try:
            data = resp.json()
        except ValueError:
            return [], "bad_response"
        return _extract_names(data), ""
    return [], f"hh_http_{last_status}"


def _fetch_profile_skills(token: str) -> list:
    """GET career_platform/profile → skills уже в профиле.

    Опциональный шаг: любой сбой (сеть/не-200/битый JSON) → [],
    тогда gap=recommended.
    """
    try:
        resp = requests.get(
            _PROFILE_URL,
            params={"profession_description": "true"},
            headers=_headers(token),
            timeout=_PROFILE_TIMEOUT,
        )
        if resp.status_code != 200:
            return []
        return _extract_names(resp.json())
    except Exception:
        return []


def _do_recommend(acc: dict) -> dict:
    """Синхронная часть (run_in_executor): OAuth-токен → predict → profile → gap."""
    rh = acc.get("resume_hash", "")
    token = _obtain_oauth_token(acc)
    if not token:
        return {"_error": "no_oauth_token", "_status": 400}
    recommended, err = _fetch_recommended(token, rh)
    if err:
        return {"_error": err, "_status": 502}
    have = _fetch_profile_skills(token)
    have_norm = {_norm(n) for n in have}
    gap = [n for n in recommended if _norm(n) not in have_norm]
    return {
        "ok": True,
        "recommended": recommended,
        "have": have,
        "gap": gap,
        "resume_hash": rh,
        "editor_url": f"https://hh.ru/resume/{rh}",
    }


@router.post("/api/account/{idx}/skills_recommend")
async def api_skills_recommend(idx: int):
    """Skills gap: какие skills ML HH советует добавить в резюме аккаунта."""
    idx_arg = idx

    acc = bot._get_apply_acc(idx_arg)

    if acc is None:


        return JSONResponse({"ok": False, "error": "account not found"}, status_code=404)
    if not acc.get("resume_hash", ""):
        return _err(400, "no_resume")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _do_recommend, acc)
    if "_error" in result:
        return _err(result["_status"], result["_error"])
    return result
