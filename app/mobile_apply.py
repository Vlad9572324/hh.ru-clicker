"""Mobile-версия отклика на вакансию (Phase 3).

POST https://api.hh.ru/negotiations — единый mobile-контракт отклика
(APK ru.hh.android v26.28.1, NegotiationApi метод c /
NegotiationRepositoryImpl.f): тело form-urlencoded
{vacancy_id, resume_id, with_chat_info="true", [message],
[response_source]} + обязательные tracking query-параметры
hhtmSource/hhtmFrom. Успех 2xx — {"id": "<negotiation_id>"}
(TopicInfoNetwork, id может быть null).

Транспорт — app.hh_mobile_transport.mobile_request (Bearer + mobile UA +
x-force-app-access). Fallback-политика: статусы 0 (сеть) / 401 / 403 / 5xx
НЕ глотаются — MobileAPIError перекидывается наверх, чтобы fallback-обёртка
повторила запрос через web-flow; прочие не-2xx разбираются на известные
бизнес-коды отказа (ApiError type='negotiations').
"""

import json

from app.hh_mobile_transport import (
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug

# Известные бизнес-коды отказа POST /negotiations (APK VR/f.java,
# NegotiationApiErrorConverter: test_required, limit_exceeded, ...;
# vacancy_archived/permission_denied — из брифа). Порядок перечисления
# определяет приоритет: возвращается ПЕРВЫЙ найденный в payload'е код.
KNOWN_ERROR_CODES = (
    "test_required",
    "limit_exceeded",
    "vacancy_not_found",
    "already_applied",
    "edit_forbidden",
    "application_denied",
    "resume_visibility_conflict",
    "inappropriate_language",
    "resource_policy_violation",
    "message_already_viewed",
    "resume_not_found",
    "vacancy_archived",
    "permission_denied",
)

# Короткие описания бизнес-кодов для поля "error" результата.
_ERROR_DESCRIPTIONS = {
    "test_required": "вакансия требует тестовое задание",
    "limit_exceeded": "лимит откликов исчерпан",
    "vacancy_not_found": "вакансия не найдена",
    "already_applied": "отклик уже был отправлен",
    "edit_forbidden": "редактирование отклика запрещено",
    "application_denied": "отклик отклонён",
    "resume_visibility_conflict": "конфликт видимости резюме",
    "inappropriate_language": "неприемлемый текст сообщения",
    "resource_policy_violation": "нарушение resource-политики",
    "message_already_viewed": "сообщение уже просмотрено",
    "resume_not_found": "резюме не найдено",
    "vacancy_archived": "вакансия в архиве",
    "permission_denied": "нет прав на отклик",
}


def _extract_error_code(payload) -> str:
    """Достаёт известный бизнес-код отказа из payload ошибки.

    payload приводится к lower-тексту: dict/list сериализуются через
    json.dumps, не-JSON-совместимые значения и строки — через str().
    Возвращается первый найденный код из KNOWN_ERROR_CODES, иначе "".
    Работает и для {"type": ..., "code": ...}, и для
    {"errors": [{"type": ...}]}, и для маркера в не-JSON тексте.
    """
    try:
        text = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(payload)
    text = text.lower()
    for code in KNOWN_ERROR_CODES:
        if code in text:
            return code
    return ""


def submit_response(acc: dict, vacancy_id: str, resume_id: str,
                    message: str = "", response_source: str = "",
                    hhtm_source: str = "vacancy",
                    hhtm_from: str = "vacancy", source_label: str = "",
                    required_applicant_visibility_id: str = "",
                    enable_applicant_visibility_in_country: bool | None = None) -> dict:
    """Отклик на вакансию через mobile-контракт api.hh.ru.

    POST https://api.hh.ru/negotiations, Content-Type form-urlencoded
    (mobile_request(form=...), НЕ json_body): обязательны vacancy_id и
    resume_id; with_chat_info="true" шлётся всегда (приложение всегда шлёт
    true); message и response_source — только если непустые.

    response_source: в APK enum содержит единственное значение
    "REGISTRATION" (NO_SOURCE → поле вообще не шлётся); значения
    "HH_ANDROID" в APK НЕ существует — поэтому дефолт "" (omit).

    hhtmSource/hhtmFrom — обязательные у приложения tracking
    query-параметры (дефолт "vacancy"/"vacancy").

    Возвращает:
    - 2xx: {"ok": True, "negotiation_id": str(id или "")}
      (id может быть null в TopicInfoNetwork);
    - бизнес-ошибка (не-2xx, НЕ fallback-статус):
      {"ok": False, "error_type": <известный код или "http_<status>">,
       "error": <короткое описание>, "http_status": <status>};
    - fallback-статусы (0 сеть / 401 / 403 / 5xx): MobileAPIError
      перекидывается наверх без обработки — для повтора через web-flow.
    """
    form = {
        "vacancy_id": vacancy_id,
        "resume_id": resume_id,
        "with_chat_info": "true",
    }
    if message:
        form["message"] = message
    if response_source:
        form["response_source"] = response_source
    if required_applicant_visibility_id:
        form["required_applicant_visibility_id"] = required_applicant_visibility_id
        enabled = True if enable_applicant_visibility_in_country is None else enable_applicant_visibility_in_country
        form["enable_applicant_visibility_in_country"] = str(enabled).lower()
    params = {"hhtmSource": hhtm_source, "hhtmFrom": hhtm_from}
    if source_label:
        params["source_label"] = source_label
    try:
        data = mobile_request(
            acc, "POST", "/negotiations",
            params=params,
            form=form,
        )
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            # Не глотим: fallback-обёртка повторит отклик через web-flow.
            raise
        code = _extract_error_code(e.payload)
        error_type = code or f"http_{e.status_code}"
        log_debug(f"mobile submit_response vacancy={vacancy_id}: "
                  f"HTTP {e.status_code} | error_type={error_type} | {e.payload}")
        return {
            "ok": False,
            "error_type": error_type,
            "error": _ERROR_DESCRIPTIONS.get(code, f"HTTP {e.status_code}"),
            "http_status": e.status_code,
        }
    neg_id = data.get("id") if isinstance(data, dict) else None
    log_debug(f"mobile submit_response vacancy={vacancy_id}: "
              f"ok, negotiation_id={neg_id}")
    return {"ok": True, "negotiation_id": str(neg_id or "")}
