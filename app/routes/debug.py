"""
Debug endpoints for inspecting HH SSR, chats, and account state.
"""

import asyncio

import requests
from app.config import hh_base
from fastapi import APIRouter, Request

from app.hh_chat import fetch_negotiation_thread
from app.hh_client_factory import get_client
from app.hh_resume import parse_hh_lux_ssr
from app.instances import bot
from app.hh_http import HH, is_impersonating, impersonate_version
from app.user_agent import webview_user_agent
from fastapi.responses import PlainTextResponse
from pathlib import Path


router = APIRouter()


def _tail(path: Path, n_bytes: int = 20000) -> str:
    """Read last ~n_bytes of a file as UTF-8 text."""
    try:
        if not path.exists():
            return f"(файл {path} не существует)"
        size = path.stat().st_size
        if size <= n_bytes:
            return path.read_text(encoding="utf-8", errors="replace")
        with open(path, "rb") as f:
            f.seek(-n_bytes, 2)
            return "…(truncated)\n" + f.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"(ошибка чтения: {e})"


@router.get("/api/diagnostic_bundle", response_class=PlainTextResponse)
async def api_diagnostic_bundle():
    """Собрать текстовый bundle для отправки в support / issue:
    - версия / TLS-impersonate статус
    - счётчик сессий / activated bots
    - последние 20 KB debug.log
    - последние 20 KB diag.log (только suspect responses)

    Возвращает text/plain — юзер копирует одним Ctrl+A / жмёт «Скачать».
    Никаких куков, токенов и текстов писем — только метаданные и HTTP-ошибки.
    """
    import platform, sys
    lines = []
    lines.append("=== HH.BOT DIAGNOSTIC BUNDLE ===")
    lines.append(f"python: {sys.version.split()[0]}  platform: {platform.platform()}")
    lines.append(f"impersonating: {is_impersonating()}  as: {impersonate_version()}")
    lines.append(f"temp_sessions: {len(bot.temp_sessions)}  active_bots: {len(bot.temp_states)}  regular_accounts: {len(bot.account_states)}")
    lines.append("")
    lines.append("=== data/diag.log (последние ~20 KB) ===")
    lines.append(_tail(Path("data/diag.log")))
    lines.append("")
    lines.append("=== data/debug.log (последние ~20 KB) ===")
    lines.append(_tail(Path("data/debug.log")))
    return "\n".join(lines)


@router.get("/api/debug/session/{idx}")
async def api_debug_session(idx: int):
    """Показать SSR структуру для браузерной сессии (для отладки resume_hash)."""
    temp_idx = idx - len(bot.account_states)
    if temp_idx < 0 or temp_idx >= len(bot.temp_sessions):
        return {"ok": False, "error": "session not found"}
    ts = bot.temp_sessions[temp_idx]
    raw_line = ts.get("_raw_cookie_line", "")
    if not raw_line:
        raw_line = "; ".join(f"{k}={v}" for k, v in ts.get("cookies", {}).items())
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cookie": raw_line,
    }
    loop = asyncio.get_event_loop()
    def _fetch():
        try:
            # Cookies идут сырым заголовком Cookie (из _raw_cookie_line) в headers.
            r = HH.get(hh_base() + "/applicant/resumes", headers=headers, timeout=15)
            ssr = parse_hh_lux_ssr(r.text)
            preview = {}
            for k, v in ssr.items():
                if isinstance(v, list) and v:
                    preview[k] = [v[0]] if len(v) > 0 else []
                elif isinstance(v, dict):
                    preview[k] = {kk: vv for kk, vv in list(v.items())[:5]}
                else:
                    preview[k] = v
            return {"status": r.status_code, "ssr_keys": list(ssr.keys()), "ssr_preview": preview}
        except requests.RequestException as e:
            return {"ok": False, "error": str(e)[:100]}
    result = await loop.run_in_executor(None, _fetch)
    return result


_SESSION_REDACT_KEYS = {"cookies", "_raw_cookie_line", "raw_cookie_line", "api_key"}


def _safe_session_dict(s: dict) -> dict:
    """Strip raw cookie line and any other sensitive fields before returning to client."""
    return {k: v for k, v in s.items() if k not in _SESSION_REDACT_KEYS}


@router.get("/api/proxy/info")
async def api_proxy_info():
    """URL прокси + текущий исходящий IP (через прокси если задан)."""
    from app.hh_http import probe_outbound_ip, is_impersonating, impersonate_version
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, probe_outbound_ip)
    data["impersonate"] = impersonate_version() if is_impersonating() else ""
    return data


@router.post("/api/proxy/set")
async def api_proxy_set(request: Request):
    """Runtime смена прокси. Body {url}. Пустая строка = отключить. Перед save
    делаем probe (api.ipify.org) — если 200 применяем + persist в CONFIG,
    иначе возвращаем error без сохранения (не портим рабочую конфигурацию)."""
    from app.hh_http import set_proxy, proxy_url as _cur_proxy, probe_outbound_ip
    from app.config import CONFIG, save_config
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "bad json"}
    new_url = (body.get("url") or "").strip()
    old_url = _cur_proxy()
    loop = asyncio.get_event_loop()
    set_proxy(new_url)
    probe = await loop.run_in_executor(None, probe_outbound_ip)
    if new_url and probe.get("error"):
        # Прокси не работает — откатываем.
        set_proxy(old_url)
        return {"ok": False, "error": f"probe failed: {probe['error']}", "reverted_to": old_url}
    CONFIG.hh_proxy_url = new_url
    save_config()
    return {"ok": True, "proxy": new_url, "ip": probe.get("ip", ""), "impersonate": probe.get("impersonate", "")}


@router.get("/api/debug")
async def api_debug():
    snap = bot.get_state_snapshot()
    return {
        "temp_sessions_count": len(bot.temp_sessions),
        "temp_sessions": [_safe_session_dict(s) for s in bot.temp_sessions],
        "accounts_in_snapshot": [
            {"idx": a["idx"], "name": a["name"], "temp": a.get("temp", False)}
            for a in snap["accounts"]
        ],
    }


@router.get("/api/debug/neg_ids/{idx}")
async def api_debug_neg_ids(idx: int):
    """Принудительно получить negotiations аккаунта через HHClient-factory.

    Клиент выбирается по acc["mode"] (web/mobile/auto); web-реализация
    делегирует в hh_negotiations.fetch_hh_negotiations_stats.
    В ответе mode — сырое поле аккаунта ("" если поля нет; нормализацию и
    резолв "auto" делает фабрика, а выбранный клиент виден в backend),
    backend — класс выбранного клиента.
    """
    if idx < len(bot.account_states):
        state = bot.account_states[idx]
    elif idx - len(bot.account_states) in bot.temp_states:
        state = bot.temp_states[idx - len(bot.account_states)]
    else:
        return {"ok": False, "error": "account not found"}

    acc = state.acc
    client = get_client(acc)  # до executor: выбор клиента синхронный
    try:
        data = await asyncio.get_event_loop().run_in_executor(
            None, lambda: client.fetch_negotiations()
        )
    except Exception as e:
        return {"ok": False, "error": str(e)[:100]}
    return {
        "ok": True,
        "account": acc.get("name", ""),
        "mode": acc.get("mode", ""),
        "backend": type(client).__name__,
        "negotiations": data,
    }


@router.get("/api/debug/thread/{idx}/{chat_id}")
async def api_debug_thread(idx: int, chat_id: str):
    """Test fetch_negotiation_thread for a given chatId using account idx."""
    if idx < len(bot.account_states):
        state = bot.account_states[idx]
    elif idx - len(bot.account_states) in bot.temp_states:
        state = bot.temp_states[idx - len(bot.account_states)]
    else:
        return {"ok": False, "error": "account not found"}
    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: fetch_negotiation_thread(state.acc, chat_id)
    )
    return result


@router.get("/api/debug/thread_raw/{idx}/{chat_id}")
async def api_debug_thread_raw(idx: int, chat_id: str):
    """Return raw JSON structure from /chat/messages?chatId=... for debugging."""
    if idx < len(bot.account_states):
        state = bot.account_states[idx]
    elif idx - len(bot.account_states) in bot.temp_states:
        state = bot.temp_states[idx - len(bot.account_states)]
    else:
        return {"ok": False, "error": "account not found"}
    acc = state.acc
    def _fetch():
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, */*",
            "Referer": hh_base() + "/applicant/negotiations",
        }
        try:
            resp = HH.get(
                f"{hh_base()}/chat/messages?chatId={chat_id}",
                cookies=acc["cookies"], headers=headers, timeout=15,
            )
        except requests.RequestException as e:
            return {"ok": False, "error": str(e)[:100]}
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
