"""
Manual vacancy apply flow (two-step: check + submit).
"""

import asyncio
import json
import re
from datetime import datetime, timezone

import aiohttp
from fastapi import APIRouter
from glom import glom

from app.logging_utils import _is_login_page
from app.config import hh_base
from app.storage import add_applied
from app.hh_api import get_headers
from app.hh_client_factory import get_client
from app.hh_client_fallback import FallbackHHClient
from app.questionnaire import get_questionnaire_answer, _parse_questionnaire_rich
from app.instances import bot
from app.user_agent import webview_user_agent
from app.hh_apply import _aio_egress_kwargs, classify_apply_response
from app.mutation_safety import ensure_mutation_allowed, MutationBlocked
from app.mobile_questionnaire import oauth_web_account


router = APIRouter()


async def _fetch_questionnaire_data(acc: dict, vid: str) -> dict:
    """
    Получает форму опросника и возвращает список вопросов с полями.
    НЕ отправляет отклик.
    """
    headers = {
        "User-Agent": webview_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": f"{hh_base()}/vacancy/{vid}",
    }
    url_form = f"{hh_base()}/applicant/vacancy_response?vacancyId={vid}&withoutTest=no"
    sess_kw, req_kw = _aio_egress_kwargs()
    async with aiohttp.ClientSession(cookies=acc["cookies"], headers=headers, **sess_kw) as session:
        async with session.get(url_form, timeout=aiohttp.ClientTimeout(total=15), **req_kw) as r:
            html = await r.text()
            if r.status in (401, 403) or _is_login_page(html):
                return {"questions": [], "hidden": {}, "error": "auth"}

    hidden = dict(re.findall(r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html))
    hidden.update(dict(re.findall(r'<input[^>]+name="([^"]+)"[^>]+type="hidden"[^>]+value="([^"]*)"', html)))

    # Reuse the canonical BeautifulSoup parser.  The former route-local regex
    # parser had drifted: radio labels were looked up by value instead of id,
    # and select fields were silently omitted.
    questions = _parse_questionnaire_rich(html)
    negative_words = ("нет", "no", "не готов", "не готова", "не могу")
    for question in questions:
        answer = get_questionnaire_answer(question.get("text", ""))
        options = question.get("options") or []
        qtype = question.get("type")
        if qtype == "textarea":
            question["suggested"] = answer
        elif qtype == "radio":
            values = [option["value"] for option in options]
            chosen = values[0] if values else ""
            if any(word in answer.lower() for word in negative_words) and len(values) > 1:
                chosen = values[1]
            question["suggested"] = chosen
        elif qtype == "checkbox":
            # A checkbox group is multi-valued all the way through the UI and
            # multipart encoder.  Default conservatively to its first option.
            question["suggested"] = [options[0]["value"]] if options else []
        elif qtype == "select":
            chosen = options[0]["value"] if options else ""
            answer_lower = answer.lower()
            for option in options:
                if option.get("label", "").lower() in answer_lower:
                    chosen = option["value"]
                    break
            question["suggested"] = chosen

    return {"questions": questions, "hidden": hidden, "url_form": url_form}


async def _web_acc_for_form(acc: dict) -> dict:
    """Use OAuth autologin cookies for WebView-only forms without persisting them."""
    if str(acc.get("mode") or "").strip().lower() == "oauth":
        return await oauth_web_account(acc)
    return acc


def _result_to_response(result: str, info: dict, vid: str,
                        questions: list = None, letter: str = "") -> dict:
    """
    Чистый маппинг tuple (result, info) из client.submit_response() в ответ
    /api/apply/submit. Без I/O и bookkeeping — unit-тестируемо.

    Для result="test" вопросы/letter передаёт вызывающий: их сбор требует
    async-запроса (_fetch_questionnaire_data) и в чистую функцию не входит.
    """
    if result == "sent":
        return {"status": "sent", "vacancy_id": vid, "message": "Отклик успешно отправлен ✅"}
    if result == "unknown":
        return {"status": "unknown", "vacancy_id": vid, "message": "Результат не подтверждён. Проверьте отклик в HH перед повторной отправкой."}
    if result == "cancelled":
        return {"status": "cancelled", "vacancy_id": vid, "message": "Отправка отменена: аккаунт остановлен или на паузе."}
    if result == "limit":
        return {"status": "limit", "vacancy_id": vid, "message": "Достигнут дневной лимит откликов"}
    if result == "already":
        return {"status": "already", "vacancy_id": vid, "message": "Отклик на эту вакансию уже был отправлен"}
    if result == "test":
        questions = questions if questions is not None else []
        return {
            "status": "test_required",
            "vacancy_id": vid,
            "questions": questions,
            "letter": letter,
            "message": f"Вакансия требует опрос ({len(questions)} вопросов)",
        }
    if result == "auth_error":
        return {"status": "error", "vacancy_id": vid, "message": "⚠️ Куки протухли — обновите в настройках"}
    # "error" и любые неизвестные result'ы
    message = str(info.get("error_type") or info.get("exception") or info.get("raw") or "Ошибка отклика")
    return {"status": "error", "vacancy_id": vid, "message": message}


async def _mobile_submit_response(acc_idx: int, acc: dict, vid: str, client) -> dict:
    """
    Отклик БЕЗ анкеты через HHClient-фабрику (mobile-ветка /api/apply/submit).

    client.submit_response() — async-метод, поэтому await'ится НАПРЯМУЮ:
    run_in_executor неприменим к корутинам (осознанное отклонение от паттерна
    routes/debug.py, где sync-методы клиента гоняются в executor'е).

    Bookkeeping повторяет success-ветку web-flow, КРОМЕ state.questionnaire_sent
    (анкеты не было). result="test" → добираем вопросы существующим
    _fetch_questionnaire_data, чтобы UI перезапустил check/submit с ответами.
    """
    try:
        result, info = await client.submit_response(vid)
    except MutationBlocked:
        return _result_to_response("cancelled", {}, vid)
    except Exception as exc:
        if getattr(exc, "outcome_unknown", False):
            return _hold_unknown(acc_idx, vid)
        raise
    if result == "unknown":
        return _hold_unknown(acc_idx, vid)

    if result == "sent":
        state = bot._get_apply_state(acc_idx)
        if state:
            state.sent += 1
            # state.questionnaire_sent НЕ инкрементируем — анкеты не было
        add_applied(acc["name"], vid)
        short = state.short if state else acc.get("name", "?")
        color = state.color if state else ""
        bot._add_log(short, color, f"\U0001f4dd Ручной отклик (mobile): {vid}", "success")

    questions = None
    if result == "test":
        qdata = await _fetch_questionnaire_data(await _web_acc_for_form(acc), vid)
        questions = qdata["questions"]

    return _result_to_response(result, info, vid, questions=questions, letter=acc["letter"])


def _hold_unknown(acc_idx: int, vid: str) -> dict:
    state = bot._get_apply_state(acc_idx)
    if state is not None:
        acc = state.acc
        bot.hold_pending_apply(
            state, vid, str(acc.get("_pinned_resume_id") or acc.get("resume_hash") or ""),
            reason_code="unconfirmed_response",
        )
    return _result_to_response("unknown", {}, vid)


@router.post("/api/account/{idx}/reconcile-application")
async def api_reconcile_application(idx: int):
    """Verify a held application with fresh GETs; never submit it again.

    POST is required because a confirmed receipt updates local bookkeeping and
    may release this account's protective pause. The existing API-key middleware
    protects the action, just like the pause/start controls.
    """
    from app.apply_confirmation import confirm_application_receipt, receipt_check_failure_reason

    state = bot._get_apply_state(idx)
    if state is None:
        return {"ok": False, "message": "Аккаунт не найден"}
    with state._state_lock:
        pending = dict(getattr(state, "pending_apply", None) or {})
        acc = {**state.acc, "cookies": dict(state.acc.get("cookies") or {})}
        expected_account = {"resume_hash": acc.get("resume_hash"),
                            "user_id": acc.get("user_id"), "cookies": acc["cookies"].copy()}
    vid = str(pending.get("vacancy_id") or "")
    resume_id = str(pending.get("resume_id") or "")
    if not vid or not resume_id:
        return {"ok": False, "message": "Нет сохранённого отклика для сверки"}
    # This ID comes from our persisted attempt, never from a caller's request.
    # An automatically selected resume can differ from the active search resume.
    acc["_pinned_resume_id"] = resume_id
    with state._state_lock:
        if getattr(state, "receipt_check_started_at", None):
            return {"ok": False, "busy": True,
                    "message": "Сверка с HH уже идёт. Дождитесь её результата."}
        if dict(getattr(state, "pending_apply", None) or {}) != pending:
            return {"ok": False, "message": "Отклик для сверки изменился. Обновите карточку."}
        check_started_at = datetime.now(timezone.utc).isoformat()
        state.receipt_check_started_at = check_started_at

    # A disconnected HTTP client does not cancel requests.get in its thread.
    # Keep the activity and busy guard until that actual read finishes, but do
    # not apply its result after the caller has cancelled this action.
    def read_receipt():
        # Read the diagnostic in the same thread as the helper's GET.
        receipt = confirm_application_receipt(acc, vid, resume_id)
        reason = receipt_check_failure_reason()
        if not isinstance(reason, str) or reason not in (
                "connect_timeout", "read_timeout", "auth", "rate_limit", "unconfirmed"):
            reason = "unconfirmed"
        return receipt, reason

    check_task = asyncio.create_task(asyncio.to_thread(read_receipt))
    state._receipt_check_task = check_task
    caller_active = True

    def clear_check():
        with state._state_lock:
            if getattr(state, "_receipt_check_task", None) is check_task:
                state.receipt_check_started_at = None
                state._receipt_check_task = None

    def finished(done):
        if not done.cancelled():
            done.exception()  # Retrieve errors even when the HTTP caller left.
        if not caller_active:
            clear_check()

    check_task.add_done_callback(finished)
    try:
        try:
            receipt, failure_reason = await asyncio.shield(check_task)
        except Exception:
            # Do not expose raw HTTP exceptions (proxy credentials, session data).
            receipt = None
            failure_reason = "unconfirmed"
        if not receipt or receipt.get("receipt_confirmed") is not True:
            bot.record_receipt_failure(idx, failure_reason, expected_state=state,
                expected_pending=pending, expected_account=expected_account)
            explanation = {
                "connect_timeout": "Нет соединения с HH через настроенный прокси.",
                "read_timeout": "HH не ответил на проверку вовремя.",
                "auth": "Для сверки требуется восстановить авторизацию HH.",
                "rate_limit": "HH временно ограничил проверки. Не повторяйте запрос сейчас.",
            }.get(failure_reason, "HH пока не подтвердил отклик.")
            return {
                "ok": False, "confirmed": False, "paused": bool(state.paused),
                "message": explanation + " Пауза сохранена; повторной отправки не было.",
            }
        resolved = bot.confirm_pending_apply(
            idx, vid, resume_id, str(receipt.get("negotiation_id") or ""),
            receipt_created_at=str(receipt.get("receipt_created_at") or ""),
            expected_state=state, expected_pending=pending, expected_account=expected_account,
        )
        if not resolved:
            return {"ok": False, "confirmed": True,
                    "message": "Состояние аккаунта изменилось во время сверки. Обновите карточку."}
        with state._state_lock:
            paused = bool(state.paused)
            remaining = bool(getattr(state, "pending_apply", None))
        return {
            "ok": True, "confirmed": True, "paused": paused, "pending": remaining,
            "message": ("Отклик подтверждён. Есть ещё отклик для сверки." if remaining else
                        "Отклик подтверждён. Защитная пауза снята; общая пауза и лимиты сохранены."),
        }
    finally:
        caller_active = False
        # Hold the shared guard through local commit, not merely through GET.
        # Cancellation leaves it held until the actual blocking read finishes.
        if check_task.done():
            clear_check()


@router.post("/api/account/{idx}/protective/continue")
async def api_account_protective_continue(idx: int, body: dict):
    if not isinstance(body, dict) or body.get("confirmed") is not True or not isinstance(body.get("reason"), str):
        return {"ok": False, "error": "Подтвердите, что проверили состояние в HH"}
    ok, message = await asyncio.to_thread(bot.confirm_protective_resume, idx, body["reason"])
    return {"ok": ok, ("message" if ok else "error"): message}


@router.post("/api/account/{idx}/recheck-auth")
async def api_recheck_auth(idx: int):
    """Fresh OAuth + WebView GET proof, followed by a guarded local resume.

    No password/OTP login, token refresh or vacancy submission is performed.
    The temporary WebView cookies are discarded. This local POST is API-key
    protected because success releases an existing pause.
    """
    from app.auth_verification import verify_oauth_and_web_access, _failure

    def rejected(reason):
        return {"ok": False, "paused": True, **_failure(reason)}

    state = bot._get_apply_state(idx)
    if state is None:
        return {"ok": False, "verified": False, "reason": "not_applicable",
                "message": "Аккаунт не найден. Обновите список."}
    with state._state_lock:
        if (getattr(state, "auth_check_started_at", None)
                or getattr(state, "receipt_check_started_at", None)
                or getattr(state, "_auth_recovery_pending", False)):
            return {"ok": False, "busy": True,
                    "message": "Проверка HH уже идёт. Дождитесь её результата."}
        recovery_reason = state.paused_reason
        raw_network_recovery = getattr(state, "network_recovery", None)
        network_recovery = dict(raw_network_recovery) if isinstance(raw_network_recovery, dict) else {}
        if (not state.paused or recovery_reason not in ("auth", "network_error")
                or (recovery_reason == "network_error" and not network_recovery)
                or str(state.acc.get("mode") or "").lower() != "oauth"
                or getattr(state, "pending_apply", None)
                or getattr(state, "pending_applies", None)
                or state._deleted or state.hard_stopped or state.limit_exceeded
                or bot.paused or bot._stop_event.is_set()):
            return {"ok": False, "verified": False, "reason": "not_applicable",
                    "paused": bool(state.paused),
                    "message": "Проверка доступна для OAuth-паузы входа или подтверждённого сетевого сбоя без других ограничений. Обновите карточку."}
        acc = {**state.acc, "cookies": dict(state.acc.get("cookies") or {})}
        expected_account = {"resume_hash": acc.get("resume_hash"),
                            "user_id": acc.get("user_id"), "cookies": acc["cookies"].copy()}
        expected_control = bot._limit_check_guard(state)
        state.auth_check_started_at = datetime.now(timezone.utc).isoformat()

    # A disconnected caller cannot cancel the underlying requests thread. Keep
    # the busy marker until it really finishes, and discard an abandoned proof.
    task = asyncio.create_task(asyncio.to_thread(verify_oauth_and_web_access, acc))
    state._auth_check_task = task
    caller_active = True

    def clear_check():
        with state._state_lock:
            if getattr(state, "_auth_check_task", None) is task:
                state.auth_check_started_at = None
                state._auth_check_task = None

    def finished(done):
        if not done.cancelled():
            done.exception()
        if not caller_active:
            clear_check()

    task.add_done_callback(finished)
    try:
        try:
            proof = await asyncio.shield(task)
        except Exception:
            proof = {"verified": False, "reason": "unavailable"}
        if not isinstance(proof, dict) or proof.get("verified") is not True:
            reason = proof.get("reason") if isinstance(proof, dict) else "unavailable"
            reason = _failure(reason)["reason"]
            if recovery_reason == "network_error":
                try:
                    bot.record_network_probe_failure(idx, reason, expected_state=state,
                        expected_account=expected_account, expected_control=expected_control,
                        expected_network_recovery=network_recovery)
                except Exception:
                    pass  # A failed local record is never permission to resume.
            return rejected(reason)
        try:
            network_kwargs = ({"recovery_reason": "network_error",
                               "expected_network_recovery": network_recovery}
                              if recovery_reason == "network_error" else {})
            recovered = bot.recover_verified_auth(idx, expected_state=state,
                expected_account=expected_account, expected_control=expected_control,
                **network_kwargs)
        except Exception:
            return rejected("unavailable")
        if not recovered:
            return rejected("stale")
        return {"ok": True, "verified": True, "paused": False,
                "message": ("Связь с HH, OAuth и доступ к веб-анкетам подтверждены. Сетевая пауза снята."
                            if recovery_reason == "network_error" else
                            "OAuth и вход в веб-анкеты подтверждены. Пауза авторизации снята.")}
    finally:
        caller_active = False
        # Guard covers the local durable commit too, not only network reads.
        if task.done():
            clear_check()


@router.post("/api/apply/check")
async def api_apply_check(body: dict):
    """
    Шаг 1: проверяет вакансию — можно ли откликнуться, требует ли опрос.
    """
    try:
        acc_idx = int(body.get("account_idx", 0))
    except (ValueError, TypeError):
        return {"status": "error", "message": "account_idx must be an integer"}
    raw = body.get("vacancy_id", "").strip()
    m = re.search(r'/vacancy/(\d+)', raw) or re.match(r'^(\d+)$', raw)
    if not m:
        return {"status": "error", "message": "Не удалось определить ID вакансии"}
    vid = m.group(1)

    acc = bot._get_apply_acc(acc_idx)
    if acc is None:
        return {"status": "error", "message": "Неверный аккаунт"}

    # This endpoint really applies: stop before the OAuth autologin round-trips too.
    guard = acc.get("_mutation_guard")
    state = bot._get_apply_state(acc_idx)
    if ((callable(guard) and not guard())
            or (state is not None and (getattr(state, "limit_exceeded", False)
                                       or getattr(state, "hard_stopped", False)))):
        return {"status": "cancelled", "vacancy_id": vid,
                "message": "Отклики сейчас остановлены (пауза, лимит или капча)"}

    custom_letter = body.get("letter", "").strip()
    if custom_letter:
        acc["letter"] = custom_letter

    try:
        acc = await _web_acc_for_form(acc)
    except Exception as exc:
        return {"status": "error", "vacancy_id": vid, "message": f"OAuth autologin: {exc}"}

    sess_kw, req_kw = _aio_egress_kwargs()
    dispatched = False
    try:
        async with aiohttp.ClientSession(
            cookies=acc["cookies"],
            headers=get_headers(acc.get("cookies", {}).get("_xsrf", "")),
            **sess_kw
        ) as session:
            data = aiohttp.FormData()
            for k, v in [("resume_hash", acc["resume_hash"]), ("vacancy_id", vid),
                         ("letter", acc["letter"]), ("lux", "true"), ("ignore_postponed", "true")]:
                data.add_field(k, v)
            ensure_mutation_allowed(acc)
            dispatched = True
            async with session.post(
                hh_base() + "/applicant/vacancy_response/popup",
                data=data, timeout=aiohttp.ClientTimeout(total=10), **req_kw
            ) as r:
                txt = await r.text()
                status_code = r.status

        if status_code in (401, 403) or (status_code == 200 and _is_login_page(txt)):
            return {"status": "error", "vacancy_id": vid, "message": "⚠️ Куки протухли — обновите в настройках"}

        if status_code == 200:
            confirmed_result, confirmed_info = classify_apply_response(status_code, txt)
            if confirmed_result == "unknown":
                return _hold_unknown(acc_idx, vid)
            if confirmed_result != "sent":
                return _result_to_response(confirmed_result, confirmed_info, vid)
            info = {}
            if "shortVacancy" in txt:
                try:
                    p = json.loads(txt)
                    info = {
                        "title": glom(p, "responseStatus.shortVacancy.name", default=""),
                        "company": glom(p, "responseStatus.shortVacancy.company.name", default=""),
                    }
                except Exception:
                    pass
            return {"status": "sent", "vacancy_id": vid, **info,
                    "message": "Отклик уже отправлен (без опроса)"}

        if "negotiations-limit-exceeded" in txt:
            return {"status": "limit", "vacancy_id": vid, "message": "Достигнут дневной лимит откликов"}

        if "alreadyApplied" in txt:
            return {"status": "already", "vacancy_id": vid, "message": "Отклик на эту вакансию уже был отправлен"}

        if "test-required" in txt:
            qdata = await _fetch_questionnaire_data(acc, vid)
            return {
                "status": "test_required",
                "vacancy_id": vid,
                "questions": qdata["questions"],
                "letter": acc["letter"],
                "message": f"Вакансия требует опрос ({len(qdata['questions'])} вопросов)",
            }

        if status_code >= 500:
            return _hold_unknown(acc_idx, vid)
        return {"status": "error", "vacancy_id": vid, "message": f"HTTP {status_code}: {txt[:100]}"}

    except MutationBlocked:
        return _result_to_response("cancelled", {}, vid)
    except Exception as e:
        return _hold_unknown(acc_idx, vid) if dispatched else {"status": "error", "message": str(e)}


@router.post("/api/apply/submit")
async def api_apply_submit(body: dict):
    """
    Шаг 2: отправляет отклик с заполненными ответами на опрос.
    """
    try:
        acc_idx = int(body.get("account_idx", 0))
    except (ValueError, TypeError):
        return {"status": "error", "message": "account_idx must be an integer"}
    vid = str(body.get("vacancy_id", "")).strip()
    letter = body.get("letter", "")
    user_answers = body.get("answers", {})

    acc = bot._get_apply_acc(acc_idx)
    if acc is None:
        return {"status": "error", "message": "Неверный аккаунт"}
    if letter:
        acc = {**acc, "letter": letter}

    # Phase 3: mobile-ветка — отклик БЕЗ анкеты через HHClient-фабрику.
    # Маркер mobile-режима: isinstance(client, FallbackHHClient) — фабрика
    # возвращает её только при mode="mobile" (выбрано перед
    # getattr(client, "mode", "") == "mobile": тип строже duck-typed атрибута).
    # Если user_answers непустой (анкета) или режим web — НИЧЕГО не меняется:
    # анкеты — территория web-flow (официальное приложение тоже ходит в них
    # через webview), поэтому web-form flow ниже сохраняется байт-в-байт.
    client = get_client(acc)
    native_oauth = str(acc.get("mode", "")).strip().lower() == "oauth"
    if (isinstance(client, FallbackHHClient) or native_oauth) and not user_answers:
        try:
            return await _mobile_submit_response(acc_idx, acc, vid, client)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    if native_oauth:
        try:
            acc = await _web_acc_for_form(acc)
        except Exception as exc:
            return {"status": "error", "message": f"OAuth autologin: {exc}"}

    url_form = f"{hh_base()}/applicant/vacancy_response?vacancyId={vid}&withoutTest=no"

    sess_kw, req_kw = _aio_egress_kwargs()
    dispatched = False
    try:
        async with aiohttp.ClientSession(
            cookies=acc["cookies"],
            headers={"User-Agent": webview_user_agent(),
                     "Accept": "text/html,*/*", "Referer": f"{hh_base()}/vacancy/{vid}"},
            **sess_kw
        ) as session:
            async with session.get(url_form, timeout=aiohttp.ClientTimeout(total=15), **req_kw) as r:
                html = await r.text()
                if r.status in (401, 403) or _is_login_page(html):
                    return {"status": "error", "message": "⚠️ Куки протухли — обновите в настройках"}

            hidden = dict(re.findall(r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html))
            hidden.update(dict(re.findall(r'<input[^>]+name="([^"]+)"[^>]+type="hidden"[^>]+value="([^"]*)"', html)))

            form = aiohttp.FormData()
            form.add_field("resume_hash", acc["resume_hash"])
            form.add_field("vacancy_id", vid)
            form.add_field("letter", acc["letter"])
            form.add_field("lux", "true")
            for name in ("_xsrf", "uidPk", "guid", "startTime", "testRequired"):
                if name in hidden:
                    form.add_field(name, hidden[name])
            for name, value in user_answers.items():
                # HH checkbox groups expect repeated fields, not a Python-list
                # string such as "['a', 'b']".
                if isinstance(value, list):
                    for item in value:
                        form.add_field(name, str(item))
                else:
                    form.add_field(name, str(value))

            ensure_mutation_allowed(acc)
            dispatched = True
            async with session.post(
                url_form,
                headers={"X-Xsrftoken": acc.get("cookies", {}).get("_xsrf", ""), "Referer": url_form},
                data=form,
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=False,
                **req_kw
            ) as r2:
                status = r2.status
                location = r2.headers.get("location", "")
                response_text = await r2.text()

        if status in (302, 303):
            if "negotiations-limit-exceeded" in location:
                return {"status": "limit", "message": "Достигнут лимит откликов"}
            if "withoutTest=no" in location or f"vacancyId={vid}" in location:
                return {"status": "error", "message": "Форма не принята — возможно не все вопросы заполнены"}
            return _hold_unknown(acc_idx, vid)

        result, info = classify_apply_response(status, response_text)
        if result == "unknown":
            return _hold_unknown(acc_idx, vid)
        if result == "sent":
            state = bot._get_apply_state(acc_idx)
            if state:
                state.sent += 1
                state.questionnaire_sent += 1
            add_applied(acc["name"], vid)
            short = state.short if state else acc.get("name", "?")
            color = state.color if state else ""
            bot._add_log(short, color, f"\U0001f4dd Ручной отклик (опрос): {vid}", "success")
            return {"status": "sent", "message": "Отклик успешно отправлен ✅"}

        return _result_to_response(result, info, vid)

    except MutationBlocked:
        return _result_to_response("cancelled", {}, vid)
    except Exception as e:
        return _hold_unknown(acc_idx, vid) if dispatched else {"status": "error", "message": str(e)}
