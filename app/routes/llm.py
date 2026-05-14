"""
LLM configuration and control routes.
"""

import threading

import requests
from fastapi import APIRouter, Request

from app.logging_utils import log_debug
from app.config import CONFIG, save_config
from app.instances import bot


router = APIRouter()


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
    if api_key.startswith("sk-") and len(api_key) < 45:
        return "https://api.deepseek.com"
    return "https://api.openai.com/v1"


@router.post("/api/llm_profiles")
async def api_llm_profiles(request: Request):
    """Save LLM multi-profile configuration."""
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "bad json"}
    profiles = body.get("profiles")
    mode = body.get("mode", "fallback")
    if isinstance(profiles, list):
        old_by_idx = {i: p for i, p in enumerate(CONFIG.llm_profiles or [])}
        for i, p in enumerate(profiles):
            if not p.get("api_key") and old_by_idx.get(i, {}).get("api_key"):
                p["api_key"] = old_by_idx[i]["api_key"]
        CONFIG.llm_profiles = profiles
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


@router.post("/api/llm_toggle")
async def api_llm_toggle():
    """Toggle global LLM auto-reply on/off instantly."""
    CONFIG.llm_enabled = not CONFIG.llm_enabled
    save_config()
    bot._add_log("", "", f"\U0001f916 LLM авто-ответы {'включены' if CONFIG.llm_enabled else 'выключены'}", "success" if CONFIG.llm_enabled else "warning")
    return {"llm_enabled": CONFIG.llm_enabled}


@router.post("/api/llm_config")
async def api_llm_config(request: Request):
    """Save LLM configuration."""
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "bad json"}
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


@router.post("/api/llm_run_now")
async def api_llm_run_now():
    """Принудительно запустить LLM авто-ответы для всех аккаунтов прямо сейчас (в фоне)."""
    def _run():
        states = list(bot.account_states) + list(bot.temp_states.values())
        for state in states:
            try:
                bot._process_llm_replies(state)
            except Exception as e:
                log_debug(f"llm_run_now {state.short}: {e}")
    threading.Thread(target=_run, daemon=True).start()
    return {"started": True, "accounts": len(bot.account_states) + len(bot.temp_states)}


@router.post("/api/llm_reset_replied")
async def api_llm_reset_replied():
    """Сбросить историю отправленных LLM-ответов для всех аккаунтов."""
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
    bot._add_log("system", "green", f"\U0001f916 История LLM-ответов сброшена для {len(cleared)} аккаунтов + {n_global} глобальных записей", "success")
    return {"ok": True, "cleared": cleared, "global_cleared": n_global}


@router.post("/api/llm_detect")
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
            timeout=12,
        )
        if resp.status_code != 200:
            return {"ok": False, "base_url": base_url, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        raw_models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]
        chat_models = [m for m in raw_models if _is_chat_model(m)]
        chat_models.sort(key=lambda m: (
            "latest" in m,
            any(x in m for x in ("gpt-4", "claude", "llama-3", "deepseek", "gemini")),
        ), reverse=True)
        return {"ok": True, "base_url": base_url, "models": chat_models}
    except Exception as e:
        return {"ok": False, "base_url": base_url, "error": str(e)}
