"""Mobile pre-flight проверка вакансии перед откликом (Phase 3).

GET https://api.hh.ru/resume_profile/data_inconsistency — контракт APK
(pg/InterfaceC8731a.java, AdditionalDataNetworkApi.kt): перед откликом
приложение запрашивает, каких элементов резюме не хватает для отклика.
Query-параметры: vacancy_id (обяз.), resume_id (обяз.), flow (обяз.;
для отклика = "vacancy_response"), auto_seen ("true"); supported_screens
НЕ отправляется. Ответ — модель с полем "data_inconsistency": список
недостающих элементов резюме (например WORK_FORMAT, PHOTO); пустой
список = всё в порядке.

Транспорт — app.hh_mobile_transport.mobile_request (Bearer + mobile UA +
x-force-app-access). Fallback-политика: статусы 0 (сеть) / 401 / 403 / 5xx
НЕ глотаются — MobileAPIError перекидывается наверх, чтобы fallback-обёртка
повторила запрос через web-flow; пустое тело и прочие не-2xx обрабатываются
fail-closed ({"ok": False, ...}): лучше пропустить вакансию, чем тратить
лимит на отклик с неполными данными.
"""

from app.hh_mobile_transport import (
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug

HARD_MISSING = {"WORK_FORMAT", "ADDRESS_COORDINATES", "PREFERRED_WORK_AREAS"}


def _parse_missing(raw) -> list:
    """Защитно извлечь список недостающих элементов из data_inconsistency.

    Покрывает варианты: list строк, list dict'ов с ключом "type" или "id",
    dict со списком значений. Нераспознанное → [].
    """
    if isinstance(raw, dict):
        flat: list = []
        for value in raw.values():
            if isinstance(value, list):
                flat.extend(value)
            else:
                flat.append(value)
        raw = flat
    if not isinstance(raw, list):
        return []
    missing: list = []
    for item in raw:
        if isinstance(item, str):
            if item:
                missing.append(item)
        elif isinstance(item, dict):
            value = item.get("type") or item.get("id")
            if value:
                missing.append(str(value))
    return missing


def check_vacancy_before_apply(acc: dict, vacancy_id, resume_id: str = "",
                               flow: str = "vacancy_response") -> dict:
    """Pre-flight проверка вакансии перед откликом: хватает ли элементов резюме.

    GET api.hh.ru/resume_profile/data_inconsistency?vacancy_id&resume_id&
    flow&auto_seen=true. resume_id по умолчанию берётся из
    acc["resume_hash"].

    Возвращает {"ok": True, "missing": []}, если недостающих элементов нет,
    иначе {"ok": False, "missing": [...]}. Fail-closed: пустое тело ответа →
    {"ok": False, "missing": [], "reason": "empty_response"}; прочие
    не-fallback не-2xx → {"ok": False, "missing": [],
    "reason": "http_<status>"} (лучше пропустить вакансию, чем тратить
    лимит). На fallback-статусах (0 сеть / 401 / 403 / 5xx) перекидывает
    MobileAPIError наверх — для повтора через web-flow.
    """
    if not resume_id:
        resume_id = acc.get("resume_hash", "")
    params = {
        "vacancy_id": vacancy_id,
        "resume_id": resume_id,
        "flow": flow,
        "auto_seen": "true",
    }
    try:
        data = mobile_request(acc, "GET", "/resume_profile/data_inconsistency",
                              params=params)
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            # Не глотим: fallback-обёртка повторит запрос через web-flow.
            raise
        log_debug(f"mobile check_vacancy_before_apply vacancy={vacancy_id}: "
                  f"HTTP {e.status_code} | {e.payload} -> fail-closed")
        return {"ok": False, "missing": [], "reason": f"http_{e.status_code}"}
    if data is None:
        log_debug(f"mobile check_vacancy_before_apply vacancy={vacancy_id}: "
                  f"пустое тело -> fail-closed")
        return {"ok": False, "missing": [], "reason": "empty_response"}
    raw = data.get("data_inconsistency") if isinstance(data, dict) else None
    missing = _parse_missing(raw)
    if missing:
        log_debug(f"mobile check_vacancy_before_apply vacancy={vacancy_id}: "
                  f"не хватает {missing} -> отклик пропускается")
    hard_missing = [item for item in missing if item in HARD_MISSING]
    soft_missing = [item for item in missing if item not in HARD_MISSING]
    return {"ok": not hard_missing, "hard_missing": hard_missing,
            "soft_missing": soft_missing}
