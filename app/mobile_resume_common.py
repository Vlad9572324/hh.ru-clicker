"""Общие утилиты mobile-методов резюме (Phase 4).

resolve_resume_id() — единая точка резолва hash'а резюме для аккаунта:
явный аргумент → acc["resume_hash"] → первый hash из списка резюме
аккаунта (GET /mobile/resumes/mine, запасной путь GET /resumes/mine —
этот endpoint уже используется в app/routes/sessions.py::_refresh_via_oauth).
Возвращает пустую строку, если резюме не найдено (что делать с пустотой —
решает вызывающий модуль: дефолтный результат, как в Phase 2).

Политика ошибок — конвенция Phase 2 (см. app/mobile_neg_meta.py):
fallback-статусы (0/401/403/5xx, см. is_fallback_status) поднимаются
MobileAPIError наверх — FallbackHHClient прозрачно повторит вызов через
web-flow; прочие не-2xx обрабатываются на месте (пустой результат,
log_debug), исключение НЕ кидается.
"""

from app.hh_mobile_transport import (
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug

# Пути списка резюме: /mobile/resumes/mine — live-проверенный контракт
# Android-приложения; /resumes/mine — официальный OAuth-endpoint (запасной).
_RESUME_LIST_PATHS = ("/mobile/resumes/mine", "/resumes/mine")


def _extract_resume_ids(data) -> list:
    """Hash'ы резюме из ответа списка: {"items": [{id|hash, ...}]} либо
    bare-list той же формы. Прочие формы → []."""
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        rid = it.get("id") or it.get("hash") or ""
        if rid:
            out.append(str(rid))
    return out


def fetch_my_resume_ids(acc: dict) -> list:
    """Список hash'ов резюме аккаунта (первое — основное резюме).

    GET /mobile/resumes/mine?per_page=30; если endpoint ответил не-2xx
    (кроме fallback-статусов) либо не отдал ни одного hash'а — запасной
    GET /resumes/mine. Fallback-статусы (0/401/403/5xx) перекидываются
    MobileAPIError наверх (повтор через web-flow)."""
    for path in _RESUME_LIST_PATHS:
        try:
            data = mobile_request(acc, "GET", path, params={"per_page": 30})
        except MobileAPIError as e:
            if is_fallback_status(e.status_code):
                raise
            log_debug(f"mobile fetch_my_resume_ids {path}: HTTP {e.status_code} "
                      f"— пробую запасной путь")
            continue
        ids = _extract_resume_ids(data)
        if ids:
            return ids
    return []


def resolve_resume_id(acc: dict, resume_id=None) -> str:
    """Резолв hash'а резюме: явный аргумент → acc["resume_hash"] → первый
    hash из списка аккаунта (fetch_my_resume_ids). Пустая строка, если
    ничего не найдено."""
    rid = str(resume_id or "").strip()
    if rid:
        return rid
    rid = str(acc.get("resume_hash") or "").strip()
    if rid:
        return rid
    ids = fetch_my_resume_ids(acc)
    return ids[0] if ids else ""
