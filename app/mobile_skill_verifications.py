"""Навыки и верификации: доступные тесты, навыки юзера, syllabus (UI full coverage).

Mobile-эндпоинты HH (проверены live-пробами, см. scratchpad deepdive
report_kimi.md / probe_qwen_r2_final.json):

    GET {MOBILE_BASE}/skill_verifications/methods
    -> {"found": N, "page", "pages", "per_page", "items": [{id, group_id,
       name, description, platform, kak_dela_quiz: {quiz_id, url_template,
       estimated_time, content, task_number},
       verification_objects: [{id, name, category,
       level: {id, internal_id, name, rank}}],
       availability: {available_at, status}}, ...]}
    — доступные тесты верификации навыков.

    GET {MOBILE_BASE}/skill_verifications/skills
    -> {"found": N, "items": [{id, name, category, level, verified,
       verified_by, has_report, ...}, ...]}
    — навыки юзера и их статусы верификации.

    GET {MOBILE_BASE}/verification_methods/skills/{skill_id}
    -> {"id", "name", "category", "result": {state, theory, practice},
       "levels": [{id, internal_id, name, rank, theory: {id, name, content,
       task_number, estimated_time}}, ...]}
    — syllabus (программа теста) для навыка skill_id. skill_id — это id из
    verification_objects метода, НЕ id самого метода.

Транспорт — app.hh_mobile_transport.mobile_request. Политика ошибок
(как в mobile_job_search_status.py): fallback-статусы (0/401/403/5xx,
см. is_fallback_status) — MobileAPIError наверх (повтор через web-flow);
прочие не-2xx — {"ok": False, "error": "HTTP ..."}.

Возврат:
    списочные  -> {"ok": True, "found": N, "items": [...]}
    syllabus   -> {"ok": True, **data}

ВНИМАНИЕ: read-only операции, но тесты — ТОЛЬКО через responses-моки.
"""

from app.hh_mobile_transport import (
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug


def _list_result(data) -> dict:
    """Нормализация списочного ответа к {"ok", "found", "items"}.

    Защита от нестандартных тел: не-dict / отсутствие полей — пустой
    список, found = len(items).
    """
    if not isinstance(data, dict):
        data = {}
    items = data.get("items")
    if not isinstance(items, list):
        items = []
    found = data.get("found")
    if not isinstance(found, int):
        found = len(items)
    return {"ok": True, "found": found, "items": items}


def _fetch_list_endpoint(acc: dict, path: str) -> dict:
    """Общий GET для списочных эндпоинтов верификаций.

    fallback-статусы (0/401/403/5xx) кидает MobileAPIError наверх
    (фабрика повторит через web-flow); прочие не-2xx —
    {"ok": False, "error": "HTTP ..."}.
    """
    try:
        data = mobile_request(acc, "GET", path)
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            raise  # 0/401/403/5xx — фабрика повторит через web-flow
        log_debug(f"mobile skill_verifications {path}: HTTP {e.status_code}")
        return {"ok": False, "error": f"HTTP {e.status_code}"}
    return _list_result(data)


def fetch_skill_verification_methods(acc: dict) -> dict:
    """Доступные тесты верификации навыков.

    GET /skill_verifications/methods -> {"ok": True, "found": N,
    "items": [...]}; каждый элемент — метод теста с kak_dela_quiz
    (вопросы/тайминг) и verification_objects (какой навык проверяет).
    """
    return _fetch_list_endpoint(acc, "/skill_verifications/methods")


def fetch_skill_verification_skills(acc: dict) -> dict:
    """Навыки юзера и их статусы верификации.

    GET /skill_verifications/skills -> {"ok": True, "found": N,
    "items": [...]}; каждый элемент — навык с флагами verified /
    verified_by / has_report.
    """
    return _fetch_list_endpoint(acc, "/skill_verifications/skills")


def fetch_verification_syllabus(acc: dict, skill_id) -> dict:
    """Syllabus (программа) теста для навыка skill_id.

    GET /verification_methods/skills/{skill_id} -> {"ok": True, **data}:
    имя навыка, result (состояние теории/практики) и levels[] с theory
    (content — список тем, task_number, estimated_time).

    skill_id — id навыка из verification_objects метода, НЕ id метода.
    """
    path = f"/verification_methods/skills/{skill_id}"
    try:
        data = mobile_request(acc, "GET", path)
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            raise  # 0/401/403/5xx — фабрика повторит через web-flow
        log_debug(f"mobile verification syllabus skill={skill_id}: "
                  f"HTTP {e.status_code}")
        return {"ok": False, "error": f"HTTP {e.status_code}"}
    if not isinstance(data, dict):
        data = {}
    return {"ok": True, **data}
