"""Observed per-search/apply-cycle results, independent of lifetime counters.

processed = sent + skipped + errors + unknown; already is part of skipped.
Pending questionnaires and untouched candidates are not processed. A processed
unknown outcome never means permission to submit the application again.
"""
from collections import Counter
from contextlib import nullcontext
from datetime import datetime, timezone
from uuid import uuid4


SKIP_REASONS = {
    "not_it": "Специализация вне ИТ",
    "not_remote": "Нет удалённого формата",
    "scope_unknown": "ИТ или удалёнка не подтверждены",
    "vacancy_outside_scope": "Не входит в выбранные локационные форматы",
    "location_unknown": "Локация не подтверждена",
    "local_country_unset": "Не указана локальная страна",
    "local_country_mismatch": "Локация не совпадает с локальной страной",
    "outside_relocation_region": "Локация вне региона релокации",
    "not_relocation": "Удалённая вакансия не относится к релокации",
    "already": "Отклик уже существует",
    "hh_blacklist": "В чёрном списке HH",
    "missing_title": "Нет данных о названии вакансии",
    "archived": "Вакансия в архиве",
    "hh_warning": "Предупреждение HH о вакансии",
    "redirect": "Вакансия перенаправляет на другую",
    "title_include": "Не соответствует нужным словам в названии",
    "title_exclude": "Исключающие слова в названии",
    "previous_rejection": "HH отмечает предыдущий отказ",
    "degraded_form": "Анкета недоступна в текущем режиме",
    "auto_response": "Исключён автоматический отклик HH",
    "accreditation": "Нет требуемой ИТ-аккредитации",
    "employer_rating": "Рейтинг работодателя ниже настройки",
    "recommendations": "Доля рекомендаций ниже настройки",
    "questionnaire_disabled": "Анкеты и тесты отключены",
    "outcome_unknown": "Неподтверждённый отклик — повтор заблокирован",
    "schedule": "Не подходит формат работы",
    "salary": "Зарплата ниже настройки или не указана",
    "preflight": "Не пройдена проверка перед откликом",
    "fresh_reserve": "Отложено из-за резерва для свежих вакансий",
    "cancelled": "Действие отменено до отправки",
    "hh_limit": "HH сообщил о лимите",
    "questionnaire_incomplete": "Анкета не завершена",
    "other": "Другой явно учтённый пропуск",
}


def _lock(state, locked=False):
    return nullcontext() if locked else getattr(state, "_state_lock", nullcontext())


def begin_cycle(state, *, now=None):
    with _lock(state):
        state._cycle_report = {"cycle_id": uuid4().hex,
            "started_at": (now or datetime.now(timezone.utc)).isoformat(),
            "finished_at": None, "status": "running", "found_raw": None,
            "found_unique": None, "operation_errors": 0, "partial": False}
        state._cycle_universe = None
        state._cycle_considered = set()
        state._cycle_outcomes = {}
        state._cycle_questionnaires = set()


def found_cycle(state, vacancy_ids, raw_count):
    with _lock(state):
        report = getattr(state, "_cycle_report", None)
        if report is None:
            return
        state._cycle_universe = {str(vid) for vid in vacancy_ids}
        report["found_unique"] = len(state._cycle_universe)
        report["found_raw"] = raw_count if type(raw_count) is int and raw_count >= 0 else None
        if raw_count is None:
            report["partial"] = True


def consider_cycle(state, vacancy_id):
    with _lock(state):
        if getattr(state, "_cycle_report", None) is not None and str(vacancy_id) in (state._cycle_universe or ()):
            state._cycle_considered.add(str(vacancy_id))


def cycle_outcome(state, vacancy_id, outcome, reason=None, *, locked=False):
    if outcome not in ("sent", "already", "skipped", "error", "unknown"):
        raise ValueError("unsupported cycle outcome")
    with _lock(state, locked):
        if getattr(state, "_cycle_report", None) is None:
            return
        vid = str(vacancy_id)
        if vid not in (state._cycle_universe or ()):
            return  # Manual/out-of-cycle activity must not enter these counters.
        previous = state._cycle_outcomes.get(vid)
        if previous and (previous[0] == "sent" or
                (previous[0] == "already" and outcome != "sent")):
            return  # Weaker/late duplicate diagnostics cannot undo a receipt.
        state._cycle_considered.add(vid)
        state._cycle_questionnaires.discard(vid)
        safe_reason = reason if reason in SKIP_REASONS else "other"
        state._cycle_outcomes[vid] = (outcome, "already" if outcome == "already" else safe_reason)


def questionnaire_cycle(state, vacancy_id):
    with _lock(state):
        vid = str(vacancy_id)
        if (getattr(state, "_cycle_report", None) is not None
                and vid in (state._cycle_universe or ()) and vid not in state._cycle_outcomes):
            state._cycle_considered.add(vid)
            state._cycle_questionnaires.add(vid)


def cycle_operation_error(state):
    """A failed source/worker operation is not a failed application."""
    with _lock(state):
        report = getattr(state, "_cycle_report", None)
        if report is not None and report["status"] == "running":
            report["operation_errors"] += 1
            report["partial"] = True


def finish_cycle(state, status="waiting", *, now=None):
    if status not in ("waiting", "blocked", "error"):
        raise ValueError("unsupported cycle status")
    with _lock(state):
        report = getattr(state, "_cycle_report", None)
        if report is not None and report["finished_at"] is None:
            report["status"] = status
            report["finished_at"] = (now or datetime.now(timezone.utc)).isoformat()


def resolve_cycle_unknown(state, vacancy_id, receipt_created_at, *, locked=False):
    with _lock(state, locked):
        report = getattr(state, "_cycle_report", None)
        vid = str(vacancy_id)
        if report is None or state._cycle_outcomes.get(vid, (None,))[0] != "unknown":
            return
        # A receipt predating this cycle proves "already", not a new cycle send.
        current_cycle_receipt = False
        try:
            stamp = datetime.fromisoformat(str(receipt_created_at).replace("Z", "+00:00"))
            start = datetime.fromisoformat(report["started_at"])
            current_cycle_receipt = stamp.tzinfo is not None and start <= stamp <= datetime.now(timezone.utc)
        except (ValueError, TypeError):
            pass
        cycle_outcome(state, vid, "sent" if current_cycle_receipt else "already", locked=True)


def cycle_snapshot(state, *, blocked=False):
    with _lock(state):
        report = getattr(state, "_cycle_report", None)
        if report is None:
            return None
        result = dict(report)
        counts = Counter(kind for kind, reason in state._cycle_outcomes.values())
        reasons = Counter(reason for kind, reason in state._cycle_outcomes.values() if kind in ("skipped", "already"))
        processed = len(state._cycle_outcomes)
        remaining = None if report["found_unique"] is None else max(0, report["found_unique"] - processed)
        result.update(considered=len(state._cycle_considered), processed=processed,
            sent=counts["sent"], already=counts["already"], skipped=counts["skipped"] + counts["already"],
            errors=counts["error"], unknown=counts["unknown"],
            questionnaires_pending=len(state._cycle_questionnaires), remaining=remaining,
            skip_reasons=[{"key": key, "label": SKIP_REASONS[key], "count": reasons[key]}
                          for key in SKIP_REASONS if reasons[key]])
        result["partial"] = bool(result["partial"] or remaining is None or remaining > 0
                                 or result["unknown"] or result["questionnaires_pending"])
        if blocked and result["status"] == "running":
            result["status"] = "blocked"
        return result
