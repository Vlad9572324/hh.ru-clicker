"""Mobile-версия fetch_stats: статистика резюме через api.hh.ru (Phase 4).

Источники (все три независимы, сбой одного не роняет остальные):

1. GET https://api.hh.ru/me?with_user_statuses=true — counters профиля:
   new_resume_views (новые просмотры резюме), unread_negotiations,
   resumes_count (scratchpad/apidocs/apidocs_group_5.yaml, live).
2. GET https://api.hh.ru/resumes/{resume_id} — total_views (просмотры за
   всё время) и new_views у конкретного резюме
   (apidocs_group_2.yaml, live 2026-08-10).
3. GET https://api.hh.ru/negotiations_statistic/mine — streak-геймификация
   откликов: applicant_statistic.responses_streak
   {responses_count, responses_required}.

Возврат — dict с ключами web-версии hh_resume.fetch_resume_stats
(views, views_new, shows, invitations, invitations_new,
next_touch_seconds, free_touches, global_invitations,
new_invitations_total) + mobile-добавки (resumes_count,
unread_negotiations, streak). shows/invitations/next_touch_seconds/
free_touches в mobile-API недоступны (данные web-SSR /applicant/resumes)
— нули, как в web при отсутствии данных.

Политика ошибок: fallback-статусы (0/401/403/5xx) на основном источнике
(/me) — MobileAPIError наверх (повтор через web-flow); сбой вспомогательных
источников (не-fallback) — log_debug и нули.
"""

from app.hh_mobile_transport import (
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug
from app.mobile_resume_common import resolve_resume_id


def _as_int(value, default: int = 0) -> int:
    """value → int; None/мусор → default (mobile-ответы не гарантируют
    числовые типы счётчиков)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def fetch_stats(acc: dict, resume_id=None) -> dict:
    """Статистика резюме через mobile-API (аналог web
    hh_resume.fetch_resume_stats; ключи совместимы).

    resume_id=None — резолвится в первое резюме аккаунта
    (mobile_resume_common.resolve_resume_id: явный аргумент →
    acc["resume_hash"] → GET /mobile/resumes/mine).

    Возвращает dict (см. докстринг модуля): web-ключи +
    resumes_count/unread_negotiations/streak. Политика ошибок:
    fallback-статусы (0/401/403/5xx) на ЛЮБОМ источнике — MobileAPIError
    наверх (вызов целиком повторяется через web-flow); прочие не-2xx
    (404 и т.п.) — log_debug, источник пропускается (нули/пустой dict),
    исключение НЕ кидается.
    """
    result: dict = {
        "views": 0, "views_new": 0, "shows": 0,
        "invitations": 0, "invitations_new": 0,
        "next_touch_seconds": 0, "free_touches": 0,
        "global_invitations": 0, "new_invitations_total": 0,
        # mobile-добавки (нет в web-версии):
        "resumes_count": 0, "unread_negotiations": 0, "streak": {},
    }

    # 1. Основной источник — counters профиля.
    try:
        me = mobile_request(acc, "GET", "/me",
                            params={"with_user_statuses": "true"})
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            # 0 (сеть) / 401 / 403 / 5xx: не глотим — fallback-обёртка
            # повторит вызов через web-flow.
            raise
        log_debug(f"mobile fetch_stats /me: HTTP {e.status_code} | "
                  f"{e.payload} — counters остаются нулями")
        me = None
    if isinstance(me, dict):
        counters = me.get("counters") or {}
        result["views_new"] = _as_int(counters.get("new_resume_views"))
        result["unread_negotiations"] = _as_int(counters.get("unread_negotiations"))
        result["resumes_count"] = _as_int(counters.get("resumes_count"))

    # 2. Статистика конкретного резюме (total_views за всё время +
    # new_views; последние берём как max(counters /me, new_views резюме)).
    rid = resolve_resume_id(acc, resume_id)
    if rid:
        try:
            resume = mobile_request(acc, "GET", f"/resumes/{rid}")
        except MobileAPIError as e:
            if is_fallback_status(e.status_code):
                raise
            log_debug(f"mobile fetch_stats /resumes/{rid}: HTTP "
                      f"{e.status_code} | {e.payload} — пропускаю")
            resume = None
        if isinstance(resume, dict):
            result["views"] = _as_int(resume.get("total_views"))
            result["views_new"] = max(result["views_new"],
                                      _as_int(resume.get("new_views")))
    else:
        log_debug("mobile fetch_stats: резюме не зарезолвлено — "
                  "пропускаю GET /resumes/{id}")

    # 3. Streak-геймификация откликов.
    try:
        stat = mobile_request(acc, "GET", "/negotiations_statistic/mine")
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            raise
        log_debug(f"mobile fetch_stats /negotiations_statistic/mine: HTTP "
                  f"{e.status_code} | {e.payload} — streak остаётся пустым")
        stat = None
    if isinstance(stat, dict):
        applicant_stat = stat.get("applicant_statistic") or {}
        streak_raw = (applicant_stat.get("responses_streak")
                      if isinstance(applicant_stat, dict) else None)
        if isinstance(streak_raw, dict):
            result["streak"] = {
                "responses_count": _as_int(streak_raw.get("responses_count")),
                "responses_required": _as_int(streak_raw.get("responses_required")),
            }
    return result
