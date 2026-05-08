"""FastAPI application, websocket endpoint, and REST API routes."""

import asyncio
import json
import re
import time
from pathlib import Path

import aiohttp
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .bot import BotManager, ConnectionManager
from .hh_client import *
from .state import CONFIG, _CONFIG_KEYS, _url_entry, accounts_data
from .storage import *

app = FastAPI(title="HH Bot Dashboard")
manager = ConnectionManager()
bot = BotManager()

STATIC_DIR = Path("static")
STATIC_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup():
    load_accounts()
    bot.start()
    asyncio.create_task(broadcast_loop())


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            cmd = data.get("type", "")

            if cmd == "pause_toggle":
                bot.toggle_pause()
            elif cmd == "account_pause":
                idx = int(data.get("idx", -1))
                bot.toggle_account_pause(idx)
            elif cmd == "account_llm":
                idx = int(data.get("idx", -1))
                bot.toggle_account_llm(idx)
            elif cmd == "set_config":
                key = data.get("key")
                value = data.get("value")
                if key and key in _CONFIG_KEYS:
                    old_val = getattr(CONFIG, key)
                    try:
                        setattr(CONFIG, key, type(old_val)(value))
                        save_config()
                        bot._add_log("", "", f"⚙️ {key} = {value}", "info")
                    except Exception as e:
                        log_debug(f"set_config error: {e}")
            elif cmd == "set_questionnaire":
                templates = data.get("templates")
                default = data.get("default_answer")
                if isinstance(templates, list):
                    CONFIG.questionnaire_templates = templates
                if isinstance(default, str):
                    CONFIG.questionnaire_default_answer = default
                save_config()
                bot._add_log("", "", f"📝 Шаблоны опроса обновлены ({len(CONFIG.questionnaire_templates)} шт.)", "info")
            elif cmd == "set_letter_templates":
                templates = data.get("templates")
                if isinstance(templates, list):
                    CONFIG.letter_templates = templates
                    save_config()
                    bot._add_log("", "", f"✉️ Шаблоны писем обновлены ({len(templates)} шт.)", "info")
            elif cmd == "set_url_pool":
                pool = data.get("urls")
                if isinstance(pool, list):
                    old_entries = [_url_entry(u) for u in CONFIG.url_pool]
                    old_urls = [e["url"] for e in old_entries if e["url"]]
                    normalized = []
                    for u in pool:
                        entry = _url_entry(u)
                        if entry["url"]:
                            normalized.append(entry)
                    new_urls = [e["url"] for e in normalized]
                    old_to_new = {
                        old_url: new_urls[i]
                        for i, old_url in enumerate(old_urls)
                        if i < len(new_urls) and old_url != new_urls[i]
                    }

                    def rewrite_selected_urls(acc: dict) -> bool:
                        changed = False
                        selected = acc.get("urls") or []
                        if selected:
                            rewritten = []
                            for url in selected:
                                if url in old_to_new:
                                    url = old_to_new[url]
                                    changed = True
                                elif url in old_urls and url not in new_urls:
                                    changed = True
                                    continue
                                if url and url not in rewritten:
                                    rewritten.append(url)
                            if rewritten != selected:
                                acc["urls"] = rewritten
                                changed = True

                        url_pages = acc.get("url_pages") or {}
                        if url_pages:
                            rewritten_pages = {}
                            for url, pages in url_pages.items():
                                if url in old_to_new:
                                    url = old_to_new[url]
                                    changed = True
                                elif url in old_urls and url not in new_urls:
                                    changed = True
                                    continue
                                if url:
                                    rewritten_pages[url] = pages
                            if rewritten_pages != url_pages:
                                acc["url_pages"] = rewritten_pages
                                changed = True
                        return changed

                    CONFIG.url_pool = normalized
                    accounts_changed = False
                    for i, state in enumerate(bot.account_states):
                        if rewrite_selected_urls(state.acc):
                            state.total_urls = len(state.acc.get("urls", []))
                            if 0 <= i < len(accounts_data):
                                accounts_data[i]["urls"] = state.acc.get("urls", [])
                                accounts_data[i]["url_pages"] = state.acc.get("url_pages", {})
                                accounts_changed = True
                    sessions_changed = False
                    for temp_idx, state in bot.temp_states.items():
                        if rewrite_selected_urls(state.acc):
                            state.total_urls = len(state.acc.get("urls", []))
                            if 0 <= temp_idx < len(bot.temp_sessions):
                                bot.temp_sessions[temp_idx]["urls"] = state.acc.get("urls", [])
                                bot.temp_sessions[temp_idx]["url_pages"] = state.acc.get("url_pages", {})
                                sessions_changed = True
                    if accounts_changed:
                        save_accounts()
                    if sessions_changed:
                        save_browser_sessions(bot.temp_sessions)
                    save_config()
                    bot._add_log("", "", f"🔗 Пул URL обновлён ({len(CONFIG.url_pool)} шт.)", "info")
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


@app.post("/api/pause")
async def api_pause():
    bot.toggle_pause()
    return {"paused": bot.paused}


@app.post("/api/account/{idx}/pause")
async def api_account_pause(idx: int):
    bot.toggle_account_pause(idx)
    if 0 <= idx < len(bot.account_states):
        paused = bot.account_states[idx].paused
    else:
        temp_idx = idx - len(bot.account_states)
        s = bot.temp_states.get(temp_idx)
        paused = s.paused if s else False
    return {"paused": paused}


@app.post("/api/account/{idx}/llm_toggle")
async def api_account_llm_toggle(idx: int):
    bot.toggle_account_llm(idx)
    if 0 <= idx < len(bot.account_states):
        enabled = bot.account_states[idx].llm_enabled
    else:
        temp_idx = idx - len(bot.account_states)
        s = bot.temp_states.get(temp_idx)
        enabled = s.llm_enabled if s else True
    return {"llm_enabled": enabled}


class ConfigUpdate(BaseModel):
    key: str
    value: float


@app.post("/api/settings")
async def api_settings(update: ConfigUpdate):
    if update.key in _CONFIG_KEYS:
        old_val = getattr(CONFIG, update.key)
        try:
            setattr(CONFIG, update.key, type(old_val)(update.value))
        except (ValueError, TypeError):
            return {"ok": False, "error": "Invalid value type"}
        save_config()
        return {"ok": True, "key": update.key, "value": getattr(CONFIG, update.key)}
    return {"ok": False, "error": "Unknown key"}


@app.get("/api/sessions")
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


@app.get("/api/debug/session/{idx}")
async def api_debug_session(idx: int):
    """Показать SSR структуру для браузерной сессии (для отладки resume_hash)."""
    temp_idx = idx - len(bot.account_states)
    if temp_idx < 0 or temp_idx >= len(bot.temp_sessions):
        return {"error": "session not found"}
    ts = bot.temp_sessions[temp_idx]
    raw_line = ts.get("_raw_cookie_line", "")
    if not raw_line:
        # Восстановить raw_line из cookies dict
        raw_line = "; ".join(f"{k}={v}" for k, v in ts.get("cookies", {}).items())
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cookie": raw_line,
    }
    loop = asyncio.get_event_loop()
    def _fetch():
        r = requests.get("https://hh.ru/applicant/resumes", headers=headers, verify=False, timeout=15)
        ssr = parse_hh_lux_ssr(r.text)
        # Показываем только верхние ключи и примеры
        preview = {}
        for k, v in ssr.items():
            if isinstance(v, list) and v:
                preview[k] = [v[0]] if len(v) > 0 else []
            elif isinstance(v, dict):
                preview[k] = {kk: vv for kk, vv in list(v.items())[:5]}
            else:
                preview[k] = v
        return {"status": r.status_code, "ssr_keys": list(ssr.keys()), "ssr_preview": preview}
    result = await loop.run_in_executor(None, _fetch)
    return result


@app.get("/api/debug")
async def api_debug():
    snap = bot.get_state_snapshot()
    return {
        "temp_sessions_count": len(bot.temp_sessions),
        "temp_sessions": [
            {k: v for k, v in s.items() if k != "cookies"}
            for s in bot.temp_sessions
        ],
        "accounts_in_snapshot": [
            {"idx": a["idx"], "name": a["name"], "temp": a.get("temp", False)}
            for a in snap["accounts"]
        ],
    }


@app.get("/api/debug/neg_ids/{idx}")
async def api_debug_neg_ids(idx: int):
    """Принудительно вызвать fetch_hh_negotiations_stats для аккаунта и вернуть neg_ids + sample hrefs."""
    if idx < len(bot.account_states):
        state = bot.account_states[idx]
    elif idx - len(bot.account_states) in bot.temp_states:
        state = bot.temp_states[idx - len(bot.account_states)]
    else:
        return {"error": "account not found"}

    acc = state.acc
    cookies = acc["cookies"]
    headers_req = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    import asyncio
    resp = await asyncio.get_event_loop().run_in_executor(
        None, lambda: requests.get(
            "https://hh.ru/applicant/negotiations?filter=all&state=INTERVIEW&page=0",
            cookies=cookies, headers=headers_req, timeout=15,
        )
    )
    body = resp.text
    parts = re.split(r'data-qa="negotiations-item"', body)
    first_item_html = parts[1][:3000] if len(parts) > 1 else "NO ITEMS FOUND"
    all_numbers = re.findall(r'\b\d{6,}\b', body[:80000])[:30]
    data_attrs = re.findall(r'data-[\w-]+="\d{4,}"', body[:80000])[:20]
    neg_ids_from_json = re.findall(r'"chatId"\s*:\s*(\d+)', body)
    # Также пробуем без учёта регистра и другие имена ID-полей
    chat_ids_any = re.findall(r'"(?:chatId|chat_id|topicId|topic_id|negotiationId|id)"\s*:\s*(\d{8,})', body)
    # Ищем __INITIAL_STATE__ или похожий встроенный JSON
    initial_state_match = re.search(r'window\.__(?:INITIAL_STATE|REDUX_STATE|DATA)__\s*=\s*(\{.*?\});', body[:200000], re.DOTALL)
    initial_state_keys = []
    if initial_state_match:
        try:
            import json as _json
            _data = _json.loads(initial_state_match.group(1))
            initial_state_keys = list(_data.keys())[:20]
        except Exception:
            initial_state_keys = ["parse_error"]
    # Ищем script-теги с крупным JSON
    script_jsons = re.findall(r'<script[^>]*>\s*(?:var|const|window\.\w+)\s*=\s*(\{[^<]{100,})', body[:200000])
    script_json_keys = []
    for sj in script_jsons[:3]:
        try:
            import json as _json
            _d = _json.loads(sj)
            script_json_keys.append(list(_d.keys())[:10])
        except Exception:
            script_json_keys.append(["parse_error", sj[:50]])
    return {
        "status_code": resp.status_code,
        "items_count": len(parts) - 1,
        "first_item_html": first_item_html,
        "all_long_numbers_in_page": all_numbers,
        "data_attrs_with_numbers": data_attrs,
        "chatid_from_json": neg_ids_from_json[:20],
        "any_id_fields_8plus_digits": chat_ids_any[:20],
        "initial_state_keys": initial_state_keys,
        "script_json_keys": script_json_keys,
    }


@app.get("/api/debug/thread/{idx}/{chat_id}")
async def api_debug_thread(idx: int, chat_id: str):
    """Test fetch_negotiation_thread for a given chatId using account idx."""
    if idx < len(bot.account_states):
        state = bot.account_states[idx]
    elif idx - len(bot.account_states) in bot.temp_states:
        state = bot.temp_states[idx - len(bot.account_states)]
    else:
        return {"error": "account not found"}
    import asyncio
    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: fetch_negotiation_thread(state.acc, chat_id)
    )
    return result


@app.get("/api/debug/thread_raw/{idx}/{chat_id}")
async def api_debug_thread_raw(idx: int, chat_id: str):
    """Return raw JSON structure from /chat/messages?chatId=... for debugging."""
    if idx < len(bot.account_states):
        state = bot.account_states[idx]
    elif idx - len(bot.account_states) in bot.temp_states:
        state = bot.temp_states[idx - len(bot.account_states)]
    else:
        return {"error": "account not found"}
    acc = state.acc
    import asyncio
    def _fetch():
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, */*",
            "Referer": "https://hh.ru/applicant/negotiations",
        }
        resp = requests.get(
            f"https://hh.ru/chat/messages?chatId={chat_id}",
            cookies=acc["cookies"], headers=headers, timeout=15,
        )
        try:
            data = resp.json()
        except Exception:
            return {"status": resp.status_code, "raw_text": resp.text[:3000]}
        chats_data = data.get("chats", {})
        chats_obj = chats_data.get("chats") or {}
        items = chats_obj.get("items", [])
        display_info = chats_data.get("chatsDisplayInfo", {})
        return {
            "status": resp.status_code,
            "top_keys": list(data.keys()),
            "pagination": {
                "page": chats_obj.get("page"),
                "perPage": chats_obj.get("perPage"),
                "pages": chats_obj.get("pages"),
                "found": chats_obj.get("found"),
                "hasNextPage": chats_obj.get("hasNextPage"),
                "nextFrom": chats_obj.get("nextFrom"),
            },
            "items_count": len(items),
            "item_ids": [str(i.get("id", "?")) for i in items[:10]],
            "item_keys_sample": list(items[0].keys()) if items else [],
            "display_info_sample_keys": list(display_info.keys())[:10],
            "first_item_full": items[0] if items else None,
        }
    return await asyncio.get_event_loop().run_in_executor(None, _fetch)


@app.get("/api/applied")
async def api_applied(limit: int = 300):
    return get_applied_list(limit)


@app.get("/api/tests")
async def api_tests(limit: int = 300):
    return get_test_list(limit)


@app.get("/api/interviews")
async def api_interviews(acc: str = "", limit: int = 2000, status: str = ""):
    return get_interviews_list(acc=acc, limit=limit, status=status)


@app.get("/api/answer_history")
async def api_answer_history(kind: str = "", limit: int = 500):
    _load_cache()
    with _cache_lock:
        items = list(_cache_answer_history or [])
    if kind:
        items = [r for r in items if r.get("kind") == kind]
    items.sort(key=lambda r: r.get("at", ""), reverse=True)
    return items[:limit]


@app.get("/api/vacancies")
async def api_vacancies(limit: int = 3000):
    return get_vacancy_db(limit)


@app.delete("/api/vacancy/{vacancy_id}")
async def api_vacancy_delete(vacancy_id: str, account: str = ""):
    """Удалить вакансию из applied и/или test кэша."""
    _load_cache()
    removed = []
    with _cache_lock:
        if account:
            # Удалить только для конкретного аккаунта
            if account in _cache_applied and vacancy_id in _cache_applied[account]:
                del _cache_applied[account][vacancy_id]
                removed.append(f"applied:{account}")
        else:
            # Удалить из всех аккаунтов
            for acc_name in list(_cache_applied.keys()):
                if vacancy_id in _cache_applied[acc_name]:
                    del _cache_applied[acc_name][vacancy_id]
                    removed.append(f"applied:{acc_name}")
        if vacancy_id in _cache_tests:
            del _cache_tests[vacancy_id]
            removed.append("test")
    if "applied" in " ".join(removed):
        threading.Thread(target=_save_applied_async, daemon=True).start()
    if "test" in " ".join(removed):
        threading.Thread(target=_save_tests_async, daemon=True).start()
    return {"ok": True, "removed": removed}


@app.get("/api/negotiations/{idx}")
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


@app.post("/api/account/{idx}/resume_touch")
async def api_resume_touch(idx: int):
    bot.trigger_resume_touch(idx)
    return {"ok": True}


@app.post("/api/account/{idx}/resume_touch_toggle")
async def api_resume_touch_toggle(idx: int):
    enabled = bot.toggle_resume_touch(idx)
    return {"ok": True, "enabled": enabled}


@app.post("/api/account/{idx}/set_urls")
async def api_set_urls(idx: int, request: Request):
    """Обновить список поисковых URL аккаунта и индивидуальную глубину поиска."""
    body = await request.json()
    urls = [u.strip() for u in body.get("urls", []) if u.strip()]
    # url_pages: {url: pages} — индивидуальная глубина, 0/None = использовать глобальное
    url_pages = {k: int(v) for k, v in body.get("url_pages", {}).items() if v}
    if 0 <= idx < len(bot.account_states):
        bot.account_states[idx].acc["urls"] = urls
        bot.account_states[idx].acc["url_pages"] = url_pages
        bot.account_states[idx].total_urls = len(urls)
        if 0 <= idx < len(accounts_data):
            accounts_data[idx]["urls"] = urls
            accounts_data[idx]["url_pages"] = url_pages
            save_accounts()
        return {"ok": True, "count": len(urls)}
    temp_idx = idx - len(bot.account_states)
    if 0 <= temp_idx < len(bot.temp_sessions):
        state = bot.temp_states.get(temp_idx)
        if state:
            state.acc["urls"] = urls
            state.acc["url_pages"] = url_pages
            state.total_urls = len(urls)
        bot.temp_sessions[temp_idx]["urls"] = urls
        bot.temp_sessions[temp_idx]["url_pages"] = url_pages
        save_browser_sessions(bot.temp_sessions)
        return {"ok": True, "count": len(urls)}
    return {"ok": False, "error": "Аккаунт не найден"}


@app.post("/api/account/{idx}/set_letter")
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


@app.post("/api/account/{idx}/update_cookies")
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

    # Обновляем в account_states (основной аккаунт)
    if 0 <= idx < len(bot.account_states):
        state = bot.account_states[idx]
        auth_cookies = {k: v for k, v in cookies.items() if k in _AUTH_COOKIE_KEYS}
        state.acc["cookies"] = auth_cookies
        state.acc["_raw_cookie_line"] = raw_line
        state.cookies_expired = False  # сбрасываем флаг протухших кук
        # Также обновляем в accounts_data чтобы новые воркеры тоже получили свежие куки
        if 0 <= idx < len(accounts_data):
            accounts_data[idx]["cookies"] = auth_cookies
            save_accounts()
        log_debug(f"update_cookies [{state.name}]: обновлены куки ({len(auth_cookies)} ключей)")
        return {"ok": True, "name": state.name, "keys": list(auth_cookies.keys())}

    # Обновляем temp сессию
    temp_idx = idx - len(bot.account_states)
    if 0 <= temp_idx < len(bot.temp_sessions):
        auth_cookies = {k: v for k, v in cookies.items() if k in _AUTH_COOKIE_KEYS}
        bot.temp_sessions[temp_idx]["cookies"] = auth_cookies
        bot.temp_sessions[temp_idx]["_raw_cookie_line"] = raw_line
        if temp_idx in bot.temp_states:
            bot.temp_states[temp_idx].acc["cookies"] = auth_cookies
            bot.temp_states[temp_idx].cookies_expired = False  # сбрасываем флаг
        save_browser_sessions(bot.temp_sessions)
        name = bot.temp_sessions[temp_idx].get("name", f"Браузер #{temp_idx+1}")
        log_debug(f"update_cookies [temp {temp_idx}] {name}: обновлены куки ({len(auth_cookies)} ключей)")
        return {"ok": True, "name": name, "keys": list(auth_cookies.keys())}

    return {"ok": False, "error": "Аккаунт не найден"}


@app.post("/api/account/{idx}/profile")
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


@app.post("/api/accounts/add")
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
        "short": short or name.split()[0],
        "color": color,
        "resume_hash": resume_hash,
        "letter": letter,
        "cookies": auth_cookies,
        "urls": [],
    }
    accounts_data.append(acc)
    save_accounts()

    # Запускаем воркеры для нового аккаунта
    state = AccountState(acc)
    bot.account_states.append(state)
    new_idx = len(bot.account_states) - 1
    for target in (bot._run_account_worker, bot._fetch_hh_stats_worker):
        threading.Thread(target=target, args=(new_idx, state), daemon=True).start()

    return {"ok": True, "idx": new_idx, "name": name}


@app.delete("/api/account/{idx}/delete")
async def api_account_delete(idx: int):
    """Удалить основной аккаунт."""
    if not (0 <= idx < len(accounts_data)):
        return {"ok": False, "error": "Аккаунт не найден"}

    # Останавливаем воркер
    if 0 <= idx < len(bot.account_states):
        bot.account_states[idx]._deleted = True

    name = accounts_data[idx].get("name", f"#{idx}")
    accounts_data.pop(idx)
    if 0 <= idx < len(bot.account_states):
        bot.account_states.pop(idx)

    save_accounts()
    bot._add_log("", "", f"🗑️ Аккаунт удалён: {name}", "info")
    return {"ok": True}


@app.post("/api/account/{idx}/apply_tests")
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


@app.get("/api/raw/config")
async def api_raw_config_get():
    """Вернуть текущий config как объект."""
    cfg = {k: getattr(CONFIG, k) for k in _CONFIG_KEYS}
    cfg["questionnaire_templates"] = CONFIG.questionnaire_templates
    cfg["letter_templates"] = CONFIG.letter_templates
    cfg["url_pool"] = CONFIG.url_pool
    return cfg


@app.post("/api/raw/config")
async def api_raw_config_set(request: Request):
    """Перезаписать config из JSON-объекта."""
    try:
        data = await request.json()
    except Exception:
        return {"ok": False, "error": "Невалидный JSON"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "Ожидается объект"}
    for key, value in data.items():
        if key in _CONFIG_KEYS:
            try:
                field_type = type(getattr(CONFIG, key))
                setattr(CONFIG, key, field_type(value))
            except Exception:
                setattr(CONFIG, key, value)
        elif key == "questionnaire_templates" and isinstance(value, list):
            CONFIG.questionnaire_templates = value
        elif key == "letter_templates" and isinstance(value, list):
            CONFIG.letter_templates = value
        elif key == "url_pool" and isinstance(value, list):
            CONFIG.url_pool = value
    save_config()
    return {"ok": True}


@app.get("/api/raw/accounts")
async def api_raw_accounts_get():
    """Вернуть accounts без значений cookies (только ключи)."""
    safe = []
    for acc in accounts_data:
        a = {k: v for k, v in acc.items() if k != "cookies"}
        a["cookies"] = {k: "***" for k in acc.get("cookies", {})}
        safe.append(a)
    return safe


@app.post("/api/raw/accounts")
async def api_raw_accounts_set(request: Request):
    """Перезаписать accounts. Значение cookies '***' сохраняет старое."""
    try:
        data = await request.json()
    except Exception:
        return {"ok": False, "error": "Невалидный JSON"}
    if not isinstance(data, list):
        return {"ok": False, "error": "Ожидается массив"}
    old_by_name = {a.get("name", ""): a for a in accounts_data}
    merged = []
    for acc in data:
        if not isinstance(acc, dict):
            continue
        name = acc.get("name", "")
        old = old_by_name.get(name, {})
        new_cookies = acc.get("cookies", {})
        merged_cookies = {
            k: (old.get("cookies", {}).get(k, "") if v == "***" else v)
            for k, v in new_cookies.items()
        }
        for k, v in old.get("cookies", {}).items():
            if k not in merged_cookies:
                merged_cookies[k] = v
        acc = dict(acc)
        acc["cookies"] = merged_cookies
        merged.append(acc)
    accounts_data.clear()
    accounts_data.extend(merged)
    save_accounts()
    return {"ok": True, "count": len(merged)}


@app.get("/api/account/{idx}/resume_text")
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
    # Принудительное обновление: очищаем кеш для этого hash, чтобы загрузить свежие данные
    rh = s.acc.get("resume_hash", "")
    _resume_cache.pop(rh, None)
    text = await asyncio.get_event_loop().run_in_executor(None, fetch_resume_text, s.acc)
    return {"ok": True, "resume_hash": rh, "length": len(text), "text": text}


@app.get("/api/account/{idx}/resume_views")
async def api_resume_views(idx: int):
    """История просмотров резюме для аккаунта"""
    s = None
    if 0 <= idx < len(bot.account_states):
        s = bot.account_states[idx]
    else:
        temp_idx = idx - len(bot.account_states)
        s = bot.temp_states.get(temp_idx)
    if s:
        # если кэш ещё пустой — фетчим прямо сейчас
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


async def _fetch_questionnaire_data(acc: dict, vid: str,
                                    vacancy_title: str = "", company: str = "") -> dict:
    """
    Получает форму опросника и возвращает список вопросов с полями.
    НЕ отправляет отклик.
    """
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": f"https://hh.ru/vacancy/{vid}",
    }
    url_form = f"https://hh.ru/applicant/vacancy_response?vacancyId={vid}&withoutTest=no"
    async with aiohttp.ClientSession(cookies=acc["cookies"], connector=connector, headers=headers) as session:
        async with session.get(url_form, timeout=aiohttp.ClientTimeout(total=15)) as r:
            html = await r.text()

    hidden = dict(re.findall(r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html))
    hidden.update(dict(re.findall(r'<input[^>]+name="([^"]+)"[^>]+type="hidden"[^>]+value="([^"]*)"', html)))

    # Тексты вопросов
    q_blocks = re.findall(
        r'data-qa="task-question">(.*?)(?=data-qa="task-question"|</(?:div|section|form)>)',
        html, re.DOTALL
    )
    q_texts = []
    for b in q_blocks:
        c = re.sub(r'<[^>]+>', ' ', b)
        c = re.sub(r'&quot;', '"', re.sub(r'&ndash;', '–', re.sub(r'&nbsp;', ' ', c)))
        c = re.sub(r'\s+', ' ', c).strip()
        q_texts.append(c)

    questions = []
    q_idx = 0

    # Текстовое поле
    for name in re.findall(r'<textarea[^>]+name="(task_\d+_text)"', html):
        q_text = q_texts[q_idx] if q_idx < len(q_texts) else ""
        suggested = get_questionnaire_template_answer(q_text)
        questions.append({"field": name, "type": "textarea", "text": q_text,
                          "options": [], "suggested": suggested})
        q_idx += 1

    # Радиокнопки
    radio_groups: dict = {}
    radio_order: list = []
    for inp in re.findall(r'<input[^>]+type="radio"[^>]+>', html, re.I):
        nm = re.search(r'name="([^"]+)"', inp)
        vl = re.search(r'value="([^"]+)"', inp)
        if nm and vl and re.match(r'task_\d+', nm.group(1)):
            n, v = nm.group(1), vl.group(1)
            if n not in radio_groups:
                radio_groups[n] = []
                radio_order.append(n)
            radio_groups[n].append(v)

    # Подписи для радиокнопок: ищем label рядом с каждым input
    label_map: dict = {}
    for inp_with_id in re.findall(r'<input[^>]+type="radio"[^>]+id="([^"]+)"[^>]*>', html, re.I):
        label_m = re.search(rf'<label[^>]+for="{re.escape(inp_with_id)}"[^>]*>(.*?)</label>', html, re.DOTALL)
        if label_m:
            lbl = re.sub(r'<[^>]+>', '', label_m.group(1)).strip()
            label_map[inp_with_id] = lbl
    # Запасной вариант: по порядку "да"/"нет", если подписи не найдены
    default_labels = ["да", "нет"]

    for name in radio_order:
        vals = radio_groups[name]
        q_text = q_texts[q_idx] if q_idx < len(q_texts) else ""
        options = []
        for i, v in enumerate(vals):
            lbl = label_map.get(v, default_labels[i] if i < len(default_labels) else v)
            options.append({"value": v, "label": lbl})
        tmpl = get_questionnaire_template_answer(q_text).lower()
        chosen = vals[0]
        if any(w in tmpl for w in ("нет", "no", "не готов", "не готова", "не могу")):
            chosen = vals[1] if len(vals) > 1 else vals[0]
        questions.append({"field": name, "type": "radio", "text": q_text,
                          "options": options, "suggested": chosen})
        q_idx += 1

    rich_qs = _parse_questionnaire_rich(html)
    resume_text = fetch_resume_text(acc) if CONFIG.llm_use_resume else ""
    cover_letter = acc.get("letter", "") if CONFIG.llm_use_cover_letter else ""
    decisions = resolve_questionnaire_answers(
        rich_qs, vacancy_title=vacancy_title, company=company,
        resume_text=resume_text, cover_letter=cover_letter,
    )
    for q in questions:
        d = decisions.get(q.get("field"))
        if d:
            q["suggested"] = d.get("answer", q.get("suggested", ""))
            q["suggested_source"] = d.get("source", "fallback")

    return {"questions": questions, "hidden": hidden, "url_form": url_form}


# Cookies авторизации, нужные для откликов: без трекинговых с + и =
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

    if raw.startswith("curl "):
        # cURL: ищем -H 'cookie: ...' или -H "cookie: ..." в том числе на нескольких строках
        m = re.search(r"-H\s+['\"](?:C|c)ookie:\s*([^'\"]+)['\"]", raw, re.DOTALL)
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


def _validate_and_profile(raw_cookie_line: str) -> dict:
    """
    Синхронно проверяет сессию и вытаскивает профиль из SSR.
    Передаёт Cookie как сырую строку заголовка — без перекодирования requests.
    Возвращает {"ok": bool, "name": str, "resume_hash": str, "error": str}.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://hh.ru/",
        "Cookie": raw_cookie_line,  # сырая строка, без URL-кодирования
    }
    try:
        r = requests.get(
            "https://hh.ru/applicant/resumes",
            headers=headers,
            verify=False,
            timeout=15,
            allow_redirects=True,
        )
    except Exception as e:
        return {"ok": False, "error": f"Ошибка сети: {e}"}

    if r.status_code != 200:
        hint = " — возможно, сессия устарела или нужно войти заново" if r.status_code in (401, 403) else ""
        return {"ok": False, "error": f"Сессия невалидна: HTTP {r.status_code}{hint}"}

    ssr = parse_hh_lux_ssr(r.text)

    # Имя — account.firstName + account.lastName
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

    # Все резюме из списка applicantResumes
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

    # latestResumeHash как приоритетный выбор
    latest = ssr.get("latestResumeHash", "")
    if latest:
        resume_hash = latest
        # Убеждаемся что latestResumeHash есть в списке
        if not any(r["hash"] == latest for r in all_resumes):
            all_resumes.insert(0, {"hash": latest, "title": "Резюме"})
    elif all_resumes:
        resume_hash = all_resumes[0]["hash"]
    else:
        resume_hash = ""

    return {"ok": True, "name": name or "Браузер", "resume_hash": resume_hash, "all_resumes": all_resumes}


@app.post("/api/session/add")
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

    # Имя: из формы → из SSR → "Браузер"
    display_name = body.get("name", "").strip() or profile["name"]
    all_resumes = profile.get("all_resumes", [])

    # Пользователь может передать resume_hash при множественном выборе
    selected_hash = body.get("resume_hash", "").strip()
    if selected_hash and any(r["hash"] == selected_hash for r in all_resumes):
        resume_hash = selected_hash
    else:
        resume_hash = profile["resume_hash"]

    # Письмо: из формы → из совпадающего аккаунта по resume_hash → пусто
    letter = body.get("letter", "").strip()
    if not letter:
        for acc in accounts_data:
            if acc.get("resume_hash") == resume_hash:
                letter = acc.get("letter", "")
                break

    # Храним только auth-куки (без трекинговых с + / = в значениях)
    auth_cookies = {k: v for k, v in cookies.items() if k in _AUTH_COOKIE_KEYS}

    idx_in_temp = len(bot.temp_sessions)
    temp_acc = {
        "name": f"{display_name} (🌐)",
        "short": f"🌐{display_name.split()[0]}",
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


@app.patch("/api/session/{idx}")
async def api_session_patch(idx: int, body: dict):
    temp_idx = idx - len(bot.account_states)
    if 0 <= temp_idx < len(bot.temp_sessions):
        ts = bot.temp_sessions[temp_idx]
        if "letter" in body:
            ts["letter"] = body["letter"]
            # Обновляем живой AccountState если сессия запущена
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


@app.post("/api/session/{idx}/activate")
async def api_session_activate(idx: int):
    """Запустить браузерную сессию как бот-аккаунт."""
    temp_idx = idx - len(bot.account_states)
    if temp_idx < 0 or temp_idx >= len(bot.temp_sessions):
        return {"status": "error", "message": "Не найдено"}
    ts = bot.temp_sessions[temp_idx]
    if not ts.get("resume_hash"):
        return {"status": "error", "message": "Сначала найдите резюме (нажмите 🔄)"}
    ok = bot.activate_session(temp_idx)
    if ok:
        return {"status": "ok", "message": f"Сессия {ts['name']} запущена как бот"}
    return {"status": "error", "message": "Не удалось запустить"}


@app.post("/api/session/{idx}/refresh")
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
    if profile["resume_hash"]:
        bot.temp_sessions[temp_idx]["resume_hash"] = profile["resume_hash"]
    if profile.get("all_resumes"):
        bot.temp_sessions[temp_idx]["all_resumes"] = profile["all_resumes"]
    if profile["name"] and profile["name"] != "Браузер":
        old_name = ts.get("name", "")
        # Сохраняем эмодзи суффикс если есть
        suffix = " (🌐)" if "(🌐)" in old_name else ""
        bot.temp_sessions[temp_idx]["name"] = profile["name"] + suffix
    save_browser_sessions(bot.temp_sessions)
    return {"status": "ok", "resume_hash": profile["resume_hash"], "name": profile["name"]}


@app.delete("/api/session/{idx}")
async def api_session_delete(idx: int):
    temp_idx = idx - len(bot.account_states)
    if 0 <= temp_idx < len(bot.temp_sessions):
        removed = bot.temp_sessions.pop(temp_idx)
        # Останавливаем рабочий поток, если он активен
        if temp_idx in bot.temp_states:
            bot.temp_states[temp_idx]._deleted = True
        # Переназначаем ключи temp_states, потому что список temp_sessions сдвинулся после pop
        new_temp_states = {}
        for old_i, state in bot.temp_states.items():
            if old_i == temp_idx:
                continue  # Удалено: пропускаем
            new_i = old_i - 1 if old_i > temp_idx else old_i
            new_temp_states[new_i] = state
        bot.temp_states = new_temp_states
        save_browser_sessions(bot.temp_sessions)
        return {"status": "ok", "message": f"Сессия удалена: {removed.get('name')}"}
    return {"status": "error", "message": "Не найдено"}


@app.post("/api/session/{idx}/profile")
async def api_session_profile(idx: int, request: Request):
    """Обновить профиль браузерной сессии (name, short, color, resume_hash)."""
    temp_idx = idx - len(bot.account_states)
    if not (0 <= temp_idx < len(bot.temp_sessions)):
        return {"ok": False, "error": "Сессия не найдена"}
    body = await request.json()
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


@app.post("/api/apply/check")
async def api_apply_check(body: dict):
    """
    Шаг 1: проверяет вакансию — можно ли откликнуться, требует ли опрос.
    Возвращает статус и данные формы если test-required.
    """
    acc_idx = int(body.get("account_idx", 0))
    raw = body.get("vacancy_id", "").strip()
    # Извлекаем ID из URL или чистого числа
    m = re.search(r'/vacancy/(\d+)', raw) or re.match(r'^(\d+)$', raw)
    if not m:
        return {"status": "error", "message": "Не удалось определить ID вакансии"}
    vid = m.group(1)

    acc = bot._get_apply_acc(acc_idx)
    if acc is None:
        return {"status": "error", "message": "Неверный аккаунт"}

    custom_letter = body.get("letter", "").strip()
    if custom_letter:
        acc["letter"] = custom_letter

    # Пробуем через popup
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    try:
        async with aiohttp.ClientSession(
            cookies=acc["cookies"],
            connector=aiohttp.TCPConnector(ssl=ssl_ctx),
            headers=get_headers(acc["cookies"]["_xsrf"])
        ) as session:
            data = aiohttp.FormData()
            for k, v in [("resume_hash", acc["resume_hash"]), ("vacancy_id", vid),
                         ("letter", acc["letter"]), ("lux", "true"), ("ignore_postponed", "true")]:
                data.add_field(k, v)
            async with session.post(
                "https://hh.ru/applicant/vacancy_response/popup",
                data=data, timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                txt = await r.text()
                status_code = r.status

        # Разбираем ответ
        if status_code == 200:
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
            return {"status": "already", "vacancy_id": vid, "message": "Уже откликались на эту вакансию"}

        if "test-required" in txt:
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
            qdata = await _fetch_questionnaire_data(
                acc, vid, vacancy_title=info.get("title", ""), company=info.get("company", "")
            )
            return {
                "status": "test_required",
                "vacancy_id": vid,
                **info,
                "questions": qdata["questions"],
                "letter": acc["letter"],
                "message": f"Вакансия требует опрос ({len(qdata['questions'])} вопросов)",
            }

        return {"status": "error", "vacancy_id": vid, "message": f"HTTP {status_code}: {txt[:100]}"}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/apply/submit")
async def api_apply_submit(body: dict):
    """
    Шаг 2: отправляет отклик с заполненными ответами на опрос.
    """
    acc_idx = int(body.get("account_idx", 0))
    vid = str(body.get("vacancy_id", "")).strip()
    letter = body.get("letter", "")
    user_answers = body.get("answers", {})  # {field_name: value}

    acc = bot._get_apply_acc(acc_idx)
    if acc is None:
        return {"status": "error", "message": "Неверный аккаунт"}
    if letter:
        acc = {**acc, "letter": letter}

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    url_form = f"https://hh.ru/applicant/vacancy_response?vacancyId={vid}&withoutTest=no"

    try:
        async with aiohttp.ClientSession(
            cookies=acc["cookies"],
            connector=aiohttp.TCPConnector(ssl=ssl_ctx),
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                     "Accept": "text/html,*/*", "Referer": f"https://hh.ru/vacancy/{vid}"}
        ) as session:
            # Свежая форма (нужны актуальные uidPk/guid/startTime/_xsrf)
            async with session.get(url_form, timeout=aiohttp.ClientTimeout(total=15)) as r:
                html = await r.text()

            hidden = dict(re.findall(r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html))
            hidden.update(dict(re.findall(r'<input[^>]+name="([^"]+)"[^>]+type="hidden"[^>]+value="([^"]*)"', html)))
            rich_qs = {q.get("field"): q for q in _parse_questionnaire_rich(html)}

            form = aiohttp.FormData()
            form.add_field("resume_hash", acc["resume_hash"])
            form.add_field("vacancy_id", vid)
            form.add_field("letter", acc["letter"])
            form.add_field("lux", "true")
            for name in ("_xsrf", "uidPk", "guid", "startTime", "testRequired"):
                if name in hidden:
                    form.add_field(name, hidden[name])
            for name, value in user_answers.items():
                form.add_field(name, str(value))
                q = rich_qs.get(name, {})
                record_answer_history(
                    kind="questionnaire",
                    source="manual",
                    question=q.get("text", name),
                    answer=str(value),
                    account=acc.get("name", ""),
                    vacancy_id=vid,
                    metadata={"field": name, "via": "manual_apply_submit"},
                )

            async with session.post(
                url_form,
                headers={"X-Xsrftoken": acc["cookies"]["_xsrf"], "Referer": url_form},
                data=form,
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=False,
            ) as r2:
                status = r2.status
                location = r2.headers.get("location", "")

        if status in (302, 303):
            if "negotiations-limit-exceeded" in location:
                return {"status": "limit", "message": "Достигнут лимит откликов"}
            if "withoutTest=no" in location or f"vacancyId={vid}" in location:
                return {"status": "error", "message": "Форма не принята — возможно не все вопросы заполнены"}
            # Успех
            state = bot._get_apply_state(acc_idx)
            if state:
                state.sent += 1
                state.questionnaire_sent += 1
            add_applied(acc["name"], vid)
            bot._add_log(state.short, state.color, f"📝 Ручной отклик (опрос): {vid}", "success")
            return {"status": "sent", "message": "Отклик успешно отправлен ✅"}

        return {"status": "error", "message": f"HTTP {status}"}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/llm_profiles")
async def api_llm_profiles(request: Request):
    """Save LLM multi-profile configuration."""
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "bad json"}
    profiles = body.get("profiles")
    mode = body.get("mode", "fallback")
    if isinstance(profiles, list):
        # Сохраняем существующий api_key, если входящий профиль прислал пустую строку
        # (happens when page reloads and key fields are blank for security reasons)
        old_by_idx = {i: p for i, p in enumerate(CONFIG.llm_profiles or [])}
        for i, p in enumerate(profiles):
            if not p.get("api_key") and old_by_idx.get(i, {}).get("api_key"):
                p["api_key"] = old_by_idx[i]["api_key"]
        CONFIG.llm_profiles = profiles
        # Синхронизируем legacy-поля с первым профилем для обратной совместимости
        if profiles:
            first = profiles[0]
            if first.get("api_key"):
                CONFIG.llm_api_key = first["api_key"]
            if first.get("base_url"):
                CONFIG.llm_base_url = first["base_url"]
            if first.get("model"):
                CONFIG.llm_model = first["model"]
    if mode in ("fallback", "roundrobin"):
        CONFIG.llm_profile_mode = mode
    save_config()
    return {"ok": True}


@app.post("/api/llm_toggle")
async def api_llm_toggle():
    """Toggle global LLM auto-reply on/off instantly."""
    CONFIG.llm_enabled = not CONFIG.llm_enabled
    save_config()
    bot._add_log("", "", f"🤖 LLM авто-ответы {'включены' if CONFIG.llm_enabled else 'выключены'}", "success" if CONFIG.llm_enabled else "warning")
    return {"llm_enabled": CONFIG.llm_enabled}


@app.post("/api/llm_config")
async def api_llm_config(request: Request):
    """Save LLM configuration."""
    body = await request.json()
    if "api_key" in body and str(body["api_key"]).strip():
        CONFIG.llm_api_key = str(body["api_key"]).strip()
    if "base_url" in body:
        CONFIG.llm_base_url = str(body["base_url"]).strip()
    if "model" in body:
        CONFIG.llm_model = str(body["model"]).strip()
    if "system_prompt" in body:
        CONFIG.llm_system_prompt = str(body["system_prompt"]).strip()
    if "enabled" in body:
        CONFIG.llm_enabled = bool(body["enabled"])
    if "auto_send" in body:
        CONFIG.llm_auto_send = bool(body["auto_send"])
    if "use_cover_letter" in body:
        CONFIG.llm_use_cover_letter = bool(body["use_cover_letter"])
    if "use_resume" in body:
        CONFIG.llm_use_resume = bool(body["use_resume"])
    # Синхронизируем первый профиль для обратной совместимости, если профили есть
    if CONFIG.llm_profiles and CONFIG.llm_api_key:
        first = CONFIG.llm_profiles[0]
        if not first.get("api_key") or "api_key" in body:
            first["api_key"] = CONFIG.llm_api_key
        if not first.get("base_url") or "base_url" in body:
            first["base_url"] = CONFIG.llm_base_url
        if not first.get("model") or "model" in body:
            first["model"] = CONFIG.llm_model
    save_config()
    return {"ok": True}


# Модели которые стоит исключить из чат-списка
_LLM_EXCLUDE_KEYWORDS = ("embed", "whisper", "tts", "dall", "moderation", "search", "realtime", "transcri")

def _is_chat_model(model_id: str) -> bool:
    mid = model_id.lower()
    return not any(k in mid for k in _LLM_EXCLUDE_KEYWORDS)

def _detect_base_url(api_key: str) -> str:
    """Угадать base_url по формату ключа."""
    if api_key.startswith("gsk_"):
        return "https://api.groq.com/openai/v1"
    if api_key.startswith("sk-or-"):
        return "https://openrouter.ai/api/v1"
    if api_key.startswith("sk-proj-"):
        return "https://api.openai.com/v1"
    # Ключи DeepSeek короче примерно 35 символов и начинаются с sk-
    if api_key.startswith("sk-") and len(api_key) < 45:
        return "https://api.deepseek.com"
    return "https://api.openai.com/v1"

@app.post("/api/llm_run_now")
async def api_llm_run_now():
    """Принудительно запустить LLM авто-ответы для всех аккаунтов прямо сейчас (в фоне)."""
    import asyncio, threading
    def _run():
        states = list(bot.account_states) + list(bot.temp_states.values())
        for state in states:
            try:
                bot._process_llm_replies(state)
            except Exception as e:
                log_debug(f"llm_run_now {state.short}: {e}")
    threading.Thread(target=_run, daemon=True).start()
    return {"started": True, "accounts": len(bot.account_states) + len(bot.temp_states)}


@app.post("/api/llm_reset_replied")
async def api_llm_reset_replied():
    """Сбросить историю отправленных LLM-ответов для всех аккаунтов.
    Позволяет боту повторно обработать чаты, помеченные как 'уже отвечали'.
    """
    all_states = list(bot.account_states) + list(bot.temp_states.values())
    cleared = []
    for state in all_states:
        n_replied = len(state.llm_replied_msgs)
        n_skip = len(state._llm_temp_skip)
        n_no_chat = len(state._llm_no_chat)
        state.llm_replied_msgs.clear()
        state._llm_temp_skip.clear()
        state._llm_no_chat.clear()
        cleared.append({"acc": state.short, "replied_cleared": n_replied, "skip_cleared": n_skip, "no_chat_cleared": n_no_chat})
    with bot._llm_sent_lock:
        n_global = len(bot._llm_sent_global)
        bot._llm_sent_global.clear()
    bot._add_log("system", "green", f"🤖 История LLM-ответов сброшена для {len(cleared)} аккаунтов + {n_global} глобальных записей", "success")
    return {"ok": True, "cleared": cleared, "global_cleared": n_global}


@app.post("/api/llm_detect")
async def api_llm_detect(request: Request):
    """Определить провайдера по ключу и получить список доступных моделей."""
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "bad json"}
    api_key = str(body.get("api_key", "")).strip()
    base_url = str(body.get("base_url", "")).strip()
    if not api_key:
        return {"ok": False, "error": "Нет ключа"}
    if not base_url:
        base_url = _detect_base_url(api_key)
    try:
        resp = requests.get(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=12, verify=False,
        )
        if resp.status_code != 200:
            return {"ok": False, "base_url": base_url, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        raw_models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]
        chat_models = [m for m in raw_models if _is_chat_model(m)]
        # Сортируем: сначала более новые (обычно содержат большую цифру или "latest")
        chat_models.sort(key=lambda m: (
            "latest" in m,
            any(x in m for x in ("gpt-4", "claude", "llama-3", "deepseek", "gemini")),
        ), reverse=True)
        return {"ok": True, "base_url": base_url, "models": chat_models}
    except Exception as e:
        return {"ok": False, "base_url": base_url, "error": str(e)}


@app.post("/api/account/{idx}/decline_discards")
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
            f"🗑️ Отклонено дискардов: {count}",
            "info",
        )
        return {"declined": count}
    return {"error": "Invalid idx"}


# ============================================================
# ЦИКЛ BROADCAST
# ============================================================

async def broadcast_loop():
    while True:
        try:
            if manager.active:
                snapshot = bot.get_state_snapshot()
                await manager.broadcast(snapshot)
        except Exception as e:
            log_debug(f"broadcast_loop error: {e}")
        await asyncio.sleep(0.3)
