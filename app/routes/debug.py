"""
Debug endpoints for inspecting HH SSR, chats, and account state.
"""

import asyncio
import json
import re

import requests
from fastapi import APIRouter

from app.hh_chat import fetch_negotiation_thread
from app.hh_resume import parse_hh_lux_ssr
from app.instances import bot


router = APIRouter()


@router.get("/api/debug/session/{idx}")
async def api_debug_session(idx: int):
    """Показать SSR структуру для браузерной сессии (для отладки resume_hash)."""
    temp_idx = idx - len(bot.account_states)
    if temp_idx < 0 or temp_idx >= len(bot.temp_sessions):
        return {"error": "session not found"}
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
        r = requests.get("https://hh.ru/applicant/resumes", headers=headers, timeout=15)
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
    result = await loop.run_in_executor(None, _fetch)
    return result


_SESSION_REDACT_KEYS = {"cookies", "_raw_cookie_line", "raw_cookie_line", "api_key"}


def _safe_session_dict(s: dict) -> dict:
    """Strip raw cookie line and any other sensitive fields before returning to client."""
    return {k: v for k, v in s.items() if k not in _SESSION_REDACT_KEYS}


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
    chat_ids_any = re.findall(r'"(?:chatId|chat_id|topicId|topic_id|negotiationId|id)"\s*:\s*(\d{8,})', body)
    initial_state_match = re.search(r'window\.__(?:INITIAL_STATE|REDUX_STATE|DATA)__\s*=\s*(\{.*?\});', body[:200000], re.DOTALL)
    initial_state_keys = []
    if initial_state_match:
        try:
            _data = json.loads(initial_state_match.group(1))
            initial_state_keys = list(_data.keys())[:20]
        except Exception:
            initial_state_keys = ["parse_error"]
    script_jsons = re.findall(r'<script[^>]*>\s*(?:var|const|window\.\w+)\s*=\s*(\{[^<]{100,})', body[:200000])
    script_json_keys = []
    for sj in script_jsons[:3]:
        try:
            _d = json.loads(sj)
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


@router.get("/api/debug/thread/{idx}/{chat_id}")
async def api_debug_thread(idx: int, chat_id: str):
    """Test fetch_negotiation_thread for a given chatId using account idx."""
    if idx < len(bot.account_states):
        state = bot.account_states[idx]
    elif idx - len(bot.account_states) in bot.temp_states:
        state = bot.temp_states[idx - len(bot.account_states)]
    else:
        return {"error": "account not found"}
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
        return {"error": "account not found"}
    acc = state.acc
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
