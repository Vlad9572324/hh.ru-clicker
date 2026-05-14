"""
Account-level CRUD and action routes.
"""

import asyncio
import json
import re
import threading
import time

import requests
from fastapi import APIRouter, Request

from app.logging_utils import log_debug, _is_login_page
from app.config import accounts_data, save_accounts
from app.storage import save_browser_sessions
from app.oauth import (
    _obtain_oauth_token, _oauth_touch_resume,
    _oauth_tokens, _oauth_lock,
)
from app.llm import generate_llm_questionnaire_answers
from app.questionnaire import get_questionnaire_answer, _parse_questionnaire_rich
from app.hh_resume import (
    fetch_resume_text, fetch_resume_stats, fetch_resume_view_history,
    _analyze_resume, parse_hh_lux_ssr, _edit_resume_field,
    _resume_cache,
)
from app.hh_negotiations import auto_decline_discards
from app.state import AccountState
from app.config import CONFIG
from app.instances import bot


router = APIRouter()


# ============================================================
# COOKIE PARSING HELPERS (shared with sessions.py)
# ============================================================

# Auth cookies нужные для откликов (без трекинговых с + и =)
_AUTH_COOKIE_KEYS = {
    "hhtoken", "_xsrf", "hhul", "crypted_id", "iap.uid",
    "hhrole", "regions", "GMT", "hhuid", "crypted_hhuid",
}


def _parse_cookies_str(raw: str) -> tuple:
    """
    Парсит cURL-запрос, 'Cookie: ...' или просто 'key=val; key2=val2'.
    Возвращает (cookies_dict, raw_cookie_line).
    """
    raw = raw.strip()
    raw_line = ""

    raw = raw.encode().decode('unicode_escape', errors='replace') if '\\u00' in raw else raw

    if raw.startswith("curl "):
        m = re.search(r"-H\s+['\"](?:C|c)ookie:\s*([^'\"]+)['\"]", raw, re.DOTALL)
        if not m:
            m = re.search(r"-b\s+\$?['\"]([^'\"]+)['\"]", raw, re.DOTALL)
        if not m:
            m = re.search(r"--cookie\s+['\"]([^'\"]+)['\"]", raw, re.DOTALL)
        if m:
            raw_line = m.group(1).strip()
        else:
            return {}, ""
    elif raw.lower().startswith("cookie:"):
        raw_line = raw[7:].strip()
    else:
        raw_line = raw

    cookies: dict = {}
    for part in raw_line.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()

    return cookies, raw_line


# ============================================================
# ACCOUNT TOGGLES
# ============================================================

@router.post("/api/account/{idx}/pause")
async def api_account_pause(idx: int):
    bot.toggle_account_pause(idx)
    if 0 <= idx < len(bot.account_states):
        paused = bot.account_states[idx].paused
    else:
        temp_idx = idx - len(bot.account_states)
        s = bot.temp_states.get(temp_idx)
        paused = s.paused if s else False
    return {"paused": paused}


@router.post("/api/account/{idx}/llm_toggle")
async def api_account_llm_toggle(idx: int):
    bot.toggle_account_llm(idx)
    if 0 <= idx < len(bot.account_states):
        enabled = bot.account_states[idx].llm_enabled
    else:
        temp_idx = idx - len(bot.account_states)
        s = bot.temp_states.get(temp_idx)
        enabled = s.llm_enabled if s else True
    return {"llm_enabled": enabled}


@router.post("/api/account/{idx}/resume_touch")
async def api_resume_touch(idx: int):
    bot.trigger_resume_touch(idx)
    return {"ok": True}


@router.post("/api/account/{idx}/resume_touch_toggle")
async def api_resume_touch_toggle(idx: int):
    enabled = bot.toggle_resume_touch(idx)
    return {"ok": True, "enabled": enabled}


@router.post("/api/account/{idx}/set_urls")
async def api_set_urls(idx: int, request: Request):
    """Обновить список поисковых URL аккаунта и индивидуальную глубину поиска."""
    body = await request.json()
    urls = [u.strip() for u in body.get("urls", []) if u.strip()]
    url_pages = {}
    for k, v in body.get("url_pages", {}).items():
        try:
            url_pages[k] = int(v) if v else 0
        except (ValueError, TypeError):
            pass
    if 0 <= idx < len(bot.account_states):
        bot.account_states[idx].acc["urls"] = urls
        bot.account_states[idx].acc["url_pages"] = url_pages
        bot.account_states[idx].total_urls = len(urls)
        if 0 <= idx < len(accounts_data):
            accounts_data[idx]["urls"] = urls
            accounts_data[idx]["url_pages"] = url_pages
            save_accounts()
        return {"ok": True, "count": len(urls)}
    return {"ok": False, "error": "Аккаунт не найден"}


@router.post("/api/account/{idx}/set_letter")
async def api_set_letter(idx: int, request: Request):
    """Обновить письмо аккаунта в памяти."""
    body = await request.json()
    letter = body.get("letter", "")
    if 0 <= idx < len(bot.account_states):
        bot.account_states[idx].acc["letter"] = letter
        if 0 <= idx < len(accounts_data):
            accounts_data[idx]["letter"] = letter
            save_accounts()
        return {"ok": True}
    temp_idx = idx - len(bot.account_states)
    if 0 <= temp_idx < len(bot.temp_sessions):
        bot.temp_sessions[temp_idx]["letter"] = letter
        if temp_idx in bot.temp_states:
            bot.temp_states[temp_idx].acc["letter"] = letter
        save_browser_sessions(bot.temp_sessions)
        return {"ok": True}
    return {"ok": False, "error": "Аккаунт не найден"}


@router.post("/api/account/{idx}/update_cookies")
async def api_update_cookies(idx: int, body: dict):
    """Обновить куки аккаунта в памяти без перезапуска."""
    raw = body.get("cookies", "").strip()
    if not raw:
        return {"ok": False, "error": "Строка cookies пустая"}

    cookies, raw_line = _parse_cookies_str(raw)

    if not cookies:
        return {"ok": False, "error": "Не удалось распознать cookies — вставьте cURL или строку cookie: ..."}
    if "hhtoken" not in cookies:
        return {"ok": False, "error": "Не найден hhtoken"}
    if "_xsrf" not in cookies:
        return {"ok": False, "error": "Не найден _xsrf"}

    if 0 <= idx < len(bot.account_states):
        state = bot.account_states[idx]
        auth_cookies = {k: v for k, v in cookies.items() if k in _AUTH_COOKIE_KEYS}
        state.acc["cookies"] = auth_cookies
        state.acc["_raw_cookie_line"] = raw_line
        state.cookies_expired = False
        if 0 <= idx < len(accounts_data):
            accounts_data[idx]["cookies"] = auth_cookies
            save_accounts()
        log_debug(f"update_cookies [{state.name}]: обновлены куки ({len(auth_cookies)} ключей)")
        return {"ok": True, "name": state.name, "keys": list(auth_cookies.keys())}

    temp_idx = idx - len(bot.account_states)
    if 0 <= temp_idx < len(bot.temp_sessions):
        auth_cookies = {k: v for k, v in cookies.items() if k in _AUTH_COOKIE_KEYS}
        bot.temp_sessions[temp_idx]["cookies"] = auth_cookies
        bot.temp_sessions[temp_idx]["_raw_cookie_line"] = raw_line
        if temp_idx in bot.temp_states:
            bot.temp_states[temp_idx].acc["cookies"] = auth_cookies
            bot.temp_states[temp_idx].cookies_expired = False
        save_browser_sessions(bot.temp_sessions)
        name = bot.temp_sessions[temp_idx].get("name", f"Браузер #{temp_idx+1}")
        log_debug(f"update_cookies [temp {temp_idx}] {name}: обновлены куки ({len(auth_cookies)} ключей)")
        return {"ok": True, "name": name, "keys": list(auth_cookies.keys())}

    return {"ok": False, "error": "Аккаунт не найден"}


@router.post("/api/account/{idx}/profile")
async def api_account_profile(idx: int, request: Request):
    """Обновить профиль основного аккаунта (name, short, color, resume_hash)."""
    body = await request.json()
    if not (0 <= idx < len(accounts_data)):
        return {"ok": False, "error": "Аккаунт не найден"}
    acc = accounts_data[idx]
    for field in ("name", "short", "color", "resume_hash"):
        if field in body and isinstance(body[field], str) and body[field].strip():
            acc[field] = body[field].strip()
    if 0 <= idx < len(bot.account_states):
        state = bot.account_states[idx]
        state.name = acc.get("name", state.name)
        state.short = acc.get("short", state.short)
        state.color = acc.get("color", state.color)
    save_accounts()
    return {"ok": True}


@router.post("/api/accounts/add")
async def api_account_add(request: Request):
    """Добавить новый основной аккаунт."""
    body = await request.json()
    name = body.get("name", "").strip()
    short = body.get("short", "").strip()
    color = body.get("color", "cyan").strip()
    resume_hash = body.get("resume_hash", "").strip()
    cookies_str = body.get("cookies", "").strip()
    letter = body.get("letter", "").strip()

    if not name or not resume_hash or not cookies_str:
        return {"ok": False, "error": "Требуются: name, resume_hash, cookies"}

    cookies, _ = _parse_cookies_str(cookies_str)
    if not cookies or "hhtoken" not in cookies:
        return {"ok": False, "error": "Не удалось распознать cookies (нужен hhtoken)"}

    auth_cookies = {k: v for k, v in cookies.items() if k in _AUTH_COOKIE_KEYS}
    acc = {
        "name": name,
        "short": short or (name.split()[0] if name.split() else name),
        "color": color,
        "resume_hash": resume_hash,
        "letter": letter,
        "cookies": auth_cookies,
        "urls": [],
    }
    accounts_data.append(acc)
    save_accounts()

    state = AccountState(acc)
    bot.account_states.append(state)
    new_idx = len(bot.account_states) - 1
    for target in (bot._run_account_worker, bot._fetch_hh_stats_worker):
        threading.Thread(target=target, args=(new_idx, state), daemon=True).start()

    return {"ok": True, "idx": new_idx, "name": name}


@router.delete("/api/account/{idx}/delete")
async def api_account_delete(idx: int):
    """Удалить основной аккаунт."""
    if not (0 <= idx < len(accounts_data)):
        return {"ok": False, "error": "Аккаунт не найден"}

    if 0 <= idx < len(bot.account_states):
        bot.account_states[idx]._deleted = True

    name = accounts_data[idx].get("name", f"#{idx}")

    if 0 <= idx < len(bot.account_states):
        bot.account_states.pop(idx)
    accounts_data.pop(idx)

    save_accounts()
    bot._add_log("", "", f"\U0001f5d1️ Аккаунт удалён: {name}", "info")
    return {"ok": True}


@router.post("/api/account/{idx}/apply_tests")
async def api_apply_tests(idx: int):
    """Переключить флаг apply_tests для аккаунта/сессии."""
    base = len(bot.account_states)
    if idx < base:
        state = bot.account_states[idx]
        state.apply_tests = not state.apply_tests
        accounts_data[idx]["apply_tests"] = state.apply_tests
        save_accounts()
        return {"ok": True, "apply_tests": state.apply_tests}
    ti = idx - base
    state = bot.temp_states.get(ti)
    if state:
        state.apply_tests = not state.apply_tests
        if 0 <= ti < len(bot.temp_sessions):
            bot.temp_sessions[ti]["apply_tests"] = state.apply_tests
            save_browser_sessions(bot.temp_sessions)
        return {"ok": True, "apply_tests": state.apply_tests}
    return {"ok": False, "error": "Аккаунт не найден"}


@router.get("/api/account/{idx}/resume_text")
async def api_resume_text(idx: int):
    """Получить и вернуть текстовое представление резюме (для проверки)."""
    s = None
    if 0 <= idx < len(bot.account_states):
        s = bot.account_states[idx]
    else:
        temp_idx = idx - len(bot.account_states)
        s = bot.temp_states.get(temp_idx)
    if not s:
        return {"ok": False, "error": "Invalid idx"}
    rh = s.acc.get("resume_hash", "")
    _resume_cache.pop(rh, None)
    text = await asyncio.get_event_loop().run_in_executor(None, fetch_resume_text, s.acc)
    return {"ok": True, "resume_hash": rh, "length": len(text), "text": text}


@router.get("/api/account/{idx}/resume_views")
async def api_resume_views(idx: int):
    """История просмотров резюме для аккаунта"""
    s = None
    if 0 <= idx < len(bot.account_states):
        s = bot.account_states[idx]
    else:
        temp_idx = idx - len(bot.account_states)
        s = bot.temp_states.get(temp_idx)
    if s:
        if not s.resume_view_history:
            loop = asyncio.get_event_loop()
            s.resume_view_history = await loop.run_in_executor(
                None, fetch_resume_view_history, s.acc, 100
            )
        if not s.resume_views_7d:
            loop = asyncio.get_event_loop()
            rs = await loop.run_in_executor(None, fetch_resume_stats, s.acc)
            s.resume_views_7d = rs["views"]
            s.resume_views_new = rs["views_new"]
            s.resume_shows_7d = rs["shows"]
            s.resume_invitations_7d = rs["invitations"]
            s.resume_invitations_new = rs["invitations_new"]
            s.resume_next_touch_seconds = rs["next_touch_seconds"]
            s.resume_free_touches = rs["free_touches"]
            s.resume_global_invitations = rs["global_invitations"]
            s.resume_new_invitations_total = rs["new_invitations_total"]
        return {
            "history": s.resume_view_history,
            "stats": {
                "views_7d": s.resume_views_7d,
                "views_new": s.resume_views_new,
                "shows_7d": s.resume_shows_7d,
                "invitations_7d": s.resume_invitations_7d,
                "invitations_new": s.resume_invitations_new,
                "global_invitations": s.resume_global_invitations,
                "new_invitations_total": s.resume_new_invitations_total,
                "next_touch_seconds": s.resume_next_touch_seconds,
                "free_touches": s.resume_free_touches,
            }
        }
    return {"error": "Invalid idx"}


@router.post("/api/account/{idx}/oauth_token")
async def api_oauth_token(idx: int):
    """Get/refresh OAuth token for account."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    loop = asyncio.get_event_loop()
    token = await loop.run_in_executor(None, _obtain_oauth_token, acc)
    if token:
        rh = acc.get("resume_hash", "")
        with _oauth_lock:
            info = _oauth_tokens.get(rh, {})
        return {
            "ok": True,
            "token_prefix": token[:20] + "...",
            "expires_in": int(info.get("expires_at", 0) - time.time()),
            "has_refresh": bool(info.get("refresh_token")),
        }
    return {"ok": False, "error": "Failed to obtain token"}


@router.get("/api/account/{idx}/oauth_status")
async def api_oauth_status(idx: int):
    """Check OAuth token status."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"error": "Invalid idx"}
    rh = acc.get("resume_hash", "")
    with _oauth_lock:
        info = _oauth_tokens.get(rh, {})
    if info:
        remaining = int(info.get("expires_at", 0) - time.time())
        return {
            "has_token": True,
            "token_prefix": info.get("access_token", "")[:20] + "...",
            "expires_in_hours": round(remaining / 3600, 1),
            "has_refresh": bool(info.get("refresh_token")),
        }
    return {"has_token": False}


@router.post("/api/account/{idx}/oauth_touch")
async def api_oauth_touch(idx: int):
    """Touch/publish resume via OAuth API (no captcha)."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    loop = asyncio.get_event_loop()
    ok, msg = await loop.run_in_executor(None, _oauth_touch_resume, acc)
    return {"ok": ok, "message": msg}


@router.get("/api/account/{idx}/test_llm_questionnaire")
async def api_test_llm_questionnaire(idx: int, vacancy_id: str = ""):
    """Test LLM questionnaire answering without submitting."""
    if not vacancy_id:
        return {"error": "vacancy_id required"}
    acc = bot._get_apply_acc(idx)
    if not acc:
        return {"error": "Invalid idx"}
    def _do():
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        r = requests.get(
            f"https://hh.ru/applicant/vacancy_response?vacancyId={vacancy_id}&withoutTest=no",
            headers={"User-Agent": ua, "Accept": "text/html"},
            cookies=acc.get("cookies", {}), timeout=15)
        rich = _parse_questionnaire_rich(r.text)
        resume_text = fetch_resume_text(acc) if CONFIG.llm_use_resume else ""
        answers = generate_llm_questionnaire_answers(rich, f"Vacancy {vacancy_id}", "", resume_text)
        result = []
        for q in rich:
            llm_ans = answers.get(q["field"], "")
            result.append({
                "field": q["field"], "type": q["type"], "text": q["text"],
                "options": q.get("options", []),
                "llm_answer": llm_ans,
                "template_answer": get_questionnaire_answer(q["text"]),
            })
        return {"questions": result, "llm_answered": len(answers), "total": len(rich),
                "llm_enabled": CONFIG.llm_enabled, "profiles": len(CONFIG.llm_profiles or [])}
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do)


@router.get("/api/account/{idx}/resume_audit")
async def api_resume_audit(idx: int, extra_terms: str = ""):
    """Аудит резюме — анализ видимости для HR."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"error": "Invalid idx"}
    extra = [t.strip() for t in (extra_terms or "").split(",") if t.strip()] if extra_terms else []
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _analyze_resume, acc, extra)


@router.get("/api/account/{idx}/hot_leads")
async def api_hot_leads(idx: int):
    """Possible job offers — горячие лиды, работодатели готовые пригласить."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"error": "Invalid idx"}
    try:
        r = requests.get(
            "https://hh.ru/shards/applicant/negotiations/possible_job_offers",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "X-Xsrftoken": acc.get("cookies", {}).get("_xsrf", ""),
                "Referer": "https://hh.ru/applicant/negotiations",
            },
            cookies=acc.get("cookies", {}), timeout=15,
        )
        if r.status_code != 200:
            return {"offers": [], "error": f"HTTP {r.status_code}"}
        d = r.json()
        offers = []
        for o in d.get("possibleJobOffers", []):
            offers.append({
                "employer": o.get("name", "?"),
                "employer_id": o.get("employerId"),
                "vacancies": o.get("vacancyNames", []),
                "vacancy_id": o.get("vacancyId", ""),
                "has_invitation": o.get("hasInvitationTopic", False),
                "topic_ids": o.get("topicIds", []),
            })
        return {"offers": offers, "total": len(offers)}
    except Exception as e:
        return {"offers": [], "error": str(e)}


@router.get("/api/account/{idx}/remindable")
async def api_remindable(idx: int):
    """Return negotiations where responseReminderState.allowed is True (can send reminder)."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"error": "Invalid idx"}
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    try:
        r = requests.get(
            "https://hh.ru/applicant/negotiations",
            headers={"User-Agent": ua, "Accept": "text/html,application/xhtml+xml"},
            cookies=acc.get("cookies", {}), timeout=15,
        )
        if r.status_code != 200 or _is_login_page(r.text):
            return {"error": "auth_error", "remindable": []}
        ssr = parse_hh_lux_ssr(r.text)
        topic_list = ssr.get("topicList", [])
        remindable = []
        for topic in (topic_list if isinstance(topic_list, list) else []):
            if not isinstance(topic, dict):
                continue
            rrs = topic.get("responseReminderState", {})
            if isinstance(rrs, dict) and rrs.get("allowed"):
                employer = ""
                vacancy = ""
                chat_id = topic.get("chatId", "")
                topic_id = topic.get("topicId", "")
                v_info = topic.get("vacancy", {})
                if isinstance(v_info, dict):
                    vacancy = v_info.get("name", "")
                    emp = v_info.get("company", v_info.get("employer", {}))
                    if isinstance(emp, dict):
                        employer = emp.get("name", "")
                    elif isinstance(emp, str):
                        employer = emp
                remindable.append({
                    "chat_id": str(chat_id),
                    "topic_id": str(topic_id),
                    "employer": employer,
                    "vacancy": vacancy,
                })
        return {"remindable": remindable, "total": len(remindable)}
    except Exception as e:
        return {"error": str(e), "remindable": []}


@router.post("/api/account/{idx}/clone_resume")
async def api_clone_resume(idx: int, request: Request):
    """Clone resume and optionally set title. Body: {title?: "new title"}"""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    try:
        body = await request.json()
    except Exception:
        body = {}
    new_title = body.get("title", "")
    resume_hash = acc.get("resume_hash", "")
    if not resume_hash:
        return {"ok": False, "error": "No resume_hash"}
    xsrf = acc.get("cookies", {}).get("_xsrf", "")
    try:
        r = requests.post(
            "https://hh.ru/applicant/resumes/clone",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "X-Xsrftoken": xsrf,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://hh.ru",
                "Referer": "https://hh.ru/applicant/resumes",
            },
            cookies=acc.get("cookies", {}),
            data=f"resume={resume_hash}&_xsrf={xsrf}",
            timeout=15,
        )
        if r.status_code == 200:
            d = r.json()
            new_url = d.get("url", "")
            new_hash = ""
            m = re.search(r'resume=([a-f0-9]+)', new_url)
            if m:
                new_hash = m.group(1)
            if not new_hash:
                return {"ok": True, "new_hash": "", "message": "Склонировано, но hash не получен"}

            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            r_orig = requests.get(f"https://hh.ru/resume/{resume_hash}",
                headers={"User-Agent": ua, "Accept": "text/html"},
                cookies=acc.get("cookies", {}), timeout=15)
            orig_data = {}
            m_ssr = re.search(r'<template[^>]*id="HH-Lux-InitialState"[^>]*>([\s\S]*?)</template>', r_orig.text)
            if m_ssr:
                orig_data = json.loads(m_ssr.group(1)).get("applicantResume", {})

            fields = {}
            if new_title:
                fields["title"] = [{"string": new_title}]
            for copy_field in ("experience", "primaryEducation", "skills", "employment",
                               "workSchedule", "workFormats", "businessTripReadiness",
                               "relocation", "travelTime"):
                val = orig_data.get(copy_field, [])
                if val:
                    fields[copy_field] = val
            if not orig_data.get("salary"):
                fields["salary"] = [{"amount": 100000, "currency": "RUR"}]
            if not any(s.get("string") == "remote" for s in orig_data.get("workSchedule", [])):
                ws = list(orig_data.get("workSchedule", []))
                ws.append({"string": "remote"})
                fields["workSchedule"] = ws
            if not any(s.get("string") == "REMOTE" for s in orig_data.get("workFormats", [])):
                wf = list(orig_data.get("workFormats", []))
                wf.append({"string": "REMOTE"})
                fields["workFormats"] = wf

            edited_count = 0
            for field_name, field_data in fields.items():
                res = _edit_resume_field(acc, new_hash, {field_name: field_data})
                if res.get("ok"):
                    edited_count += 1

            return {
                "ok": True,
                "new_hash": new_hash,
                "edit_url": f"https://hh.ru/resume/edit/{new_hash}/position",
                "fields_copied": edited_count,
                "message": f"Полный клон создан! {edited_count} полей скопировано. Осталось опубликовать на hh.ru",
            }
        else:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/account/{idx}/edit_resume")
async def api_edit_resume(idx: int, request: Request):
    """Edit resume fields via API. Body: {resume_hash, title, salary, skills, professionalRole}"""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "bad json"}

    resume_hash = body.get("resume_hash") or acc.get("resume_hash", "")
    if not resume_hash:
        return {"ok": False, "error": "No resume_hash"}

    fields = {}
    if "title" in body and body["title"]:
        fields["title"] = [{"string": body["title"]}]
    if "salary" in body:
        try:
            sal = int(body["salary"])
            if sal > 0:
                fields["salary"] = [{"amount": sal, "currency": body.get("currency", "RUR")}]
            else:
                fields["salary"] = []
        except (ValueError, TypeError):
            pass
    if "skills" in body and body["skills"]:
        fields["skills"] = [{"string": body["skills"]}]
    if "professionalRole" in body:
        try:
            fields["professionalRole"] = [{"string": int(body["professionalRole"])}]
        except (ValueError, TypeError):
            pass

    if not fields:
        return {"ok": False, "error": "No fields to update"}

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _edit_resume_field, acc, resume_hash, fields)
    return result


@router.get("/api/account/{idx}/all_resumes")
async def api_all_resumes(idx: int):
    """List all resumes for this account (including clones). Uses HTML page for full data."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"error": "Invalid idx"}
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    try:
        r = requests.get(
            "https://hh.ru/applicant/resumes",
            headers={"User-Agent": ua, "Accept": "text/html", "Referer": "https://hh.ru/"},
            cookies=acc.get("cookies", {}), timeout=15,
        )
        if r.status_code != 200:
            return {"resumes": [], "error": f"HTTP {r.status_code}"}
        ssr = parse_hh_lux_ssr(r.text)
        ssr_resumes = ssr.get("applicantResumes", [])
        stats = ssr.get("applicantResumesStatistics", {}).get("resumes", {})

        resumes = []
        for res in ssr_resumes:
            attrs = res.get("_attributes", {})
            rid = str(attrs.get("id", ""))
            rhash = attrs.get("hash", "")
            title_list = res.get("title", [])
            title = title_list[0].get("string", "") if title_list and isinstance(title_list[0], dict) else ""
            percent = attrs.get("percent", 0)
            rs = stats.get(rid, {}).get("statistics", {})
            resumes.append({
                "hash": rhash,
                "title": title or "(без заголовка)",
                "status": attrs.get("status", ""),
                "percent": percent,
                "is_searchable": attrs.get("isSearchable", False),
                "can_publish": attrs.get("canPublishOrUpdate", False),
                "updated": attrs.get("updated"),
                "skills_count": len(res.get("keySkills", [])),
                "experience_count": len(res.get("experience", [])),
                "views_7d": (rs.get("views") or {}).get("count", 0),
                "shows_7d": (rs.get("searchShows") or {}).get("count", 0),
                "edit_url": f"https://hh.ru/resume/edit/{rhash}/position",
            })
        return {"resumes": resumes, "total": len(resumes)}
    except Exception as e:
        return {"resumes": [], "error": str(e)}


@router.post("/api/account/{idx}/decline_discards")
async def api_decline_discards(idx: int):
    """Авто-отклонение дискардов в переговорах"""
    if 0 <= idx < len(bot.account_states):
        acc = bot.account_states[idx].acc

        def do_decline():
            return auto_decline_discards(acc)

        count = await asyncio.get_event_loop().run_in_executor(None, do_decline)
        bot._add_log(
            bot.account_states[idx].short,
            bot.account_states[idx].color,
            f"\U0001f5d1️ Отклонено дискардов: {count}",
            "info",
        )
        return {"declined": count}
    return {"error": "Invalid idx"}


@router.get("/api/negotiations/{idx}")
async def api_negotiations(idx: int):
    s = None
    if 0 <= idx < len(bot.account_states):
        s = bot.account_states[idx]
    else:
        temp_idx = idx - len(bot.account_states)
        s = bot.temp_states.get(temp_idx)
    if s:
        return {
            "interviews": s.hh_interviews,
            "viewed": s.hh_viewed,
            "not_viewed": s.hh_not_viewed,
            "discards": s.hh_discards,
            "interviews_list": s.hh_interviews_list,
            "possible_offers": s.hh_possible_offers,
            "updated": s.hh_stats_updated.isoformat() if s.hh_stats_updated else None,
        }
    return {"error": "Invalid idx"}
