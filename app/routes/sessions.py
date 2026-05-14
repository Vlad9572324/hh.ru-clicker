"""
Browser session routes (temporary accounts added via cookie paste).
"""

import asyncio

import requests
from fastapi import APIRouter, Request

from app.config import accounts_data
from app.storage import save_browser_sessions
from app.hh_resume import parse_hh_lux_ssr
from app.instances import bot

from app.routes.accounts import _parse_cookies_str, _AUTH_COOKIE_KEYS


router = APIRouter()


def _validate_and_profile(raw_cookie_line: str) -> dict:
    """
    Синхронно проверяет сессию и вытаскивает профиль из SSR.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://hh.ru/",
        "Cookie": raw_cookie_line,
    }
    try:
        r = requests.get(
            "https://hh.ru/applicant/resumes",
            headers=headers,
            
            timeout=15,
            allow_redirects=True,
        )
    except Exception as e:
        return {"ok": False, "error": f"Ошибка сети: {e}"}

    if r.status_code != 200:
        hint = " — возможно, сессия устарела или нужно войти заново" if r.status_code in (401, 403) else ""
        return {"ok": False, "error": f"Сессия невалидна: HTTP {r.status_code}{hint}"}

    ssr = parse_hh_lux_ssr(r.text)

    name = ""
    for path in [
        lambda s: f"{s.get('account',{}).get('firstName','')} {s.get('account',{}).get('lastName','')}".strip(),
        lambda s: f"{s.get('hhidAccount',{}).get('firstName','')} {s.get('hhidAccount',{}).get('lastName','')}".strip(),
        lambda s: s.get("currentUser", {}).get("fullName", ""),
    ]:
        try:
            v = path(ssr)
            if v:
                name = v
                break
        except Exception:
            pass

    all_resumes = []
    for res in ssr.get("applicantResumes", []):
        h = (
            res.get("_attributes", {}).get("hash", "") or
            res.get("resume", {}).get("hash", "") or ""
        )
        title = (
            res.get("_attributes", {}).get("title", "") or
            res.get("title", "") or
            res.get("resume", {}).get("title", "") or ""
        )
        if h:
            all_resumes.append({"hash": h, "title": title or "Резюме"})

    latest = ssr.get("latestResumeHash", "")
    if latest:
        resume_hash = latest
        if not any(r["hash"] == latest for r in all_resumes):
            all_resumes.insert(0, {"hash": latest, "title": "Резюме"})
    elif all_resumes:
        resume_hash = all_resumes[0]["hash"]
    else:
        resume_hash = ""

    return {"ok": True, "name": name or "Браузер", "resume_hash": resume_hash, "all_resumes": all_resumes}


@router.get("/api/sessions")
async def api_sessions():
    """Список браузерных сессий без cookies."""
    base_idx = len(bot.account_states)
    return [
        {
            "idx": base_idx + i,
            "name": s.get("name", f"Браузер #{i+1}"),
            "short": s.get("short", ""),
            "resume_hash": s.get("resume_hash", ""),
            "all_resumes": s.get("all_resumes", []),
            "letter": s.get("letter", ""),
            "temp": True,
            "bot_active": s.get("bot_active", False),
        }
        for i, s in enumerate(bot.temp_sessions)
    ]


@router.post("/api/session/add")
async def api_session_add(body: dict):
    """Добавить временную сессию из браузера по строке cookies."""
    cookie_str = body.get("cookies", "").strip()
    if not cookie_str:
        return {"status": "error", "message": "Строка cookies пустая"}

    cookies, raw_cookie_line = _parse_cookies_str(cookie_str)

    if not cookies or not raw_cookie_line:
        return {"status": "error", "message": "Не удалось распознать cookies — вставьте cURL целиком или строку Cookie: ..."}
    if "hhtoken" not in cookies:
        return {"status": "error", "message": "Не найден hhtoken — вставьте полный cURL (правая кнопка на запросе → Copy as cURL)"}
    if "_xsrf" not in cookies:
        return {"status": "error", "message": "Не найден _xsrf"}

    loop = asyncio.get_event_loop()
    profile = await loop.run_in_executor(None, _validate_and_profile, raw_cookie_line)

    if not profile["ok"]:
        return {"status": "error", "message": profile["error"]}

    display_name = body.get("name", "").strip() or profile["name"]
    all_resumes = profile.get("all_resumes", [])

    selected_hash = body.get("resume_hash", "").strip()
    if selected_hash and any(r["hash"] == selected_hash for r in all_resumes):
        resume_hash = selected_hash
    else:
        resume_hash = profile["resume_hash"]

    letter = body.get("letter", "").strip()
    if not letter:
        for acc in accounts_data:
            if acc.get("resume_hash") == resume_hash:
                letter = acc.get("letter", "")
                break

    auth_cookies = {k: v for k, v in cookies.items() if k in _AUTH_COOKIE_KEYS}

    idx_in_temp = len(bot.temp_sessions)
    temp_acc = {
        "name": f"{display_name} (\U0001f310)",
        "short": f"\U0001f310{display_name.split()[0] if display_name.split() else display_name}",
        "color": "yellow",
        "resume_hash": resume_hash,
        "all_resumes": all_resumes,
        "letter": letter,
        "cookies": auth_cookies,
        "urls": [],
    }
    bot.temp_sessions.append(temp_acc)
    save_browser_sessions(bot.temp_sessions)

    return {
        "status": "ok",
        "message": f"Сессия добавлена: {temp_acc['name']}",
        "idx": len(bot.account_states) + idx_in_temp,
        "name": temp_acc["name"],
        "resume_hash": resume_hash,
    }


@router.patch("/api/session/{idx}")
async def api_session_patch(idx: int, body: dict):
    temp_idx = idx - len(bot.account_states)
    if 0 <= temp_idx < len(bot.temp_sessions):
        ts = bot.temp_sessions[temp_idx]
        if "letter" in body:
            ts["letter"] = body["letter"]
            if temp_idx in bot.temp_states:
                bot.temp_states[temp_idx].acc["letter"] = body["letter"]
        if "resume_hash" in body:
            new_hash = body["resume_hash"]
            ts["resume_hash"] = new_hash
            if temp_idx in bot.temp_states:
                state = bot.temp_states[temp_idx]
                state.acc["resume_hash"] = new_hash
                state.acc["urls"] = bot._build_session_urls(new_hash)
        save_browser_sessions(bot.temp_sessions)
        return {"status": "ok"}
    return {"status": "error", "message": "Не найдено"}


@router.post("/api/session/{idx}/activate")
async def api_session_activate(idx: int):
    """Запустить браузерную сессию как бот-аккаунт."""
    temp_idx = idx - len(bot.account_states)
    if temp_idx < 0 or temp_idx >= len(bot.temp_sessions):
        return {"status": "error", "message": "Не найдено"}
    ts = bot.temp_sessions[temp_idx]
    if not ts.get("resume_hash"):
        return {"status": "error", "message": "Сначала найдите резюме (нажмите \U0001f504)"}
    ok = bot.activate_session(temp_idx)
    if ok:
        return {"status": "ok", "message": f"Сессия {ts['name']} запущена как бот"}
    return {"status": "error", "message": "Не удалось запустить"}


@router.post("/api/session/{idx}/refresh")
async def api_session_refresh(idx: int):
    """Перепрофилировать сессию: обновить имя и resume_hash из HH."""
    temp_idx = idx - len(bot.account_states)
    if temp_idx < 0 or temp_idx >= len(bot.temp_sessions):
        return {"status": "error", "message": "Не найдено"}
    ts = bot.temp_sessions[temp_idx]
    raw_line = ts.get("_raw_cookie_line", "") or "; ".join(f"{k}={v}" for k, v in ts.get("cookies", {}).items())
    loop = asyncio.get_event_loop()
    profile = await loop.run_in_executor(None, _validate_and_profile, raw_line)
    if not profile["ok"]:
        return {"status": "error", "message": profile.get("error", "Ошибка")}
    resume_changed = False
    if profile["resume_hash"]:
        if bot.temp_sessions[temp_idx].get("resume_hash") != profile["resume_hash"]:
            resume_changed = True
        bot.temp_sessions[temp_idx]["resume_hash"] = profile["resume_hash"]
    if profile.get("all_resumes"):
        bot.temp_sessions[temp_idx]["all_resumes"] = profile["all_resumes"]
    if profile["name"] and profile["name"] != "Браузер":
        old_name = ts.get("name", "")
        suffix = " (\U0001f310)" if "(\U0001f310)" in old_name else ""
        bot.temp_sessions[temp_idx]["name"] = profile["name"] + suffix
    # Если сессия уже активна — обновим runtime-копию, иначе воркер
    # продолжит работать со старыми resume_hash/именем/URL'ами.
    active_state = bot.temp_states.get(temp_idx)
    if active_state is not None:
        if profile["resume_hash"]:
            active_state.acc["resume_hash"] = profile["resume_hash"]
            if resume_changed:
                active_state.acc["urls"] = bot._build_session_urls(profile["resume_hash"])
                active_state.total_urls = len(active_state.acc["urls"])
        if profile["name"] and profile["name"] != "Браузер":
            active_state.name = bot.temp_sessions[temp_idx]["name"]
            active_state.acc["name"] = bot.temp_sessions[temp_idx]["name"]
    save_browser_sessions(bot.temp_sessions)
    return {"status": "ok", "resume_hash": profile["resume_hash"], "name": profile["name"]}


@router.delete("/api/session/{idx}")
async def api_session_delete(idx: int):
    temp_idx = idx - len(bot.account_states)
    if 0 <= temp_idx < len(bot.temp_sessions):
        removed = bot.temp_sessions.pop(temp_idx)
        if temp_idx in bot.temp_states:
            bot.temp_states[temp_idx]._deleted = True
        new_temp_states = {}
        for old_i, state in bot.temp_states.items():
            if old_i == temp_idx:
                continue
            new_i = old_i - 1 if old_i > temp_idx else old_i
            new_temp_states[new_i] = state
        bot.temp_states = new_temp_states
        save_browser_sessions(bot.temp_sessions)
        return {"status": "ok", "message": f"Сессия удалена: {removed.get('name')}"}
    return {"status": "error", "message": "Не найдено"}


@router.post("/api/session/{idx}/profile")
async def api_session_profile(idx: int, request: Request):
    """Обновить профиль браузерной сессии (name, short, color, resume_hash)."""
    temp_idx = idx - len(bot.account_states)
    if not (0 <= temp_idx < len(bot.temp_sessions)):
        return {"ok": False, "error": "Сессия не найдена"}
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "bad json"}
    ts = bot.temp_sessions[temp_idx]
    for field in ("name", "short", "color", "resume_hash"):
        if field in body and isinstance(body[field], str) and body[field].strip():
            ts[field] = body[field].strip()
    if temp_idx in bot.temp_states:
        state = bot.temp_states[temp_idx]
        state.name = ts.get("name", state.name)
        state.short = ts.get("short", state.short)
        state.color = ts.get("color", state.color)
        state.acc.update({k: ts[k] for k in ("name", "short", "color", "resume_hash") if k in ts})
    save_browser_sessions(bot.temp_sessions)
    return {"ok": True}
