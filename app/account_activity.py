"""Account activity presentation only: no I/O, scheduling or mutation decisions."""
from contextlib import nullcontext
from datetime import datetime, timezone


def aware_iso(value):
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if value.tzinfo is None:
                return None  # Persisted strings without a zone are not evidence.
        if not isinstance(value, datetime):
            return None
        # Existing worker deadlines are local naive datetime values.
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (ValueError, TypeError, OverflowError):
        return None


def initial_activity():
    return {"phase": "idle", "current": "Ожидает начала рабочего цикла",
            "next": "Проверит состояние аккаунта и начнёт поиск вакансий",
            "started_at": aware_iso(datetime.now(timezone.utc)), "wait_until": None,
            "progress": None, "requires_action": False}


def set_activity(state, phase, current, next_step, *, progress=None, wait_until=None, now=None, operation=None):
    """Called at real worker transitions. Snapshot reads never reset clocks."""
    at = aware_iso(now or datetime.now(timezone.utc))
    deadline = aware_iso(wait_until)
    if progress is not None:
        done, total = progress
        if type(done) is not int or type(total) is not int or not 0 <= done <= total:
            raise ValueError("invalid activity progress")
        progress = {"done": done, "total": total}
    with getattr(state, "_state_lock", nullcontext()):
        previous = getattr(state, "activity", {})
        identity = (phase, current, next_step, deadline, operation)
        previous_identity = tuple(previous.get(key) for key in ("phase", "current", "next", "wait_until")) + (getattr(state, "_activity_operation", None),)
        state.activity = {"phase": phase, "current": current, "next": next_step,
                          "started_at": previous.get("started_at") if identity == previous_identity else at,
                          "wait_until": deadline, "progress": progress, "requires_action": False}
        state._activity_operation = operation  # Internal identity, never exported.
        if phase not in ("apply", "questionnaire", "preflight"):
            # These legacy UI fields are current work, not last-success labels.
            state.current_vacancy_id = ""
            state.current_vacancy_title = ""
            state.current_vacancy_company = ""


def note_pause(state):
    """Record a real pause transition when its state is persisted, not polled."""
    key = (bool(state.paused), state.paused_reason, bool(state.hard_stopped), bool(state.limit_exceeded))
    if getattr(state, "_activity_pause_key", None) != key:
        state._activity_pause_key = key
        state._activity_control_revision = getattr(state, "_activity_control_revision", 0) + 1
        state.activity_pause_started_at = aware_iso(datetime.now(timezone.utc))


def activity_view(state, *, global_paused=False, stopped=False, global_started_at=None):
    """Truthful priority overlays; never reuse a previous vacancy or raw error."""
    with getattr(state, "_state_lock", nullcontext()):
        activity = dict(getattr(state, "activity", {}) or {})
        if isinstance(activity.get("progress"), dict):
            activity["progress"] = dict(activity["progress"])
        pending = bool(getattr(state, "pending_apply", None))
        pending_since = aware_iso((getattr(state, "pending_apply", None) or {}).get("recorded_at"))
        held = getattr(state, "pending_apply", None) or {}
        attempts = held.get("reconcile_attempts")
        next_check = aware_iso(held.get("reconcile_next_at"))
        last_error = held.get("reconcile_last_error")
        recovery_storage_failed = bool(getattr(state, "_reconcile_persistence_failed", False))
        reason = getattr(state, "paused_reason", "")
        paused = bool(getattr(state, "paused", False))
        deleted = bool(getattr(state, "_deleted", False))
        hard_limit = bool(getattr(state, "hard_stopped", False))
        limit = bool(getattr(state, "limit_exceeded", False))
        limit_at = getattr(state, "limit_reset_time", None)
        started = getattr(state, "activity_pause_started_at", None)
        receipt_at = getattr(state, "receipt_check_started_at", None)
        auth_check_at = aware_iso(getattr(state, "auth_check_started_at", None))
        auth_recovery_pending = bool(getattr(state, "_auth_recovery_pending", False))
        network_recovery = dict(getattr(state, "network_recovery", None) or {})
        network_storage_failed = bool(getattr(state, "_network_recovery_persistence_failed", False))
    def overlay(phase, current, next_step, action=True, wait_until=None, since=started):
        return {"phase": phase, "current": current, "next": next_step,
                "started_at": aware_iso(since), "wait_until": aware_iso(wait_until),
                "progress": None, "requires_action": action}
    if stopped or deleted:
        if pending or reason == "outcome_unknown":
            return overlay("stopped", "Бот остановлен. Исход отклика не подтверждён",
                           "Запустите аккаунт для сверки в HH. Повторная отправка заблокирована", since=None)
        return overlay("stopped", "Новые действия остановлены",
                       "Уже начатый запрос может завершиться. Для продолжения запустите бота", since=None)
    if pending or reason == "outcome_unknown":
        if receipt_at:
            return overlay("receipt_check", "Сверяет результат отклика в HH; отправки заблокированы",
                           "После ответа подтвердит результат или сохранит защитную паузу",
                           action=False, since=receipt_at)
        if global_paused:
            return overlay("outcome_unknown", "Исход отклика неизвестен; включена общая пауза",
                           "Автосверка ждёт снятия общей паузы. Можно проверить результат вручную",
                           since=pending_since or started)
        if paused and reason != "outcome_unknown":
            return overlay("outcome_unknown", "Исход отклика неизвестен; действует другая пауза аккаунта",
                           "Нажмите ручную проверку результата в HH; автоматическая сверка приостановлена",
                           since=pending_since or started)
        if recovery_storage_failed:
            return overlay("outcome_unknown", "Исход отклика неизвестен; автосверка остановлена",
                           "Не удалось сохранить состояние проверки. Проверьте хранилище; не повторяйте отклик",
                           since=pending_since or started)
        if last_error == "auth":
            return overlay("outcome_unknown", "HH не подтвердил авторизацию для сверки отклика",
                           "Восстановите вход в HH и проверьте результат вручную. Автосверки остановлены",
                           since=pending_since or started)
        if last_error == "rate_limit":
            return overlay("outcome_unknown", "HH ограничил запросы проверки результата отклика",
                           "Автосверки остановлены. Дождитесь снятия ограничения HH, затем проверьте вручную",
                           since=pending_since or started)
        network_problem = {
            "connect_timeout": "Нет соединения с HH через настроенный прокси; исход отклика неизвестен",
            "read_timeout": "HH не ответил вовремя; исход отклика неизвестен",
        }.get(last_error) if isinstance(last_error, str) else None
        if type(attempts) is int and 0 <= attempts < 3 and next_check:
            return overlay("outcome_unknown", network_problem or "Отклики приостановлены: результат пока не подтверждён",
                           f"Автоматически сверит результат в HH, проверка {attempts + 1}/3. Повторной отправки не будет",
                           action=False, wait_until=next_check, since=pending_since or started)
        if type(attempts) is int and attempts >= 3:
            return overlay("outcome_unknown", network_problem or "Лимит автосверок исчерпан; результат не подтверждён",
                           "Автосверки исчерпаны. Восстановите соединение и проверьте результат вручную; не повторяйте отклик"
                           if network_problem else "Нужна ручная проверка результата в HH. Повторная отправка остаётся заблокированной",
                           since=pending_since or started)
        return overlay("outcome_unknown", "Исход отклика неизвестен — отправки приостановлены",
                       "Нажмите проверку результата в HH. Не отправляйте отклик повторно",
                       since=pending_since or started)
    if reason == "message_outcome_unknown":
        return overlay(reason, "Исход сообщения неизвестен — автоматизация приостановлена",
                       "Проверьте чат HH перед продолжением. Не повторяйте сообщение")
    if auth_check_at and ((paused and reason in ("auth", "network_error")) or auth_recovery_pending):
        return overlay("auth_check", "Проверяет вход в HH и доступ к веб-анкете; отправки приостановлены",
                       "Снимет только паузу авторизации после успешной проверки; остальные ограничения сохранятся",
                       action=False, since=auth_check_at)
    if paused and reason == "auth":
        return overlay("auth", "Не удалось подтвердить авторизацию HH",
                       "Восстановите вход в аккаунт, затем продолжите работу")
    if paused and reason == "network_error":
        next_probe = aware_iso(network_recovery.get("next_check_at"))
        last_error = network_recovery.get("last_error")
        if global_paused:
            return overlay("network_error", "Сетевая пауза и общая пауза: новые действия не запускаются",
                           "Снимите общую паузу для проверки соединения; отклики пока не отправляются")
        if hard_limit or limit:
            return overlay("network_error", "Сетевая пауза: также действует лимит откликов",
                           "Проверки соединения приостановлены до снятия ограничения", action=False)
        if network_storage_failed:
            return overlay("network_error", "Проверки соединения остановлены: состояние не удалось сохранить",
                           "Проверьте локальное хранилище и состояние аккаунта; отправки остаются на паузе")
        stopped_reason = {
            "auth": "HH не подтвердил авторизацию; автоматические проверки остановлены",
            "challenge": "HH ограничил доступ к веб-анкетам; автоматические проверки остановлены",
            "rate_limit": "HH ограничил частоту запросов; автоматические проверки остановлены",
            "unavailable": "Причина сбоя не подтверждена как сетевая; автоматические проверки остановлены",
            "stale": "Данные аккаунта изменились; автоматические проверки остановлены",
        }.get(last_error) if isinstance(last_error, str) else None
        if stopped_reason:
            return overlay("network_error", stopped_reason,
                           "Проверьте вход и ограничения HH вручную. Автоматической повторной отправки не было")
        if next_probe:
            return overlay("network_recovery", "Подготовка веб-анкеты прервана сетевым сбоем; отклики на паузе",
                           "Проверит вход и доступ к веб-анкетам без отправки отклика; продолжит только после подтверждения",
                           action=False, wait_until=next_probe)
        return overlay("network_error", "Сетевая пауза: автоматическая проверка не запланирована",
                       "Проверьте соединение и вход в HH вручную; отправки остаются на паузе")
    if paused and reason == "hh_rate_limit":
        return overlay("hh_rate_limit", "HH ограничил запросы к анкете; автоматические попытки остановлены",
                       "Дождитесь снятия ограничения HH. Это не суточный лимит откликов; потребуется ручная проверка")
    if paused and reason == "challenge":
        return overlay("challenge", "HH требует ручную проверку доступа",
                       "Откройте проверку HH в карточке аккаунта. Автоматические отправки остановлены")
    if hard_limit or limit or (paused and reason == "limit"):
        if global_paused:
            return overlay("limit", "Действует лимит откликов и общая пауза",
                           "Снимите общую паузу. Продолжение возможно только после проверки лимита HH")
        if paused and reason == "manual":
            return overlay("limit", "Действует лимит откликов и ручная пауза аккаунта",
                           "Дождитесь снятия лимита и снимите ручную паузу")
        if paused and reason == "auto_errors":
            return overlay("limit", "Действует лимит и защитная пауза после ошибок",
                           "Проверьте подключение и продолжите работу; лимит должен быть снят отдельно")
        # A check deadline is not a guaranteed reset or permission to send.
        if activity.get("phase") == "limit_check" and not paused and not global_paused:
            return activity
        check_at = limit_at if not hard_limit and not paused and not global_paused else None
        return overlay("limit", "Отправки остановлены из-за лимита",
                       "Проверит доступность откликов в HH; время снятия ограничения неизвестно",
                       action=False, wait_until=check_at)
    if paused and reason == "auto_errors":
        return overlay("auto_errors", "Защитная пауза после нескольких ошибок",
                       "Проверьте подключение и нажмите продолжение, когда причина устранена")
    if global_paused:
        return overlay("global_pause", "Общая пауза: новые действия не запускаются",
                       "Снимите общую паузу; защита отдельных аккаунтов останется включённой",
                       since=global_started_at)
    if paused:
        return overlay("manual_pause", "Пауза аккаунта: новые действия не запускаются",
                       "Нажмите продолжение, чтобы возобновить рабочий цикл")
    if activity:
        return activity
    # Older/restored objects have no observable stage timestamp.
    return overlay("idle", "Ожидает рабочего цикла", "Проверит состояние аккаунта и поиск вакансий",
                   action=False, since=None)
