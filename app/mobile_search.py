"""Vacancy search through the applicant mobile API."""

from __future__ import annotations

from collections.abc import Mapping

from app.hh_mobile_transport import mobile_request


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


def search_vacancies(acc: dict, text: str, area_id=1, per_page: int = 20,
                     page: int = 0, filters: Mapping | None = None) -> list[dict]:
    """Return all search pages, starting at *page* (at most 20 requests).

    ``filters`` is passed to HH verbatim and supports scalar as well as list
    values (``requests`` serialises both correctly).  Explicit arguments win
    over colliding filter keys.
    """
    start_page = max(0, int(page))
    params = dict(filters or {})
    params.update({
        "text": text,
        "area": area_id,
        "per_page": per_page,
        "page": start_page,
    })
    result: list[dict] = []
    current = start_page
    last_page = start_page

    for _ in range(20):
        params["page"] = current
        payload = mobile_request(acc, "GET", "/vacancies", params=params)
        if not isinstance(payload, dict):
            break
        items = payload.get("items") or []
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
