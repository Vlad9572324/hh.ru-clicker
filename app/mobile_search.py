"""Vacancy search through the applicant mobile API."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import quote, urlencode

from app.hh_mobile_transport import mobile_request
from app.logging_utils import log_debug


def _normalise_item(item: dict) -> dict:
    """Keep HH fields intact and add the stable URL expected by callers."""
    result = dict(item)
    result["id"] = str(item.get("id") or "")
    result.setdefault("name", "")
    result.setdefault("employer", {})
    result.setdefault("area", {})
    result.setdefault("salary", None)
    result["url"] = item.get("alternate_url") or item.get("url") or (
        f"https://hh.ru/vacancy/{result['id']}" if result["id"] else ""
    )
    return result


def search_vacancies(acc: dict, text: str, area_id=113, per_page: int = 20,
                     page: int = 0, filters: Mapping | None = None,
                     max_pages: int = 20) -> list[dict]:
    """Return at most *max_pages* search pages, starting at *page*.

    ``filters`` is passed to HH verbatim and supports scalar as well as list
    values (``requests`` serialises both correctly).  Explicit arguments win
    over colliding filter keys.
    """
    start_page = max(0, int(page))
    params = dict(filters or {})
    resume_id = str(params.pop("resume", "") or "").strip()
    if resume_id:
        # Android 26.29, VacancyUrlConverter.kt::b:
        # /resumes/{id}/similar_vacancies, а НЕ /vacancies?resume=id.
        # Последний публичный endpoint игнорирует resume и отдаёт общий поиск.
        endpoint = f"/resumes/{quote(resume_id, safe='')}/similar_vacancies"
        request_per_page = max(1, min(int(per_page), 20))
        params.update({
            "text": text,
            "area": area_id,
            "per_page": request_per_page,
            "page": start_page,
            "responses_count_enabled": "true",
            "with_chat_info": "true",
            "check_misleading_vacancy_alert": "true",
            "with_skills_match": "false",
        })
        mode = "mobile-resume"
    else:
        endpoint = "/vacancies"
        params.update({
            "text": text,
            "area": area_id,
            "per_page": per_page,
            "page": start_page,
        })
        mode = "mobile"
    result: list[dict] = []
    current = start_page
    last_page = start_page

    request_limit = max(0, min(int(max_pages), 20))
    for _ in range(request_limit):
        params["page"] = current
        page_url = "https://api.hh.ru" + endpoint + "?" + urlencode(params, doseq=True)
        label = acc.get("short") or acc.get("name") or acc.get("resume_hash", "?")
        log_debug(
            f"COLLECT_PAGE start [{label}] mode={mode} "
            f"page={current + 1} page_index={current} url={page_url}"
        )
        payload = mobile_request(acc, "GET", endpoint, params=params)
        if not isinstance(payload, dict):
            log_debug(
                f"COLLECT_PAGE invalid [{label}] mode={mode} "
                f"page={current + 1} url={page_url}"
            )
            break
        items = payload.get("items") or []
        log_debug(
            f"COLLECT_PAGE parsed [{label}] mode={mode} "
            f"page={current + 1} vacancies={len(items)} url={page_url}"
        )
        result.extend(_normalise_item(item) for item in items if isinstance(item, dict))

        try:
            pages = max(0, int(payload.get("pages", 0)))
        except (TypeError, ValueError):
            pages = 0
        last_page = pages - 1
        if not items or current >= last_page:
            break
        current += 1

    return result
