"""Mobile-версия fetch_resume: полное резюме через api.hh.ru (Phase 4).

Источник: GET https://api.hh.ru/resumes/{resume_id}
?with_professional_roles=true&with_creds=true — полный JSON резюме
(legacy-формат api.hh.ru, ~63 top-level ключа: last_name/first_name/title/
area/age/salary/total_experience/skills/experience/education/status/
total_views/new_views/... — scratchpad/apidocs/apidocs_group_2.yaml,
live-проба 2026-08-10).

Резолв hash'а при resume_id=None: app.mobile_resume_common.resolve_resume_id
(явный аргумент → acc["resume_hash"] → первое резюме из
GET /mobile/resumes/mine).

Транспорт — app.hh_mobile_transport.mobile_request (Bearer + mobile UA +
x-force-app-access). Политика ошибок: fallback-статусы (0/401/403/5xx)
поднимаются MobileAPIError (FallbackHHClient повторит через web-flow);
прочие не-2xx (404 — резюме не найдено и т.п.) → пустой dict.

ВНИМАНИЕ (расхождение с web, задокументировано в отчёте Phase 4):
web-версия hh_resume.fetch_resume_text возвращает str (текст резюме для
LLM-контекста); mobile-версия возвращает dict — полный JSON резюме
(структурные данные полезнее текста для JSON-потребителей, текст при
необходимости собирается из тех же полей).
"""

from app.hh_mobile_transport import (
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug
from app.mobile_resume_common import resolve_resume_id


def fetch_resume(acc: dict, resume_id=None) -> dict:
    """Полное резюме аккаунта через mobile-API.

    resume_id=None — резолвится в первое резюме аккаунта
    (resolve_resume_id). Возвращает полный JSON резюме (dict); пустой
    dict если резюме не найдено/не передано. Fallback-статусы
    (0/401/403/5xx) — MobileAPIError наверх для повтора через web-flow.
    """
    rid = resolve_resume_id(acc, resume_id)
    if not rid:
        # Резюме не найдено/не передано — запрашивать /resumes/ не с чем.
        return {}
    try:
        data = mobile_request(
            acc, "GET", f"/resumes/{rid}",
            params={"with_professional_roles": "true", "with_creds": "true"},
        )
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            # 0 (сеть) / 401 / 403 / 5xx: не глотим — FallbackHHClient
            # повторит через web-flow.
            raise
        log_debug(f"mobile fetch_resume: HTTP {e.status_code} | {e.payload}")
        return {}
    return data if isinstance(data, dict) else {}
