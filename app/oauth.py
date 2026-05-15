"""
OAuth via official Android app credentials — token management and OAuth-based operations.
"""

import hashlib
import json
import os
import re
import secrets
import time
import threading
from pathlib import Path
import requests

from app.logging_utils import log_debug
from app.config import CONFIG

# Эти креды извлечены из публичного APK HH Android и широко известны.
# Не секрет: но желательно вынести в env для возможности замены.
_HH_OAUTH_CLIENT_ID = os.environ.get(
    "HH_OAUTH_CLIENT_ID",
    "HIOMIAS39CA9DICTA7JIO64LQKQJF5AGIK74G9ITJKLNEDAOH5FHS5G1JI7FOEGD",
)
_HH_OAUTH_CLIENT_SECRET = os.environ.get(
    "HH_OAUTH_CLIENT_SECRET",
    "V9M870DE342BGHFRUJ5FTCGCUA1482AN0DI8C5TFI9ULMA89H10N60NOP8I4JMVS",
)
_HH_OAUTH_REDIRECT = "hhandroid://oauthresponse"
_OAUTH_FILE = Path("data/oauth_tokens.json")
_oauth_tokens: dict = {}  # {resume_hash or resume_hash::account_key: {access_token, refresh_token, expires_at}}
_oauth_lock = threading.Lock()
_oauth_save_lock = threading.Lock()  # сериализует tmp+replace, чтобы не интерливить файл

# Per-account locks для refresh/authorize: иначе два потока могут одновременно
# увидеть expired token и оба пойти refresh с одним и тем же refresh_token.
# HH ротирует refresh tokens — второй запрос получит invalid_grant. (swarm-7 #1)
_oauth_refresh_locks: dict = {}  # {resume_hash: threading.Lock}
_oauth_refresh_locks_lock = threading.Lock()


def _account_key(acc: dict) -> str:
    """Stable per-account hash based on hhtoken cookie or short name."""
    raw = acc.get("cookies", {}).get("hhtoken", "") or acc.get("short", "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _token_key(acc: dict) -> str:
    """Composite key to isolate tokens per-account even when resume_hash is shared."""
    resume_hash = acc.get("resume_hash", "")
    if not resume_hash:
        return ""
    return f"{resume_hash}::{_account_key(acc)}"


def _get_refresh_lock(resume_hash: str) -> threading.Lock:
    with _oauth_refresh_locks_lock:
        lock = _oauth_refresh_locks.get(resume_hash)
        if lock is None:
            lock = threading.Lock()
            _oauth_refresh_locks[resume_hash] = lock
        return lock


def invalidate_oauth_token(resume_hash: str, acc: dict = None) -> None:
    """Удалить кэшированный токен (на 401/403 от API). После вызова следующий
    `_obtain_oauth_token` сделает свежий refresh или authorize."""
    if not resume_hash:
        return
    with _oauth_lock:
        removed = False
        if resume_hash in _oauth_tokens:
            _oauth_tokens.pop(resume_hash, None)
            removed = True
        if acc:
            comp = _token_key(acc)
            if comp in _oauth_tokens:
                _oauth_tokens.pop(comp, None)
                removed = True
        else:
            prefix = f"{resume_hash}::"
            for k in list(_oauth_tokens.keys()):
                if k.startswith(prefix):
                    _oauth_tokens.pop(k, None)
                    removed = True
        if removed:
            _save_oauth_tokens()
            log_debug(f"OAuth: invalidated token for {resume_hash[:12]} (auth_error)")


def _load_oauth_tokens():
    """Load persisted OAuth tokens from disk.
    Backward compatible: supports both plain resume_hash keys and composite keys."""
    global _oauth_tokens
    try:
        if _OAUTH_FILE.exists():
            with open(_OAUTH_FILE, "r", encoding="utf-8") as f:
                _oauth_tokens = json.load(f)
            log_debug(f"OAuth: loaded {len(_oauth_tokens)} tokens from disk")
    except Exception as e:
        log_debug(f"OAuth: failed to load tokens: {e}")


def _save_oauth_tokens():
    """Atomic persist (tmp + replace) of OAuth tokens to disk."""
    with _oauth_save_lock:
        try:
            _OAUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
            with _oauth_lock:
                snapshot = dict(_oauth_tokens)
            tmp = _OAUTH_FILE.with_suffix(".tmp")
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, ensure_ascii=False, indent=2)
                tmp.replace(_OAUTH_FILE)
            except Exception as e:
                log_debug(f"OAuth: failed to save tokens: {e}")
                tmp.unlink(missing_ok=True)
        except Exception as e:
            log_debug(f"OAuth: save outer error: {e}")


# Load on import
_load_oauth_tokens()


def get_oauth_status(resume_hash: str) -> dict:
    """Return OAuth token status for display: {has_token, expires_hours, has_refresh}"""
    with _oauth_lock:
        cached = _oauth_tokens.get(resume_hash, {})
        if not cached:
            # fallback to composite key
            prefix = f"{resume_hash}::"
            for k, v in _oauth_tokens.items():
                if k.startswith(prefix):
                    cached = v
                    break
    if not cached:
        return {"has_token": False, "expires_hours": 0, "has_refresh": False}
    exp = cached.get("expires_at", 0)
    remaining = max(0, int((exp - time.time()) / 3600))
    return {
        "has_token": exp > time.time(),
        "expires_hours": remaining,
        "has_refresh": bool(cached.get("refresh_token")),
    }


def _obtain_oauth_token(acc: dict) -> str:
    """Get OAuth access_token for account. Auto-refresh if expired. Returns token or empty string."""
    resume_hash = acc.get("resume_hash", "")
    if not resume_hash:
        return ""
    key = _token_key(acc)

    def _is_cached_valid(cached: dict) -> bool:
        if not cached:
            return False
        exp = cached.get("expires_at", 0)
        if exp <= time.time() + 300:
            return False
        mono = cached.get("_expires_monotonic")
        if mono is not None and time.monotonic() >= mono:
            return False
        return True

    with _oauth_lock:
        cached = _oauth_tokens.get(key)
        if not cached:
            # Migrate old plain-key token if present
            old = _oauth_tokens.get(resume_hash)
            if old:
                _oauth_tokens[key] = dict(old)
                cached = _oauth_tokens[key]
        if _is_cached_valid(cached):
            return cached["access_token"]

    # Сериализуем refresh/authorize per-account: один поток делает HTTP, остальные ждут.
    refresh_lock = _get_refresh_lock(resume_hash)
    with refresh_lock:
        # Double-checked: пока ждали лок, другой поток мог уже обновить токен.
        with _oauth_lock:
            cached = _oauth_tokens.get(key)
            if not cached:
                old = _oauth_tokens.get(resume_hash)
                if old:
                    _oauth_tokens[key] = dict(old)
                    cached = _oauth_tokens[key]
            if _is_cached_valid(cached):
                return cached["access_token"]

        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        # Try refresh first
        with _oauth_lock:
            cached = _oauth_tokens.get(key, {})
        refresh = cached.get("refresh_token", "")
        if refresh:
            try:
                r = requests.post("https://hh.ru/oauth/token", data={
                    "grant_type": "refresh_token",
                    "client_id": _HH_OAUTH_CLIENT_ID,
                    "client_secret": _HH_OAUTH_CLIENT_SECRET,
                    "refresh_token": refresh,
                }, headers={"User-Agent": ua}, timeout=15)
                if r.status_code == 200:
                    d = r.json()
                    access_token = d.get("access_token")
                    if not access_token:
                        log_debug(f"OAuth: refresh response missing access_token for {resume_hash[:12]}")
                    else:
                        # Не перетираем валидный refresh_token пустым (HH может опустить).
                        new_refresh = d.get("refresh_token") or refresh
                        expires_in = d.get("expires_in", 1209599)
                        token_data = {
                            "access_token": access_token,
                            "refresh_token": new_refresh,
                            "expires_at": time.time() + expires_in,
                            "_expires_monotonic": time.monotonic() + expires_in,
                        }
                        with _oauth_lock:
                            _oauth_tokens[key] = token_data
                            # backward-compat plain key for external readers
                            _oauth_tokens[resume_hash] = {
                                k: v for k, v in token_data.items() if not k.startswith("_")
                            }
                        _save_oauth_tokens()
                        log_debug(f"OAuth: refreshed token for {resume_hash[:12]}")
                        return access_token
            except Exception as e:
                log_debug(f"OAuth refresh error: {e}")

        # Full authorize flow using cookies (по-прежнему под refresh_lock)
        try:
            cookies = acc.get("cookies", {})
            # Random per-request state защищает от accept'a чужого code-redirect (CSRF)
            flow_state = secrets.token_urlsafe(24)

            def _extract_code(location: str) -> str:
                """Извлечь code только если state совпадает с нашим."""
                if not location:
                    return ""
                state_m = re.search(r"[?&]state=([^&]+)", location)
                if state_m and state_m.group(1) != flow_state:
                    # Не логируем сам state — это per-request secret (swarm-16 #3).
                    log_debug(f"OAuth: state mismatch — rejecting code for {resume_hash[:12]}")
                    return ""
                code_m = re.search(r"[?&]code=([^&]+)", location)
                return code_m.group(1) if code_m else ""

            # Step 1: GET authorize
            r1 = requests.get("https://hh.ru/oauth/authorize", params={
                "response_type": "code",
                "client_id": _HH_OAUTH_CLIENT_ID,
                "redirect_uri": _HH_OAUTH_REDIRECT,
                "state": flow_state,
            }, headers={"User-Agent": ua}, cookies=cookies, timeout=15, allow_redirects=False)

            code = _extract_code(r1.headers.get("Location", ""))
            if not code and r1.status_code == 200 and (
                "разрешить" in r1.text.lower() or "approve" in r1.text.lower() or "grant" in r1.text.lower()
            ):
                # Submit approve form
                r2 = requests.post("https://hh.ru/oauth/authorize", data={
                    "response_type": "code",
                    "client_id": _HH_OAUTH_CLIENT_ID,
                    "redirect_uri": _HH_OAUTH_REDIRECT,
                    "state": flow_state,
                    "action": "approve",
                    "_xsrf": cookies.get("_xsrf", ""),
                }, headers={"User-Agent": ua}, cookies=cookies, timeout=15, allow_redirects=False)
                code = _extract_code(r2.headers.get("Location", ""))

            if not code:
                log_debug(f"OAuth: failed to get code for {resume_hash[:12]}")
                return ""

            # Step 2: Exchange code for token
            r3 = requests.post("https://hh.ru/oauth/token", data={
                "grant_type": "authorization_code",
                "client_id": _HH_OAUTH_CLIENT_ID,
                "client_secret": _HH_OAUTH_CLIENT_SECRET,
                "redirect_uri": _HH_OAUTH_REDIRECT,
                "code": code,
            }, headers={"User-Agent": ua, "Content-Type": "application/x-www-form-urlencoded"}, timeout=15)

            if r3.status_code == 200:
                d = r3.json()
                access_token = d.get("access_token")
                if not access_token:
                    log_debug(f"OAuth: authorize response missing access_token for {resume_hash[:12]}")
                    return ""
                # Не сохраняем пустой refresh_token поверх существующего.
                existing_refresh = cached.get("refresh_token", "")
                new_refresh = d.get("refresh_token") or existing_refresh
                expires_in = d.get("expires_in", 1209599)
                token_data = {
                    "access_token": access_token,
                    "refresh_token": new_refresh,
                    "expires_at": time.time() + expires_in,
                    "_expires_monotonic": time.monotonic() + expires_in,
                }
                with _oauth_lock:
                    _oauth_tokens[key] = token_data
                    # backward-compat plain key for external readers
                    _oauth_tokens[resume_hash] = {
                        k: v for k, v in token_data.items() if not k.startswith("_")
                    }
                _save_oauth_tokens()
                log_debug(f"OAuth: obtained token for {resume_hash[:12]}, expires in {d.get('expires_in', 0)}s")
                return access_token
            else:
                # Логируем только status, не raw body (может содержать code в URL → leak).
                log_debug(f"OAuth: token exchange failed {r3.status_code} for {resume_hash[:12]}")
        except Exception as e:
            log_debug(f"OAuth: authorize error: {e}")
        return ""


def _oauth_apply(acc: dict, vid: str, message: str = "") -> tuple:
    """Apply to vacancy via OAuth API. Returns (result_str, info_dict)."""
    from app.llm import _randomize_text
    token = _obtain_oauth_token(acc)
    if not token:
        return "error", {"exception": "OAuth token не получен"}
    resume_hash = acc.get("resume_hash", "")
    try:
        message = _randomize_text(message) if message else message
        data = {"vacancy_id": vid, "resume_id": resume_hash}
        if message:
            data["message"] = message
        r = requests.post(
            "https://api.hh.ru/negotiations",
            headers={"User-Agent": "Mozilla/5.0", "Authorization": f"Bearer {token}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data=data, timeout=15,
        )
        if r.status_code in (200, 201, 204):
            # Success — try to get vacancy info
            info = {}
            try:
                d = r.json()
                info = {"title": d.get("vacancy", {}).get("name", ""),
                        "company": d.get("vacancy", {}).get("employer", {}).get("name", "")}
            except Exception:
                pass
            return "sent", info
        elif r.status_code == 400:
            try:
                d = r.json()
            except Exception:
                return "error", {"raw": r.text[:100]}
            err = d.get("errors", [{}])[0].get("value", d.get("description", ""))
            if "limit" in err.lower():
                return "limit", {}
            if "already" in err.lower() or "exist" in err.lower():
                return "already", {}
            if "test" in err.lower():
                return "test", {}
            return "error", {"raw": err}
        elif r.status_code in (401, 403):
            # Очищаем кэшированный токен: иначе manager на каждом следующем apply
            # будет переиспользовать тот же rejected токен → бесконечная петля 401.
            log_debug(f"OAuth apply auth_error for {resume_hash[:12]} vid={vid}")
            invalidate_oauth_token(resume_hash, acc)
            return "auth_error", {}
        elif r.status_code == 404:
            return "error", {"raw": "Вакансия не найдена"}
        elif r.status_code == 429:
            # Rate-limit от HH — не считаем permanent error (раньше manager
            # auto-pause'ил account на 429 как на consecutive_errors).
            retry_after = 0
            try:
                retry_after = int(r.headers.get("Retry-After", "0"))
            except (ValueError, TypeError):
                pass
            return "limit", {"retry_after": retry_after}
        elif r.status_code in (502, 503, 504):
            return "error", {"raw": f"HH transient {r.status_code}", "transient": True}
        else:
            return "error", {"raw": f"HTTP {r.status_code}: {r.text[:100]}"}
    except Exception as e:
        return "error", {"exception": str(e)}


def _oauth_touch_resume(acc: dict) -> tuple:
    """Touch resume via OAuth API (no captcha). Returns (success, message)."""
    token = _obtain_oauth_token(acc)
    if not token:
        return False, "OAuth token не получен"
    resume_hash = acc.get("resume_hash", "")
    try:
        r = requests.post(
            f"https://api.hh.ru/resumes/{resume_hash}/publish",
            headers={"User-Agent": "Mozilla/5.0", "Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if r.status_code in (200, 204):
            return True, "✅ Резюме поднято через OAuth API!"
        elif r.status_code == 429:
            return False, "Кулдаун (429) — подождите 4 часа"
        else:
            return False, f"HTTP {r.status_code}: {r.text[:100]}"
    except Exception as e:
        return False, f"Ошибка: {str(e)[:50]}"
