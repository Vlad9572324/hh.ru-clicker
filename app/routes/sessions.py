"""
Browser session routes (temporary accounts added via cookie paste).
"""

import asyncio
import hashlib
import re

import requests
from fastapi import APIRouter, Request

from app.config import accounts_data, hh_base
from app.storage import save_browser_sessions
from app.hh_resume import parse_hh_lux_ssr
from app.instances import bot
from app.hh_http import HH, is_impersonating
from app.user_agent import mobile_user_agent, webview_user_agent

from app.routes.accounts import _parse_cookies_str, _AUTH_COOKIE_KEYS


router = APIRouter()


def _validate_and_profile(raw_cookie_line: str) -> dict:
    """
    Синхронно проверяет сессию и вытаскивает профиль из SSR.
    Использует per-validation сессию + warm-up GET к hh.ru/ чтобы получить
    DDoS-Guard-куки; без warm-up прямой GET /applicant/resumes часто
    возвращает 403 (issue #8).
    """
    # Per-validation сессия (ключ = хэш вставляемой cookie-строки): requests
    # мержит общую jar ПОВЕРХ raw `Cookie:` header, и без изоляции валидация
    # новой сессии B могла бы пройти на живых куках другого аккаунта.
    _jar_key = "sess_validate::" + hashlib.sha256(
        raw_cookie_line.encode("utf-8", errors="replace")).hexdigest()[:16]
    base_headers = {
        "User-Agent": webview_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Chromium";v="120", "Not?A_Brand";v="8"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Upgrade-Insecure-Requests": "1",
        "Cookie": raw_cookie_line,
    }
    # HH client (curl_cffi impersonate Chrome) вместо голого requests: без этого
    # HH через DDoS-Guard палит JA3-fingerprint python'a и режет 403/404 ещё до
    # чтения cookie. С impersonate — walk-through как обычный Chrome.
    try:
        # Warm-up для получения DDoS-Guard cookies (best-effort).
        try:
            HH.get(hh_base() + "/", headers=base_headers, timeout=10,
                   allow_redirects=True, _diag_tag="sess_warmup",
                   cookie_jar_key=_jar_key)
        except Exception:
            pass
        r = HH.get(
            hh_base() + "/applicant/resumes",
            headers={**base_headers, "Referer": hh_base() + "/"},
            timeout=15, allow_redirects=True,
            _diag_tag="sess_validate",
            cookie_jar_key=_jar_key,
        )
    except Exception as e:
        return {"ok": False, "error": f"Ошибка сети: {e}"}

    if r.status_code != 200:
        hint = ""
        if r.status_code == 404:
            hint = " — HH вернул 404, обычно это DDoS-Guard soft-ban по IP+fingerprint."
            if not is_impersonating():
                hint += " Установите пакет curl_cffi (рестарт бота) — маскирует TLS под Chrome."
            else:
                hint += " Попробуйте сменить IP (VPN/прокси) или подождать 30-60 мин."
        elif r.status_code in (401, 403):
            hint = " — DDoS-Guard или сессия устарела. Попробуйте обновить cookie из браузера (свежая cURL)."
            if r.status_code == 403 and not is_impersonating():
                hint += " Также помогает curl_cffi для TLS-fingerprint mask."
        return {"ok": False, "error": f"Сессия невалидна: HTTP {r.status_code}{hint}", "http_status": r.status_code}

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

    # HH-fallback: /applicant/resumes теперь редиректит на /applicant/profile/me,
    # где нет applicantResumes в SSR. Парсим /resume/HASH прямо из HTML — эти
    # ссылки остались как навигация к каждому резюме.
    if not resume_hash:
        seen = set()
        for h in re.findall(r'/resume/([a-f0-9]{30,})', r.text):
            if h not in seen:
                seen.add(h)
                all_resumes.append({"hash": h, "title": "Резюме"})
        if all_resumes:
            resume_hash = all_resumes[0]["hash"]

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

    force = bool(body.get("force"))
    loop = asyncio.get_event_loop()
    profile = await loop.run_in_executor(None, _validate_and_profile, raw_cookie_line)

    if not profile["ok"]:
        if not force:
            return {
                "status": "error",
                "message": profile["error"],
                "can_force": profile.get("http_status") in (401, 403),
            }
        # force=true: пользователь хочет добавить сессию без validation
        # (workaround для issue #8 когда HH режет первый запрос).
        # Профиль будет добычен при первом refresh из UI.
        profile = {"ok": True, "name": "", "resume_hash": "", "all_resumes": []}

    display_name = body.get("name", "").strip() or profile["name"] or "Браузер"
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

    # Защита от дублей: если уже есть сессия с таким же resume_hash и hhtoken,
    # не создаём вторую (иначе UI показывает одну и ту же сессию N раз).
    new_hhtoken = auth_cookies.get("hhtoken", "")
    for existing in bot.temp_sessions:
        ex_hash = existing.get("resume_hash", "")
        ex_hhtoken = (existing.get("cookies") or {}).get("hhtoken", "")
        if resume_hash and ex_hash == resume_hash and ex_hhtoken == new_hhtoken:
            return {
                "status": "error",
                "message": f"Сессия уже есть: {existing.get('name', '?')}. Обнови куки через ✏️ Изменить.",
            }

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
        # r12-2 #10: храним raw_cookie_line в памяти (на диск НЕ попадёт через
        # _strip_sensitive_session_fields), нужен для будущих session_refresh без
        # необходимости пересобирать строку из dict.
        "_raw_cookie_line": raw_cookie_line,
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
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, bot.activate_session, temp_idx)
    if ok:
        return {"status": "ok", "message": f"Сессия {ts['name']} запущена как бот"}
    return {"status": "error", "message": "Не удалось запустить"}


@router.post("/api/session/{idx}/deactivate")
async def api_session_deactivate(idx: int):
    """Остановить браузерную сессию (kill воркеры, bot_active=False).
    Сессия + cookies + letter сохраняются — можно потом снова запустить."""
    temp_idx = idx - len(bot.account_states)
    if temp_idx < 0 or temp_idx >= len(bot.temp_sessions):
        return {"status": "error", "message": "Не найдено"}
    ts = bot.temp_sessions[temp_idx]
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, bot.deactivate_session, temp_idx)
    if ok:
        return {"status": "ok", "message": f"Сессия {ts.get('name','')} остановлена"}
    return {"status": "error", "message": "Не удалось остановить"}


def _refresh_via_oauth(acc: dict) -> dict:
    """OAuth-fallback: тянем список резюме через GET /resumes/mine
    (Bearer-only, cookies не нужны). Работает даже когда куки протухли.
    """
    from app.oauth import _obtain_oauth_token, _token_key
    from app.hh_http import HH
    token = _obtain_oauth_token(acc)
    if not token:
        return {"ok": False, "error": "OAuth токен не получен — куки нужны для первичной авторизации"}
    try:
        r = HH.get("https://api.hh.ru/resumes/mine", headers={
            "User-Agent": mobile_user_agent(),
            "Authorization": f"Bearer {token}",
        }, params={"per_page": 30}, cookie_jar_key=_token_key(acc) or None,
            timeout=10, _diag_tag="sess_refresh_oauth")
    except Exception as e:
        return {"ok": False, "error": f"OAuth ошибка: {e}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"OAuth /resumes/mine HTTP {r.status_code}"}
    try:
        data = r.json()
    except Exception:
        return {"ok": False, "error": "OAuth ответ не JSON"}
    all_resumes = []
    name = ""
    for it in data.get("items", []) or []:
        h = it.get("id") or it.get("hash") or ""
        if not h:
            continue
        all_resumes.append({"hash": h, "title": it.get("title") or "Резюме"})
        if not name:
            fn = it.get("first_name") or ""
            ln = it.get("last_name") or ""
            full = (fn + " " + ln).strip()
            if full:
                name = full
    rh = acc.get("resume_hash", "")
    if not rh and all_resumes:
        rh = all_resumes[0]["hash"]
    return {"ok": True, "name": name or "Браузер", "resume_hash": rh,
            "all_resumes": all_resumes, "_source": "oauth"}


@router.post("/api/session/{idx}/refresh")
async def api_session_refresh(idx: int):
    """Перепрофилировать сессию: обновить имя и resume_hash из HH.

    Пытаемся 2 пути:
    1. Cookie-based /applicant/resumes (правильные названия резюме, работает
       если куки живые)
    2. OAuth-based /resumes/mine (fallback когда куки dead — degraded mode)
    """
    temp_idx = idx - len(bot.account_states)
    if temp_idx < 0 or temp_idx >= len(bot.temp_sessions):
        return {"status": "error", "message": "Не найдено"}
    ts = bot.temp_sessions[temp_idx]
    raw_line = ts.get("_raw_cookie_line", "") or "; ".join(f"{k}={v}" for k, v in ts.get("cookies", {}).items())
    loop = asyncio.get_event_loop()
    profile = await loop.run_in_executor(None, _validate_and_profile, raw_line)
    # Cookie-путь мог вернуть ok=True но с пустым resume_hash — это случай нового
    # HH profile-редиректа (/applicant/resumes → /applicant/profile/me, где нет
    # applicantResumes в SSR). Также HTML-fallback ставит title="Резюме" placeholder
    # без реального названия — тоже дёргаем OAuth чтобы получить нормальный title.
    _placeholder_titles = all(
        (r.get("title") or "").strip() in ("", "Резюме")
        for r in (profile.get("all_resumes") or [])
    ) if profile.get("all_resumes") else True
    need_oauth_fallback = (
        (not profile["ok"])
        or (not profile.get("resume_hash") and not profile.get("all_resumes"))
        or _placeholder_titles
    )
    if need_oauth_fallback:
        # OAuth-based: /resumes/mine работает без кук пока refresh_token живой.
        oauth_profile = await loop.run_in_executor(None, _refresh_via_oauth, ts)
        if oauth_profile.get("ok"):
            # Сохраняем имя из cookie-пути если оно нашлось (обычно точнее OAuth-версии).
            if profile.get("ok") and profile.get("name") and profile["name"] != "Браузер":
                oauth_profile["name"] = profile["name"]
            profile = oauth_profile
        elif not profile["ok"]:
            # Оба пути не сработали — вернём подробную причину.
            cookie_err = profile.get("error", "Ошибка")
            oauth_err = oauth_profile.get("error", "Нет OAuth токена")
            return {"status": "error",
                    "message": f"{cookie_err}\n\nOAuth-fallback тоже не помог: {oauth_err}"}
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
    # Аудит 2026-08-17 #18: раньше delete мутировал temp_sessions/temp_states
    # без _activate_lock, пока activate_session мог параллельно создавать state
    # для того же temp_idx → индексы разъезжались. Держим тот же lock, что и
    # activate/deactivate. Плюс join удалённого worker'а, чтобы он не продолжал
    # писать в state после re-index'а (аудит #19).
    with bot._activate_lock:
        temp_idx = idx - len(bot.account_states)
        if not (0 <= temp_idx < len(bot.temp_sessions)):
            return {"status": "error", "message": "Не найдено"}
        removed = bot.temp_sessions.pop(temp_idx)
        removed_state = bot.temp_states.pop(temp_idx, None)
        if removed_state is not None:
            removed_state._deleted = True
            removed_state.paused = True
        new_temp_states = {}
        for old_i, state in bot.temp_states.items():
            new_i = old_i - 1 if old_i > temp_idx else old_i
            new_temp_states[new_i] = state
        bot.temp_states = new_temp_states
    # Join за пределами lock — сам worker может пытаться взять lock изнутри.
    # Аудит round-2 #2: раньше sync join(timeout=5) блокировал uvicorn event
    # loop на 10s (два worker'а × 5с). Уводим join в thread чтобы loop дышал.
    if removed_state is not None:
        import asyncio as _aio
        threads = list(getattr(removed_state, "_workers", []))
        def _join_all():
            for t in threads:
                try:
                    t.join(timeout=5)
                except Exception:
                    pass
        await _aio.get_event_loop().run_in_executor(None, _join_all)
    save_browser_sessions(bot.temp_sessions)
    return {"status": "ok", "message": f"Сессия удалена: {removed.get('name')}"}


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
