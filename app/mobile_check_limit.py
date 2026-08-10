"""Mobile-версия проверки дневного лимита откликов (Phase 3).

GET https://api.hh.ru/negotiations_statistic/mine — mobile-endpoint
streak-статистики откликов (probe'нут в app/oauth.py::
fetch_negotiations_statistic, работает через web OAuth-token). Из
applicant_statistic.responses_streak берутся responses_count (сколько
откликов сделано за период) и responses_required (сколько требуется).

Важно: это ЭВРИСТИКА по streak-статистике, а не суточный лимит откликов
в явном виде. Если данных нет (2xx без streak, мусорные значения, прочие
не-2xx) — отклики НЕ блокируются: жёсткий лимит всё равно enforcement'ится
сервером в POST /negotiations (ошибка limit_exceeded).

Транспорт — app.hh_mobile_transport.mobile_request (Bearer + mobile UA +
x-force-app-access; без последних двух заголовков endpoint отдаёт 406 —
см. комментарий в app/oauth.py::fetch_negotiations_statistic).
Fallback-политика: статусы 0 (сеть) / 401 / 403 / 5xx НЕ глотаются —
MobileAPIError перекидывается наверх, чтобы fallback-обёртка повторила
проверку через web-flow (web hh_apply.check_limit); прочие не-2xx →
can_apply True (не блокируем).
"""

from app.hh_mobile_transport import (
    MobileAPIError,
    is_fallback_status,
    mobile_request,
)
from app.logging_utils import log_debug


def _no_data() -> dict:
    """Данных о лимите нет — не блокируем отклики (жёсткий лимит
    enforcement'ится сервером в POST /negotiations → limit_exceeded)."""
    return {"applied_today": None, "limit": None, "can_apply": True}


def _to_int(value):
    """Защитное приведение к int: числа и числовые строки → int;
    мусор (None, нечисловые строки, bool) → None."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def check_limit(acc: dict) -> dict:
    """Дневной лимит откликов по mobile streak-статистике api.hh.ru.

    GET https://api.hh.ru/negotiations_statistic/mine → парсится
    applicant_statistic.responses_streak.{responses_count,
    responses_required} (полный payload может содержать и другие ключи —
    берём только streak, парсим защитно). Возвращает
    {"applied_today": int|None, "limit": int|None, "can_apply": bool}.

    can_apply=False ТОЛЬКО если оба числа распознаны, limit > 0 и
    applied >= limit. Это эвристика по streak-статистике: при отсутствии
    данных (2xx с пустым телом/без streak, мусорные значения, прочие
    не-2xx кроме fallback-статусов) возвращаем can_apply=True — отклики
    не блокируем, жёсткий лимит всё равно enforcement'ится сервером в
    POST /negotiations (limit_exceeded).

    Fallback-статусы (0 сеть / 401 / 403 / 5xx) перекидываются
    MobileAPIError наверх — fallback-обёртка повторит проверку через
    web-flow (web hh_apply.check_limit).
    """
    try:
        data = mobile_request(acc, "GET", "/negotiations_statistic/mine")
    except MobileAPIError as e:
        if is_fallback_status(e.status_code):
            # Не глотим: fallback-обёртка повторит через web-flow.
            raise
        log_debug(f"mobile check_limit: HTTP {e.status_code} | {e.payload} "
                  f"— не блокирую отклики")
        return _no_data()

    stat = data.get("applicant_statistic") if isinstance(data, dict) else None
    streak = stat.get("responses_streak") if isinstance(stat, dict) else None
    if not isinstance(streak, dict):
        log_debug("mobile check_limit: нет responses_streak в ответе "
                  "— не блокирую отклики")
        return _no_data()

    applied = _to_int(streak.get("responses_count"))
    limit = _to_int(streak.get("responses_required"))
    can_apply = not (applied is not None and limit is not None
                     and limit > 0 and applied >= limit)
    log_debug(f"mobile check_limit: applied={applied} limit={limit} "
              f"can_apply={can_apply}")
    return {"applied_today": applied, "limit": limit, "can_apply": can_apply}
