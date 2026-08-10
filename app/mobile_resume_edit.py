"""Mobile-версия edit_resume_field: редактирование полей резюме (Phase 4).

Контракт записи (reverse APK, scratchpad/apk_writes/apk_writes_group_5.yaml):

    PUT https://api.hh.ru/resume_profile/{resume_id}
    body (EditResumeProfileRequestNetwork, diff-save pattern):
        {"resume": {<field>: <value>, ...},   # JSON-diff изменённых полей
         "creds": {},                          # required non-null, пусто
         "additional_properties": {}}          # required non-null, пусто

Валидация перед записью: GET https://api.hh.ru/resumes/{resume_id}/conditions
— правила для 39 полей: {required, regexp?, min_length?, max_length?}
(apidocs_group_2.yaml, live 2026-08-10). Строковые значения проверяются
по regexp (re.fullmatch) и длинам; нарушение → отказ БЕЗ запроса на запись.

Возврат (контракт Phase 4, совместим с web {ok, error}):
    {"ok": True, "updated_field": [<имена полей>]}
    {"ok": False, "error": "..."}

Транспорт — app.hh_mobile_transport.mobile_request. Политика ошибок:
fallback-статусы (0/401/403/5xx) — MobileAPIError наверх (повтор через
web-flow); прочие не-2xx при записи — {"ok": False, "error": "HTTP ..."};
сбой получения conditions (не-fallback) — валидация пропускается, запись
продолжается (правила недоступны — не блокировать редактирование).

ВНИМАНИЕ: write-операция. Тесты — ТОЛЬКО через responses-моки, никаких
живых запросов (dry-probe этого endpoint'а не делался: safe_for_dry_probe
= false в apk_writes).
"""

import re

from app.hh_mobile_transport import (
    MOBILE_BASE,
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug


def _string_candidates(value) -> list:
    """Строковые кандидаты значения поля для валидации по conditions.

    Поддерживаемые формы: простая строка; web-формат list
    [{"string": "..."}, ...]; dict с ключом "string" либо "name".
    Для не-строковых значений возвращает [] — валидация поля пропускается.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                s = item.get("string")
                if isinstance(s, str):
                    out.append(s)
        return out
    if isinstance(value, dict):
        s = value.get("string") or value.get("name")
        return [s] if isinstance(s, str) else []
    return []


def _check_rule(rule: dict, text: str):
    """Проверка строки по правилам поля из conditions: regexp
    (re.fullmatch), min_length/max_length (число символов). Возвращает
    причину нарушения либо None. Некорректные правила сервера запись не
    блокируют (неизвестное правило == его нет)."""
    regexp = rule.get("regexp")
    if isinstance(regexp, str) and regexp:
        try:
            matches = re.fullmatch(regexp, text) is not None
        except re.error:
            matches = True  # битый regexp от сервера — не блокируем
        if not matches:
            return f"не соответствует regexp {regexp!r}"
    min_length = rule.get("min_length")
    if isinstance(min_length, int) and not isinstance(min_length, bool) \
            and len(text) < min_length:
        return f"длина {len(text)} меньше min_length {min_length}"
    max_length = rule.get("max_length")
    if isinstance(max_length, int) and not isinstance(max_length, bool) \
            and len(text) > max_length:
        return f"длина {len(text)} больше max_length {max_length}"
    return None


def edit_resume_field(acc: dict, resume_hash: str, fields: dict) -> dict:
    """Редактирование полей резюме через mobile-API (аналог web
    hh_resume._edit_resume_field).

    resume_hash — hash резюме; fields — свободный JSON-diff
    {field: value} (например {"title": [{"string": "QA"}]}). Возвращает
    {"ok": True, "updated_field": [...]} либо {"ok": False, "error": ...};
    на fallback-статусах кидает MobileAPIError (повтор через web-flow).
    """
    # Входной контроль БЕЗ сети: пустой hash или пустой/не-dict fields —
    # запросы не имеют смысла.
    resume_hash = str(resume_hash or "").strip()
    if not resume_hash:
        return {"ok": False, "error": "пустой resume_hash"}
    if not isinstance(fields, dict) or not fields:
        return {"ok": False, "error": "fields должен быть непустым dict"}

    # 1) Валидация: GET /resumes/{hash}/conditions — правила по полям
    #    ({required, regexp?, min_length?, max_length?}).
    rules_by_field: dict = {}
    try:
        data = mobile_request(acc, "GET",
                              f"{MOBILE_BASE}/resumes/{resume_hash}/conditions")
        if isinstance(data, dict):
            rules_by_field = data
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            # 0/401/403/5xx — не ловим: fallback-обёртка повторит через
            # web-flow.
            raise
        # Правила недоступны (404 и т.п.) — валидация пропускается,
        # запись продолжается.
        log_debug(f"mobile edit_resume_field {resume_hash}: conditions "
                  f"HTTP {e.status_code} | {e.payload} — валидация пропущена")

    for field, value in fields.items():
        rule = rules_by_field.get(field)
        if not isinstance(rule, dict):
            continue  # правил для поля нет — пропускаем
        for text in _string_candidates(value):
            reason = _check_rule(rule, text)
            if reason is not None:
                return {"ok": False,
                        "error": f"validation_failed: {field}: {reason}"}

    # 2) Запись: PUT /resume_profile/{hash}, diff-save тело (контракт APK
    #    EditResumeProfileRequestNetwork).
    body = {"resume": fields, "creds": {}, "additional_properties": {}}
    try:
        mobile_request(acc, "PUT",
                       f"{MOBILE_BASE}/resume_profile/{resume_hash}",
                       json_body=body)
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            raise
        payload = e.payload if isinstance(e.payload, str) else str(e.payload)
        log_debug(f"mobile edit_resume_field {resume_hash}: PUT "
                  f"HTTP {e.status_code} | {payload[:200]}")
        return {"ok": False, "error": f"HTTP {e.status_code}: {payload[:200]}"}
    return {"ok": True, "updated_field": sorted(fields.keys())}
