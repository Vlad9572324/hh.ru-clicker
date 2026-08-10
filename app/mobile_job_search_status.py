"""Mobile-версия set_job_search_status: смена статуса поиска работы (Phase 4).

Контракт (reverse APK ru.hh.android/26.28.1, JobSearchStatusRemoteApi.kt —
Uq/InterfaceC4443a.java: @PUT + @FormUrlEncoded + @Field("id")):

    PUT https://api.hh.ru/user_statuses/job_search_statuses/mine
    form-body: id=<status_id>

Канонические id статусов (APK SearchStatus.kt,
ru/hh/applicant/core/model/job_search/SearchStatus.java):
    active_search, looking_for_offers, not_looking_for_job,
    has_job_offer, accepted_job_offer

Принимаются также web-иды (hh_resume._JOB_SEARCH_STATUSES: accept_offers)
и алиасы из брифа Phase 4 — нормализуются к каноническим (маппинг и
расхождение с брифом задокументированы в отчёте Phase 4: значения
not_looking/considering/already_found/about_to_leave в APK не найдены).

Возврат (совместим с web hh_resume.set_job_search_status):
    {"ok": True, "status": <канонический id>, "label": <человекочитаемо>}
    {"ok": False, "error": "..."}   # неизвестный статус / HTTP-ошибка

Транспорт — app.hh_mobile_transport.mobile_request. Политика ошибок:
fallback-статусы (0/401/403/5xx) — MobileAPIError наверх (повтор через
web-flow); прочие не-2xx — {"ok": False, "error": "HTTP ..."}.

ВНИМАНИЕ: write-операция. Тесты — ТОЛЬКО через responses-моки.
"""

from app.hh_mobile_transport import (
    MOBILE_BASE,
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug

# Канонические id (APK SearchStatus.kt) + web-иды и алиасы брифа Phase 4.
# Значение маппится само в себя, если уже каноническое.
_STATUS_ALIASES = {
    "active_search": "active_search",
    "looking_for_offers": "looking_for_offers",
    "accept_offers": "looking_for_offers",      # web-id (hh_resume.py)
    "considering": "looking_for_offers",        # алиас брифа phase 4
    "about_to_leave": "looking_for_offers",     # алиас брифа phase 4
    "not_looking_for_job": "not_looking_for_job",
    "not_looking": "not_looking_for_job",       # алиас брифа phase 4
    "has_job_offer": "has_job_offer",
    "accepted_job_offer": "accepted_job_offer",
    "already_found": "accepted_job_offer",      # алиас брифа phase 4
}

_STATUS_LABELS = {
    "active_search": "🟢 Активно ищу работу",
    "looking_for_offers": "🟡 Рассматриваю предложения",
    "not_looking_for_job": "🔴 Не ищу работу",
    "has_job_offer": "🟠 Есть оффер",
    "accepted_job_offer": "🔵 Принят оффер",
}


def set_job_search_status(acc: dict, status: str) -> dict:
    """Смена статуса поиска работы через mobile-API (аналог web
    hh_resume.set_job_search_status).

    status — id статуса либо алиас (нормализуется через _STATUS_ALIASES).
    Возвращает {"ok": True, "status": ..., "label": ...} либо
    {"ok": False, "error": ...}; на fallback-статусах кидает
    MobileAPIError (повтор через web-flow).
    """
    norm = str(status or "").strip().lower()
    canonical = _STATUS_ALIASES.get(norm)
    if canonical is None:
        # Неизвестный статус — в сеть не идём вообще.
        return {
            "ok": False,
            "error": f"Неизвестный статус: {norm!r}. Доступные: {sorted(_STATUS_ALIASES)}",
        }
    url = f"{MOBILE_BASE}/user_statuses/job_search_statuses/mine"
    try:
        mobile_request(acc, "PUT", url, form={"id": canonical})
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            raise  # 0/401/403/5xx — фабрика повторит через web-flow
        log_debug(f"mobile set_job_search_status {canonical}: HTTP {e.status_code}")
        return {"ok": False, "error": f"HTTP {e.status_code}"}
    return {
        "ok": True,
        "status": canonical,
        "label": _STATUS_LABELS.get(canonical, canonical),
    }
