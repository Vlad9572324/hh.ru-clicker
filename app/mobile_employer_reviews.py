"""Mobile-список работодателей, которых юзер может оценить (employer reviews).

Контракт (проверен live-пробой, см. docs/scratchpad deepdive report_qwen.md):

    GET https://api.hh.ru/employer_reviews/employers_to_rate
    -> {"status": "EMPLOYERS_CAN_BE_REVIEWED",
        "items": [{"employer_id": 118368, "is_employer_mapped": false,
                   "target": "PREVIOUS_EMPLOYER",
                   "employer_name": "НПА Вира Реалтайм",
                   "logo_urls": {"90": "...", "240": "..."},
                   "position": "Инженер-программист",
                   "employment_duration_id": "1", "area_id": 1,
                   "country_id": 1}, ...]}

status бывает и другим (напр. пустой items — оценивать некого).

Возврат fetch_employers_to_rate():
    {"ok": True, "count": N, "status": <status>,
     "items": [{"employer_id", "employer_name", "position", "target"}, ...]}
    — только нормализованные поля (logo_urls и пр. не пробрасываем в UI).
    {"ok": False, "error": "HTTP ..."}  # не-2xx не-fallback

Неожиданная форма ответа (не-dict, items не список, битый JSON) — НЕ ошибка:
возвращаем пустой результат, чтобы UI-badge просто остался скрыт.

Транспорт — app.hh_mobile_transport.mobile_request. Политика ошибок как в
mobile_job_search_status: fallback-статусы (0/401/403/5xx) — MobileAPIError
наверх (повтор через web-flow); прочие не-2xx — {"ok": False, ...}.

Тесты — ТОЛЬКО через responses-моки (никаких живых запросов).
"""

from app.hh_mobile_transport import (
    MOBILE_BASE,
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug

# Пустой результат: неожиданная форма ответа не должна ронять вызывающих.
_EMPTY_RESULT = {"ok": True, "count": 0, "items": [], "status": ""}


def fetch_employers_to_rate(acc: dict) -> dict:
    """Работодатели, которых можно оценить, для аккаунта acc.

    Возвращает {"ok", "count", "status", "items"} (см. модуль); на
    fallback-статусах кидает MobileAPIError (фабрика повторит через
    web-flow), прочие не-2xx — {"ok": False, "error": "HTTP ..."}.
    """
    url = f"{MOBILE_BASE}/employer_reviews/employers_to_rate"
    try:
        data = mobile_request(acc, "GET", url)
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            raise  # 0/401/403/5xx — фабрика повторит через web-flow
        log_debug(f"mobile employers_to_rate: HTTP {e.status_code}")
        return {"ok": False, "error": f"HTTP {e.status_code}"}

    if not isinstance(data, dict):
        return dict(_EMPTY_RESULT)
    items_raw = data.get("items")
    if not isinstance(items_raw, list):
        return dict(_EMPTY_RESULT)

    items = []
    for raw in items_raw:
        if not isinstance(raw, dict):
            continue  # битый элемент — пропускаем, не падаем
        items.append({
            "employer_id": raw.get("employer_id"),
            "employer_name": raw.get("employer_name") or "",
            "position": raw.get("position") or "",
            "target": raw.get("target") or "",
        })
    return {
        "ok": True,
        "count": len(items),
        "status": str(data.get("status") or ""),
        "items": items,
    }
