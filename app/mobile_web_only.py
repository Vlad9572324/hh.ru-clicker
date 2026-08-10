"""Mobile analogs of operations that historically used the hh.ru web UI.

The decline contract was recovered from Android's ``NegotiationApi``:
``DELETE /negotiations/active/{negotiationId}`` with query parameter
``with_decline_message``.  Diagnostics and employer ratings use public
api.hh.ru resources.  All calls go through the common mobile transport so
401/403/network/5xx errors retain FallbackHHClient semantics.
"""

from app.hh_mobile_transport import MobileAPIError, is_fallback_status, mobile_request
from app.logging_utils import log_debug


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_request(acc, path, *, params=None):
    """Return None for an unavailable optional source, preserving fallback."""
    try:
        return mobile_request(acc, "GET", path, params=params)
    except MobileAPIError as exc:
        if is_fallback_status(exc.status_code):
            raise
        log_debug(f"mobile optional GET {path}: HTTP {exc.status_code}")
        return None


def auto_decline_discards(acc: dict, max_pages: int = 5, limit: int = 50) -> int:
    """Decline removable DISCARD negotiations using the Android API contract."""
    ids = []
    seen = set()
    for page in range(max_pages):
        try:
            data = mobile_request(
                acc, "GET", "/negotiations",
                params={"status": "discard", "page": page, "per_page": 100},
            )
        except MobileAPIError as exc:
            if is_fallback_status(exc.status_code):
                raise
            log_debug(f"mobile auto_decline_discards list: HTTP {exc.status_code}")
            break
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            state = item.get("state") or {}
            state_id = state.get("id") if isinstance(state, dict) else state
            if state_id and str(state_id).lower() != "discard":
                continue
            allowed = item.get("decline_allowed", item.get("is_decline_allowed", True))
            negotiation_id = item.get("id")
            if allowed and negotiation_id is not None and negotiation_id not in seen:
                seen.add(negotiation_id)
                ids.append(str(negotiation_id))
                if len(ids) >= limit:
                    break
        if len(ids) >= limit or len(items) < 100:
            break

    declined = 0
    for negotiation_id in ids:
        try:
            mobile_request(
                acc, "DELETE", f"/negotiations/active/{negotiation_id}",
                params={"with_decline_message": "true"},
            )
            declined += 1
        except MobileAPIError as exc:
            if is_fallback_status(exc.status_code):
                raise
            log_debug(
                f"mobile auto_decline_discards {negotiation_id}: "
                f"HTTP {exc.status_code}"
            )
    return declined


def _job_status(me):
    candidates = [
        me.get("job_search_status"),
        (me.get("applicant_user_statuses") or {}).get("job_search_status"),
        (me.get("user_statuses") or {}).get("job_search_status"),
    ]
    for value in candidates:
        if isinstance(value, dict):
            value = value.get("id") or value.get("name")
        if value:
            return str(value).lower()
    return None


def fetch_account_diagnostics(acc: dict) -> dict:
    """Compose the web-compatible diagnostic envelope from mobile sources.

    SSR-only per-resume flags and search-show/recommendation metrics cannot be
    reproduced by api.hh.ru; their containers stay empty and ``source_gaps``
    describes that deliberate difference.
    """
    out = {
        "status": None, "status_label": None, "red_flags": [],
        "stats": {"per_resume": {}, "resume_limits": {},
                  "suitable_vacancies": {}, "user_stats": {},
                  "global_invitations": None},
        "resumes": [],
        "source": "mobile",
        "source_gaps": [
            "SSR resume visibility/error flags are unavailable",
            "SSR per-resume search shows and recommendations are unavailable",
        ],
    }
    me = mobile_request(acc, "GET", "/me", params={"with_user_statuses": "true"})
    if not isinstance(me, dict):
        me = {}
    status = _job_status(me)
    out["status"] = status
    labels = {
        "active_search": "Активно ищу работу",
        "looking_for_offers": "Рассматриваю предложения",
        "not_looking_for_job": "Не ищу работу",
    }
    out["status_label"] = labels.get(status, status)
    if status == "not_looking_for_job":
        out["red_flags"].append("🚨 Статус «Не ищу работу» — работодатели видят этот статус")
    elif status and status not in ("active_search", "looking_for_offers", "accept_offers"):
        out["red_flags"].append(f"⚠️ Статус «{status}» — лучше переключить на active_search")

    uuid = me.get("uuid") or me.get("id")
    counters = _optional_request(
        acc, "/counters/user", params={"uuid": uuid}
    ) if uuid else None
    statistic = _optional_request(acc, "/negotiations_statistic/mine")
    out["stats"]["user_stats"] = counters if isinstance(counters, dict) else {}
    if isinstance(statistic, dict):
        out["stats"]["negotiations_statistic"] = statistic
        applicant = statistic.get("applicant_statistic") or {}
        out["stats"]["global_invitations"] = applicant.get("invitations")

    # Some /me variants include a compact resume list. Preserve it without
    # pretending that unavailable SSR booleans are known.
    raw_resumes = me.get("resumes") or []
    if isinstance(raw_resumes, dict):
        raw_resumes = raw_resumes.get("items") or []
    for resume in raw_resumes if isinstance(raw_resumes, list) else []:
        if not isinstance(resume, dict):
            continue
        out["resumes"].append({
            "title": resume.get("title") or resume.get("name") or "(без названия)",
            "hash": resume.get("id") or resume.get("hash") or "",
            "canTouch": resume.get("can_touch"),
            "canPublishOrUpdate": resume.get("can_publish_or_update"),
            "hasPublicVisibility": None,
            "hasErrors": None,
            "hasConditions": None,
            "accessType": resume.get("access", {}).get("type", "")
            if isinstance(resume.get("access"), dict) else "",
        })
    return out


def fetch_employer_rating(acc: dict, employer_id) -> dict | None:
    """Return the web method's compact shape using mobile employer APIs."""
    try:
        eid = int(str(employer_id).strip())
    except (TypeError, ValueError):
        return None
    if eid <= 0:
        return None
    employer = _optional_request(acc, f"/employers/{eid}")
    reviews = _optional_request(acc, f"/employers/{eid}/reviews")
    conditions = _optional_request(acc, f"/employers/{eid}/reviews/conditions")
    if not isinstance(reviews, dict):
        return None
    try:
        total = float(reviews.get("total_rating") or 0)
    except (TypeError, ValueError):
        total = 0.0
    if not total and not _as_int(reviews.get("reviews_count")):
        return None
    ratings_raw = reviews.get("ratings") or reviews.get("rating") or []
    rating_map = {}
    if isinstance(ratings_raw, list):
        rating_map = {str(x.get("id", "")).upper(): x.get("value")
                      for x in ratings_raw if isinstance(x, dict)}
    elif isinstance(ratings_raw, dict):
        rating_map = {str(k).upper(): v for k, v in ratings_raw.items()}
    return {
        "id": eid,
        "name": employer.get("name", "") if isinstance(employer, dict) else "",
        "total": round(total, 1),
        "recommend_pct": reviews.get("recommendations_percent"),
        "ratings": {
            "workplace": rating_map.get("WORKPLACE"),
            "team": rating_map.get("TEAM"),
            "management": rating_map.get("MANAGEMENT"),
            "career": rating_map.get("CAREER"),
            "rest": rating_map.get("REST_RECOVERY"),
            "salary": rating_map.get("SALARY"),
        },
        "advantages": (reviews.get("advantages") or [])[:3],
        "reviews_count": _as_int(reviews.get("reviews_count")),
        "neg_count": _as_int(reviews.get("negative_reviews_count")),
        "staff_count": (employer.get("employees_count") or "")
        if isinstance(employer, dict) else "",
        "status": employer.get("type", "") if isinstance(employer, dict) else "",
        "is_open": bool(employer.get("open", False)) if isinstance(employer, dict) else False,
        "review_conditions": conditions if isinstance(conditions, dict) else {},
    }
