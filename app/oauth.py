"""
OAuth via official Android app credentials — token management and OAuth-based operations.
"""

import json
import re
import time
import threading
from pathlib import Path
import requests

from app.logging_utils import log_debug
from app.config import CONFIG

# ── OAuth via official Android app credentials ──
_HH_OAUTH_CLIENT_ID = "HIOMIAS39CA9DICTA7JIO64LQKQJF5AGIK74G9ITJKLNEDAOH5FHS5G1JI7FOEGD"
_HH_OAUTH_CLIENT_SECRET = "V9M870DE342BGHFRUJ5FTCGCUA1482AN0DI8C5TFI9ULMA89H10N60NOP8I4JMVS"
_HH_OAUTH_REDIRECT = "hhandroid://oauthresponse"
_OAUTH_FILE = Path("data/oauth_tokens.json")
_oauth_tokens: dict = {}  # {resume_hash: {access_token, refresh_token, expires_at}}
_oauth_lock = threading.Lock()


def _load_oauth_tokens():
    """Load persisted OAuth tokens from disk."""
    global _oauth_tokens
    try:
        if _OAUTH_FILE.exists():
            with open(_OAUTH_FILE, "r", encoding="utf-8") as f:
                _oauth_tokens = json.load(f)
            log_debug(f"OAuth: loaded {len(_oauth_tokens)} tokens from disk")
    except Exception as e:
        log_debug(f"OAuth: failed to load tokens: {e}")


def _save_oauth_tokens():
    """Persist OAuth tokens to disk."""
    try:
        _OAUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_OAUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(_oauth_tokens, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_debug(f"OAuth: failed to save tokens: {e}")


# Load on import
_load_oauth_tokens()


def get_oauth_status(resume_hash: str) -> dict:
    """Return OAuth token status for display: {has_token, expires_hours, has_refresh}"""
    with _oauth_lock:
        cached = _oauth_tokens.get(resume_hash, {})
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

    with _oauth_lock:
        cached = _oauth_tokens.get(resume_hash)
        if cached and cached.get("expires_at", 0) > time.time() + 300:
            return cached["access_token"]

    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    # Try refresh first
    with _oauth_lock:
        cached = _oauth_tokens.get(resume_hash, {})
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
                with _oauth_lock:
                    _oauth_tokens[resume_hash] = {
                        "access_token": d["access_token"],
                        "refresh_token": d.get("refresh_token", refresh),
                        "expires_at": time.time() + d.get("expires_in", 1209599),
                    }
                _save_oauth_tokens()
                log_debug(f"OAuth: refreshed token for {resume_hash[:12]}")
                return d["access_token"]
        except Exception as e:
            log_debug(f"OAuth refresh error: {e}")

    # Full authorize flow using cookies
    try:
        cookies = acc.get("cookies", {})
        # Step 1: GET authorize
        r1 = requests.get("https://hh.ru/oauth/authorize", params={
            "response_type": "code",
            "client_id": _HH_OAUTH_CLIENT_ID,
            "redirect_uri": _HH_OAUTH_REDIRECT,
            "state": "botstate",
        }, headers={"User-Agent": ua}, cookies=cookies, timeout=15, allow_redirects=False)

        code = None
        loc = r1.headers.get("Location", "")
        m = re.search(r"code=([^&]+)", loc)
        if m:
            code = m.group(1)
        elif r1.status_code == 200 and ("разрешить" in r1.text.lower() or "approve" in r1.text.lower() or "grant" in r1.text.lower()):
            # Submit approve form
            r2 = requests.post("https://hh.ru/oauth/authorize", data={
                "response_type": "code",
                "client_id": _HH_OAUTH_CLIENT_ID,
                "redirect_uri": _HH_OAUTH_REDIRECT,
                "state": "botstate",
                "action": "approve",
                "_xsrf": cookies.get("_xsrf", ""),
            }, headers={"User-Agent": ua}, cookies=cookies, timeout=15, allow_redirects=False)
            loc2 = r2.headers.get("Location", "")
            m2 = re.search(r"code=([^&]+)", loc2)
            if m2:
                code = m2.group(1)

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
            with _oauth_lock:
                _oauth_tokens[resume_hash] = {
                    "access_token": d["access_token"],
                    "refresh_token": d.get("refresh_token", ""),
                    "expires_at": time.time() + d.get("expires_in", 1209599),
                }
            _save_oauth_tokens()
            log_debug(f"OAuth: obtained token for {resume_hash[:12]}, expires in {d.get('expires_in',0)}s")
            return d["access_token"]
        else:
            log_debug(f"OAuth: token exchange failed {r3.status_code}: {r3.text[:200]}")
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
            return "auth_error", {}
        elif r.status_code == 404:
            return "error", {"raw": "Вакансия не найдена"}
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
