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
from app.config import accounts_data, save_accounts, hh_base
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
    fetch_account_diagnostics, set_job_search_status, _JOB_SEARCH_STATUSES,
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
        # `\$?` — bash $'...' ANSI-C quoting (Firefox Copy-as-cURL для cookies с спецсимволами).
        m = re.search(r"-H\s+\$?['\"](?:C|c)ookie:\s*([^'\"]+)['\"]", raw, re.DOTALL)
        if not m:
            m = re.search(r"-b\s+\$?['\"]([^'\"]+)['\"]", raw, re.DOTALL)
        if not m:
            m = re.search(r"--cookie\s+\$?['\"]([^'\"]+)['\"]", raw, re.DOTALL)
        if m:
            raw_line = m.group(1).strip()
        else:
            return {}, ""
    elif raw.lower().startswith("cookie:"):
        raw_line = raw[7:].strip()
    else:
        raw_line = raw

    # bash $'...' декодирует \NNN (octal), \xNN, \n и т.д. — повторяем то же.
    # Firefox Copy-as-cURL генерит $'...' когда cookie содержит спецсимволы (например ! → \041).
    if "\\" in raw_line:
        try:
            raw_line = raw_line.encode("utf-8").decode("unicode_escape")
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass

    cookies: dict = {}
    for part in raw_line.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            # Stripping NUL и control chars (CRLF) — иначе header injection
            # или requests/http.client крашится навсегда на этой сессии (kimi-search-3 #5,#8).
            k = k.strip()
            v = "".join(ch for ch in v.strip() if ch == "\t" or 0x20 <= ord(ch) < 0x7f or ord(ch) >= 0xa0)
            # Если после strip значение пустое — не добавляем,
            # иначе downstream `hhtoken in cookies` проходит, а реально auth-token нет (r10-1 #4,#9).
            if not v:
                continue
            cookies[k] = v

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


@router.get("/api/account/{idx}/diagnostics")
async def api_account_diagnostics(idx: int):
    """Прогнать диагностику аккаунта: jobSearchStatus, видимость резюме,
    статистика, red flags. Делает один GET на /applicant/resumes — кэширования
    нет, всегда свежие данные.
    """
    acc = bot._get_apply_acc(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    import asyncio as _aio
    data = await _aio.get_event_loop().run_in_executor(None, fetch_account_diagnostics, acc)
    data["ok"] = True
    data["available_statuses"] = _JOB_SEARCH_STATUSES
    return data


@router.post("/api/account/{idx}/job_status")
async def api_set_job_status(idx: int, request: Request):
    """Сменить публичный статус поиска работы.
    Body: {"status": "active_search"}. Допустимые значения см. диагностику.
    """
    acc = bot._get_apply_acc(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "bad json"}
    status = str(body.get("status", "")).strip().lower()
    import asyncio as _aio
    result = await _aio.get_event_loop().run_in_executor(None, set_job_search_status, acc, status)
    if result.get("ok"):
        # лог в боте для аудита
        state = bot._get_apply_state(idx)
        if state:
            bot._add_log(state.short, state.color,
                         f"🟢 Статус поиска работы изменён → {result.get('label','?')}", "success")
    return result


@router.post("/api/account/{idx}/resume_touch_toggle")
async def api_resume_touch_toggle(idx: int):
    enabled = bot.toggle_resume_touch(idx)
    return {"ok": True, "enabled": enabled}


@router.post("/api/account/{idx}/set_urls")
async def api_set_urls(idx: int, request: Request):
    """Обновить список поисковых URL аккаунта (regular или browser-сессия).
    Если idx стал stale (после удаления/рестарта), пробуем найти аккаунт
    по short/name из body — иначе фронт получает «Аккаунт не найден» и
    юзер вынужден жать F5 (GitHub: «не видит URL поиска»)."""
    body = await request.json()
    urls = [u.strip() for u in body.get("urls", []) if u.strip()]
    url_pages = {}
    for k, v in body.get("url_pages", {}).items():
        try:
            url_pages[k] = int(v) if v else 0
        except (ValueError, TypeError):
            pass
    fallback_short = (body.get("short") or "").strip()
    fallback_name = (body.get("name") or "").strip()

    def _apply_regular(i: int) -> dict:
        bot.account_states[i].acc["urls"] = urls
        bot.account_states[i].acc["url_pages"] = url_pages
        bot.account_states[i].total_urls = len(urls)
        if 0 <= i < len(accounts_data):
            accounts_data[i]["urls"] = urls
            accounts_data[i]["url_pages"] = url_pages
            save_accounts()
        return {"ok": True, "count": len(urls), "matched": "regular", "idx": i}

    def _apply_temp(ti: int) -> dict:
        bot.temp_sessions[ti]["urls"] = urls
        bot.temp_sessions[ti]["url_pages"] = url_pages
        if ti in bot.temp_states:
            bot.temp_states[ti].acc["urls"] = urls
            bot.temp_states[ti].acc["url_pages"] = url_pages
            bot.temp_states[ti].total_urls = len(urls)
        save_browser_sessions(bot.temp_sessions)
        return {"ok": True, "count": len(urls), "matched": "temp", "temp_idx": ti}

    # 1. Strict idx match — regular
    if 0 <= idx < len(bot.account_states):
        return _apply_regular(idx)
    # 2. Strict idx match — temp
    temp_idx = idx - len(bot.account_states)
    if 0 <= temp_idx < len(bot.temp_sessions):
        return _apply_temp(temp_idx)
    # 3. Fallback: match by short/name (frontend snapshot was stale after
    #    a deletion or restart — idx no longer aligns but the card belongs
    #    to a real account).
    if fallback_short or fallback_name:
        for i, state in enumerate(bot.account_states):
            acc = state.acc
            if (fallback_short and acc.get("short") == fallback_short) or \
               (fallback_name and acc.get("name") == fallback_name):
                log_debug(f"set_urls: stale idx={idx} → matched regular[{i}] by short/name")
                return _apply_regular(i)
        for ti, ts in enumerate(bot.temp_sessions):
            if (fallback_short and ts.get("short") == fallback_short) or \
               (fallback_name and ts.get("name") == fallback_name):
                log_debug(f"set_urls: stale idx={idx} → matched temp[{ti}] by short/name")
                return _apply_temp(ti)
    return {
        "ok": False,
        "error": "Аккаунт не найден",
        "hint": "Обнови страницу (Ctrl+F5) — индекс карточки устарел.",
    }


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

    final_short = short or (name.split()[0] if name.split() else name)
    # Уникальность short — иначе vacancy_queues пересекаются (kimi-r14-2 #7):
    # два аккаунта с одним short затирают очереди друг друга.
    existing_shorts = {a.get("short", "") for a in accounts_data}
    if final_short in existing_shorts:
        return {"ok": False, "error": f"short='{final_short}' уже используется — выберите уникальное"}

    auth_cookies = {k: v for k, v in cookies.items() if k in _AUTH_COOKIE_KEYS}
    acc = {
        "name": name,
        "short": final_short,
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
    short = accounts_data[idx].get("short", "")
    resume_hash = accounts_data[idx].get("resume_hash", "")

    if 0 <= idx < len(bot.account_states):
        bot.account_states.pop(idx)
    # Чистим связанные структуры — иначе остаются висеть в памяти (swarm-11 #3,#6).
    # vacancy_queues keyed by state.short (manager.py:1053), но раньше pop был по name —
    # очередь оставалась висеть когда name != short (kimi-r14-2 #7).
    if short:
        bot.vacancy_queues.pop(short, None)
    bot.vacancy_queues.pop(name, None)  # backward compat для старых записей
    if resume_hash:
        from app.oauth import invalidate_oauth_token
        invalidate_oauth_token(resume_hash)
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
    return {"ok": False, "error": "Invalid idx"}


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
            # Не отдаём ни одного байта токена наружу — 20 chars Bearer-токена
            # достаточно для подтверждения существования + entropy reduction (swarm-7 #2).
            "expires_in": int(info.get("expires_at", 0) - time.time()),
            "has_refresh": bool(info.get("refresh_token")),
        }
    return {"ok": False, "error": "Failed to obtain token"}


@router.get("/api/account/{idx}/oauth_status")
async def api_oauth_status(idx: int):
    """Check OAuth token status."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    rh = acc.get("resume_hash", "")
    with _oauth_lock:
        info = _oauth_tokens.get(rh, {})
    if info:
        remaining = int(info.get("expires_at", 0) - time.time())
        return {
            "has_token": True,
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
        return {"ok": False, "error": "vacancy_id required"}
    acc = bot._get_apply_acc(idx)
    if not acc:
        return {"ok": False, "error": "Invalid idx"}
    def _do():
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        r = requests.get(
            f"{hh_base()}/applicant/vacancy_response?vacancyId={vacancy_id}&withoutTest=no",
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
        return {"ok": False, "error": "Invalid idx"}
    extra = [t.strip() for t in (extra_terms or "").split(",") if t.strip()] if extra_terms else []
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _analyze_resume, acc, extra)


@router.get("/api/account/{idx}/suggest_urls")
async def api_suggest_urls(idx: int, extra_terms: str = ""):
    """Подсказать URL поисков на основе резюме (title + professionalRole + skills).
    Возвращает [{term, vacancies, seekers, ratio, url}, ...] отсортированный
    по конкуренции (низкая → высокая). Использует кеш аудита если он уже есть.
    Использовать на странице Настройки → Пул URL."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    extra = [t.strip() for t in (extra_terms or "").split(",") if t.strip()] if extra_terms else []
    loop = asyncio.get_event_loop()
    audit = await loop.run_in_executor(None, _analyze_resume, acc, extra)
    if audit.get("error"):
        return {"ok": False, "error": audit["error"]}
    suggestions = []
    import urllib.parse as _up
    resume_hash = acc.get("resume_hash", "")
    for cmp_item in (audit.get("supply_demand_comparison") or []):
        term = cmp_item.get("term", "").strip()
        if not term:
            continue
        # ?text=...&area=1&order_by=publication_time для свежих
        url = (
            f"{hh_base()}/search/vacancy?text={_up.quote(term)}"
            f"&area=1&order_by=publication_time&items_on_page=20"
        )
        suggestions.append({
            "term": term,
            "url": url,
            "vacancies": cmp_item.get("vacancies", 0),
            "ratio": cmp_item.get("ratio", 0),
        })
    # Если есть resume_hash — добавим вариант "По резюме" первым (приоритет).
    if resume_hash:
        url_resume = (
            f"{hh_base()}/search/vacancy?resume={resume_hash}"
            f"&order_by=publication_time&items_on_page=20"
        )
        suggestions.insert(0, {
            "term": f"По резюме «{audit.get('title', '?')}»",
            "url": url_resume,
            "vacancies": audit.get("market", {}).get("vacancy_count", 0),
            "ratio": audit.get("market", {}).get("supply_demand_ratio", 0),
        })
    return {
        "ok": True,
        "resume_title": audit.get("title", ""),
        "resume_hash": resume_hash,
        "suggestions": suggestions,
    }


@router.get("/api/account/{idx}/hot_leads")
async def api_hot_leads(idx: int):
    """Possible job offers — горячие лиды, работодатели готовые пригласить."""
    acc = bot._get_apply_acc(idx)
    if acc is None:
        return {"ok": False, "error": "Invalid idx"}
    try:
        r = requests.get(
            hh_base() + "/shards/applicant/negotiations/possible_job_offers",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "X-Xsrftoken": acc.get("cookies", {}).get("_xsrf", ""),
                "Referer": hh_base() + "/applicant/negotiations",
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
        return {"ok": False, "error": "Invalid idx"}
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    try:
        r = requests.get(
            hh_base() + "/applicant/negotiations",
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
            hh_base() + "/applicant/resumes/clone",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "X-Xsrftoken": xsrf,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://hh.ru",
                "Referer": hh_base() + "/applicant/resumes",
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
            r_orig = requests.get(f"{hh_base()}/resume/{resume_hash}",
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
                "edit_url": f"{hh_base()}/resume/edit/{new_hash}/position",
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
        return {"ok": False, "error": "Invalid idx"}
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    try:
        r = requests.get(
            hh_base() + "/applicant/resumes",
            headers={"User-Agent": ua, "Accept": "text/html", "Referer": hh_base() + "/"},
            cookies=acc.get("cookies", {}), timeout=15,
        )
        if r.status_code in (401, 403) or _is_login_page(r.text):
            return {"resumes": [], "error": "auth_error"}
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
                "edit_url": f"{hh_base()}/resume/edit/{rhash}/position",
            })
        return {"resumes": resumes, "total": len(resumes)}
    except Exception as e:
        return {"resumes": [], "error": str(e)}


# Cache: {url: (timestamp, result)} — TTL 10 min, ограничение размера.
_URL_PREVIEW_CACHE: dict = {}
_URL_PREVIEW_TTL = 600
_URL_PREVIEW_MAX = 200


def _url_preview_compute(url: str, cookies: dict) -> dict:
    """Достать кол-во вакансий + (если возможно) кол-во активных соискателей по URL."""
    import urllib.parse as _up
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    result = {"vacancies": 0, "seekers": 0, "ratio": 0.0}
    try:
        # 1. Vacancies count — фетчим URL как есть, парсим SSR.
        r = requests.get(url, headers={"User-Agent": ua, "Accept": "text/html"},
                         cookies=cookies, timeout=10)
        if r.status_code == 200 and not _is_login_page(r.text):
            from app.hh_resume import parse_hh_lux_ssr
            ssr = parse_hh_lux_ssr(r.text)
            sc = ssr.get("searchCounts", {})
            if isinstance(sc, dict) and sc.get("value"):
                result["vacancies"] = int(sc["value"])
            if not result["vacancies"]:
                m = re.search(r'"found"\s*:\s*(\d+)', r.text[:8000])
                if m:
                    result["vacancies"] = int(m.group(1))

        # 2. Seekers count — только если URL содержит ?text= (для resume= это
        # нельзя посчитать без дополнительной информации о резюме).
        try:
            parsed = _up.urlparse(url)
            qs = dict(_up.parse_qsl(parsed.query))
            text = qs.get("text", "").strip()
            if text and result["vacancies"]:
                r2 = requests.get(
                    f"{hh_base()}/search/applicant?text={_up.quote(text)}&area=1&clusters=true",
                    headers={"User-Agent": ua, "Accept": "application/json,text/html"},
                    cookies=cookies, timeout=10,
                )
                if r2.status_code == 200:
                    try:
                        cj = r2.json()
                    except Exception:
                        cj = {}
                    js_groups = (cj.get("clusters", {}).get("job_search_status", {}) or {}).get("groups", {})
                    for gid, gdata in (js_groups or {}).items():
                        if gid == "active_search" or "актив" in (gdata.get("title", "")).lower():
                            result["seekers"] = int(gdata.get("count", 0))
                            break
        except Exception as e:
            log_debug(f"_url_preview seekers error: {e}")

        if result["vacancies"] > 0 and result["seekers"] > 0:
            result["ratio"] = round(result["seekers"] / result["vacancies"], 1)
    except Exception as e:
        log_debug(f"_url_preview_compute error: {e}")
    return result


@router.get("/api/url_preview")
async def api_url_preview(url: str, idx: int = 0):
    """Возвращает {vacancies, seekers, ratio} для поисковой URL.
    Если URL содержит ?text= — посчитает конкуренцию (как в аудите).
    Без text= — только число вакансий."""
    # Принимаем основной и любые региональные поддомены *.hh.ru/search/
    import re as _re
    if not url or not _re.match(r"^https://(?:[a-z0-9-]+\.)?hh\.ru/search/", url):
        return {"error": "bad url"}
    import time as _t
    import urllib.parse as _up
    now = _t.time()

    # Если URL имеет ?resume=HASH и хеш НЕ принадлежит этому аккаунту —
    # HH вернёт 404, и закешировать 0 нельзя (затрёт работающие результаты
    # у владельца). Возвращаем явный foreign-маркер без кеша.
    try:
        qs_dict = dict(_up.parse_qsl(_up.urlparse(url).query))
        url_resume = qs_dict.get("resume", "").strip()
    except Exception:
        url_resume = ""

    acc = bot._get_apply_acc(idx) if 0 <= idx else None
    cookies = (acc or {}).get("cookies", {}) if acc else {}
    acc_resume = (acc or {}).get("resume_hash", "") if acc else ""
    if url_resume and acc_resume and url_resume != acc_resume:
        return {"vacancies": 0, "seekers": 0, "ratio": 0.0, "foreign_resume": True}

    # Кеш-ключ включает idx, чтобы разные аккаунты не затирали друг друга.
    cache_key = (url, int(idx))
    cached = _URL_PREVIEW_CACHE.get(cache_key)
    if cached and now - cached[0] < _URL_PREVIEW_TTL:
        return {**cached[1], "cached": True}
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _url_preview_compute, url, cookies)
    if len(_URL_PREVIEW_CACHE) > _URL_PREVIEW_MAX:
        oldest = min(_URL_PREVIEW_CACHE.items(), key=lambda kv: kv[1][0])
        _URL_PREVIEW_CACHE.pop(oldest[0], None)
    _URL_PREVIEW_CACHE[cache_key] = (now, data)
    return data


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
    return {"ok": False, "error": "Invalid idx"}


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
    return {"ok": False, "error": "Invalid idx"}
