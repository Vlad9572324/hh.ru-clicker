"""
LLM configuration and control routes.
"""

import os
import threading

import requests
from fastapi import APIRouter, Request

from app.logging_utils import log_debug
from app.config import CONFIG, save_config
from app.instances import bot
from app.llm import _openclaw_command


router = APIRouter()


def _llm_proxies():
    """proxies-dict для requests к LLM-провайдеру, если задан env LLM_PROXY.

    Держим тест-коннект и реальные вызовы (см. app.llm._make_openai_client) на
    одном прокси — иначе проверка ключа падает с РФ-IP, хотя сам чат работает.
    """
    proxy = os.environ.get("LLM_PROXY", "").strip()
    return {"http": proxy, "https": proxy} if proxy else None


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
    if api_key.startswith("sk-ant-"):
        # Anthropic claude — есть OpenAI-compat shim:
        return "https://api.anthropic.com/v1"
    if api_key.startswith("AIza"):
        # Google Gemini (Google AI Studio key) — OpenAI-compatible endpoint
        # https://ai.google.dev/gemini-api/docs/openai
        return "https://generativelanguage.googleapis.com/v1beta/openai"
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
        # Ключ (type=password) не подставляется из snap в UI, значит autosave
        # шлёт api_key='' если юзер сам не перепечатал ключ. Не потерять его:
        # (1) сначала strict match по (name+base_url+model),
        # (2) fallback по name — иначе смена модели/URL стирала ключ (issue: user).
        # (3) последний fallback — по индексу, если имена все пустые.
        def _identity(p):
            return (
                str(p.get("name", "")).strip(),
                str(p.get("base_url", "")).strip(),
                str(p.get("model", "")).strip(),
            )
        old_profiles = CONFIG.llm_profiles or []
        old_by_identity = {_identity(p): p for p in old_profiles}
        old_by_name = {str(p.get("name", "")).strip(): p for p in old_profiles if p.get("api_key")}
        for i, p in enumerate(profiles):
            if p.get("api_key"):
                continue
            # (1) strict
            ident = _identity(p)
            if ident in old_by_identity and old_by_identity[ident].get("api_key"):
                p["api_key"] = old_by_identity[ident]["api_key"]
                continue
            # (2) by name
            name = str(p.get("name", "")).strip()
            if name and name in old_by_name:
                p["api_key"] = old_by_name[name]["api_key"]
                continue
            # (3) by index (когда имена одинаковые/пустые)
            if i < len(old_profiles) and old_profiles[i].get("api_key"):
                p["api_key"] = old_profiles[i]["api_key"]
        CONFIG.llm_profiles = profiles
        if profiles:
            first = profiles[0]
            # legacy-поле обновляем ТОЛЬКО если первый профиль сохранил свой api_key
            # (после fallback выше). Иначе оставляем что было — иначе стёрлось бы
            # старое рабочее значение legacy-ключа.
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
    def _truthy(v):
        # strict bool: "false"/"0"/"no" → False, иначе bool(v).
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "on")
        return False

    if "enabled" in body:
        CONFIG.llm_enabled = _truthy(body["enabled"])
    if "auto_send" in body:
        CONFIG.llm_auto_send = _truthy(body["auto_send"])
    if "use_cover_letter" in body:
        CONFIG.llm_use_cover_letter = _truthy(body["use_cover_letter"])
    if "use_resume" in body:
        CONFIG.llm_use_resume = _truthy(body["use_resume"])
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


_llm_run_now_lock = threading.Lock()
_llm_run_now_last: float = 0.0
_LLM_RUN_NOW_COOLDOWN = 60  # сек — минимум между принудительными запусками


@router.post("/api/llm_run_now")
async def api_llm_run_now():
    """Принудительно запустить LLM авто-ответы для всех аккаунтов прямо сейчас (в фоне).

    Rate-limit: cooldown между запусками + одновременно может идти только один _run,
    чтобы spam endpoint'а не плодил daemon-thread'ы и не жёг токены (swarm-3 #7).
    """
    global _llm_run_now_last
    import time as _time
    # Pre-flight: проверки конфига ДО загрузки чат-листов с HH (raw_config-уровень).
    # Если LLM глобально выключен или нет ни одного рабочего профиля — впустую
    # тащить список чатов и потом вылетать в цикле нет смысла.
    if not CONFIG.llm_enabled:
        return {"started": False, "error": "LLM глобально выключен — включи большой тумблер на этой вкладке"}
    _has_llm = (CONFIG.llm_api_key or "").strip() or any(
        p.get("api_key") for p in (CONFIG.llm_profiles or []) if p.get("enabled", True)
    ) or (getattr(CONFIG, "llm_openclaw_enabled", False) and bool(_openclaw_command()))
    # HH-quick_replies работают без своего LLM (HH сам генерит подсказки) —
    # если этот флаг вкл, разрешаем прогон даже без API-ключей / OpenClaw.
    _use_qr = getattr(CONFIG, "llm_use_quick_replies", True)
    if not _has_llm and not _use_qr:
        return {"started": False, "error": "Не настроен ни один LLM-провайдер: API-профили или OpenClaw"}
    now = _time.time()
    if now - _llm_run_now_last < _LLM_RUN_NOW_COOLDOWN:
        wait = int(_LLM_RUN_NOW_COOLDOWN - (now - _llm_run_now_last))
        return {"started": False, "error": f"Cooldown — повторите через {wait}с"}
    if not _llm_run_now_lock.acquire(blocking=False):
        return {"started": False, "error": "Предыдущий запуск ещё идёт"}
    _llm_run_now_last = now

    def _run():
        try:
            states = list(bot.account_states) + list(bot.temp_states.values())
            for state in states:
                try:
                    bot._process_llm_replies(state)
                except Exception as e:
                    log_debug(f"llm_run_now {state.short}: {e}")
        finally:
            _llm_run_now_lock.release()
    threading.Thread(target=_run, daemon=True).start()
    return {"started": True, "accounts": len(bot.account_states) + len(bot.temp_states)}


@router.post("/api/llm_reset_replied")
async def api_llm_reset_replied():
    """Сбросить историю отправленных LLM-ответов для всех аккаунтов.

    Round-1 #11: держим per-state + global locks чтобы clear не сносил
    резервацию сообщения in-flight.
    Round-2 #1: lock-order per-state → global (worker в этом же порядке).
    Round-3 #3: acquire с timeout в to_thread — иначе застрявший worker
    блокирует event loop (весь UI/WS зависает).
    Round-3 #4: snapshot глобального set в НАЧАЛЕ; в конце удаляем
    только эти записи, не сносим новые резервации, добавленные worker'ами
    других аккаунтов пока reset проходил свой цикл.
    """
    import asyncio
    all_states = list(bot.account_states) + list(bot.temp_states.values())

    # Snapshot глобального set до старта — только их удалим в конце.
    with bot._llm_sent_lock:
        stale_globals = set(bot._llm_sent_global)
    stale_global_count = len(stale_globals)

    def _do_reset_sync():
        cleared = []
        skipped_busy = []
        for state in all_states:
            lock = getattr(state, "_llm_lock", None)
            got = True
            if lock is not None:
                # Round-3 #3: timeout=5с. Если worker застрял на LLM API →
                # skip state, не блокируем reset и event loop бесконечно.
                got = lock.acquire(timeout=5)
                if not got:
                    skipped_busy.append(state.short)
                    continue
            try:
                with bot._llm_sent_lock:
                    n_replied = len(state.llm_replied_msgs)
                    n_skip = len(state._llm_temp_skip)
                    n_no_chat = len(state._llm_no_chat)
                    n_drafts = len(getattr(state, "_llm_drafts", {}) or {})
                    state.llm_replied_msgs.clear()
                    state._llm_temp_skip.clear()
                    state._llm_no_chat.clear()
                    if hasattr(state, "_llm_drafts"):
                        state._llm_drafts.clear()
                    cleared.append({"acc": state.short, "replied_cleared": n_replied,
                                    "skip_cleared": n_skip, "no_chat_cleared": n_no_chat,
                                    "drafts_cleared": n_drafts})
            finally:
                if lock is not None and got:
                    lock.release()
        # Round-3 #4: удаляем ТОЛЬКО stale-snapshot ключи. Новые резервации,
        # добавленные worker'ами пока мы шли по states, останутся защищены.
        with bot._llm_sent_lock:
            bot._llm_sent_global.difference_update(stale_globals)
        return cleared, skipped_busy

    # Round-3 #3: sync locks + IO — вне event loop.
    cleared, skipped_busy = await asyncio.get_event_loop().run_in_executor(None, _do_reset_sync)
    bot._add_log("system", "green",
                 f"\U0001f916 История LLM-ответов сброшена для {len(cleared)} аккаунтов + "
                 f"{stale_global_count} глобальных записей" +
                 (f" (пропущено занятых: {', '.join(skipped_busy)})" if skipped_busy else ""),
                 "success")
    return {"ok": True, "cleared": cleared, "global_cleared": stale_global_count,
            "skipped_busy": skipped_busy}


_LLM_DETECT_ALLOWED_HOSTS = {
    "api.openai.com",
    "api.anthropic.com",
    "openrouter.ai",
    "api.together.xyz",
    "api.groq.com",
    "api.deepseek.com",
    "api.mistral.ai",
    "api.perplexity.ai",
    "api.cohere.com",
    "generativelanguage.googleapis.com",
}


def _is_safe_llm_base_url(url: str) -> bool:
    """Reject SSRF vectors: only https + known provider hosts."""
    from urllib.parse import urlparse
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme != "https" or not p.hostname:
        return False
    host = p.hostname.lower()
    # Reject private/internal addresses outright
    if host in ("localhost", "0.0.0.0") or host.startswith("127.") or host.endswith(".local"):
        return False
    # Reject IP-literal addresses
    if any(host.startswith(p) for p in ("10.", "172.", "192.168.", "169.254.", "::1", "fc", "fd")):
        return False
    return host in _LLM_DETECT_ALLOWED_HOSTS


@router.get("/api/llm/usage")
async def api_llm_usage():
    """Вернуть агрегированные счётчики использования LLM по аккаунтам."""
    from app.llm import get_llm_usage
    return {"per_account": get_llm_usage()}


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
    if not _is_safe_llm_base_url(base_url):
        return {"ok": False, "error": "base_url не из списка разрешённых LLM-провайдеров"}
    try:
        resp = requests.get(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=12,
            proxies=_llm_proxies(),
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
