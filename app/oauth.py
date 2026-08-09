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
import urllib.parse
from pathlib import Path
import requests

from app.logging_utils import log_debug
from app.config import CONFIG
from app.hh_http import HH

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
_HH_OAUTH_CLIENT_ID_2 = os.environ.get("HH_OAUTH_CLIENT_ID_2", "")
_HH_OAUTH_CLIENT_SECRET_2 = os.environ.get("HH_OAUTH_CLIENT_SECRET_2", "")
_OAUTH_FILE = Path("data/oauth_tokens.json")
_oauth_tokens: dict = {}  # {resume_hash or resume_hash::account_key: {access_token, refresh_token, expires_at}}
_oauth_lock = threading.Lock()
_oauth_save_lock = threading.Lock()  # сериализует tmp+replace, чтобы не интерливить файл

# Per-account locks для refresh/authorize: иначе два потока могут одновременно
# увидеть expired token и оба пойти refresh с одним и тем же refresh_token.
# HH ротирует refresh tokens — второй запрос получит invalid_grant. (swarm-7 #1)
_oauth_refresh_locks: dict = {}  # {resume_hash: threading.Lock}
_oauth_refresh_locks_lock = threading.Lock()

_DEFAULT_MOBILE_USER_AGENT = (
    "ru.hh.android/26.29.11476, Device: Pixel 10, Android OS: 17 "
    "(UUID: 8f42e879-43c7-4d86-a671-31ea36ed924b)"
)


def _mobile_user_agent() -> str:
    """Return the APK-compatible User-Agent from the editable mobile settings."""
    try:
        from app.mobile_auth import effective_config

        cfg, _ = effective_config()
        return cfg.user_agent
    except Exception as exc:
        log_debug(f"OAuth: failed to load mobile User-Agent: {exc}")
        return _DEFAULT_MOBILE_USER_AGENT


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
    `_obtain_oauth_token` сделает свежий refresh или authorize.

    ⚠️ `_save_oauth_tokens()` ВНЕ `_oauth_lock` — иначе deadlock: save тоже
    пытается взять `_oauth_lock` для snapshot (issue #19).
    """
    if not resume_hash:
        return
    removed = False
    with _oauth_lock:
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
                try:
                    os.chmod(_OAUTH_FILE, 0o600)  # secrets — owner-only
                except Exception:
                    pass
            except Exception as e:
                log_debug(f"OAuth: failed to save tokens: {e}")
                tmp.unlink(missing_ok=True)
        except Exception as e:
            log_debug(f"OAuth: save outer error: {e}")


# Load on import
_load_oauth_tokens()
# One-shot chmod на existing file — r12-2 #7: pre-r8 install мог оставить 0o644.
try:
    if _OAUTH_FILE.exists():
        os.chmod(_OAUTH_FILE, 0o600)
except Exception:
    pass


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


def import_mobile_tokens(tokens: dict, resumes: list[dict], me: dict | None = None) -> int:
    """Atomically merge an OTP token response into the existing OAuth store.

    A plain resume-id key is intentionally used for compatibility with old accounts.
    Existing entries are replaced only after the complete input has been validated.
    """
    if not isinstance(tokens, dict) or not tokens.get("access_token"):
        raise ValueError("mobile token response has no access_token")
    now = int(time.time())
    expires_at = tokens.get("expires_at")
    if expires_at is None:
        expires_at = now + int(tokens.get("expires_in", 1209599))
    clean = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "expires_in": int(tokens.get("expires_in", max(0, int(expires_at) - now))),
        "expires_at": int(expires_at),
        "obtained_at": int(tokens.get("obtained_at", now)),
        "source": "mobile_otp",
    }
    keys = [str(r.get("id") or "").strip() for r in resumes if isinstance(r, dict)]
    keys = list(dict.fromkeys(k for k in keys if k))
    if not keys and isinstance(me, dict) and me.get("id") is not None:
        keys = [f"mobile-user-{me['id']}"]
    if not keys:
        raise ValueError("cannot associate mobile tokens with a user or resume")
    with _oauth_lock:
        for key in keys:
            _oauth_tokens[key] = dict(clean)
    # Save outside _oauth_lock: _save_oauth_tokens takes the same lock for its snapshot.
    _save_oauth_tokens()
    return len(keys)


def remove_mobile_tokens() -> int:
    """Remove only tokens created by the mobile OTP flow."""
    removed = 0
    with _oauth_lock:
        for key in list(_oauth_tokens):
            if isinstance(_oauth_tokens.get(key), dict) and _oauth_tokens[key].get("source") == "mobile_otp":
                _oauth_tokens.pop(key, None)
                removed += 1
    if removed:
        # Save outside _oauth_lock (see import_mobile_tokens above).
        _save_oauth_tokens()
    return removed


def _refresh_identity(cached: dict, fallback_ua: str) -> tuple[str, str, str]:
    """Select OAuth credentials while always presenting the configured Android UA."""
    mobile_ua = _mobile_user_agent()
    if cached.get("source") == "mobile_otp":
        try:
            from app.mobile_auth import effective_config
            cfg, _ = effective_config()
            return cfg.oauth_client_id, cfg.oauth_client_secret, mobile_ua
        except Exception:
            pass
    return _HH_OAUTH_CLIENT_ID, _HH_OAUTH_CLIENT_SECRET, mobile_ua


def _do_refresh(refresh: str, client_id: str, client_secret: str, ua: str, resume_hash: str = ""):
    """Refresh token. Returns token dict on success, None if invalid_client (fallback needed), {} on other failure."""
    try:
        r = HH.post("https://hh.ru/oauth/token", data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
        }, headers={"User-Agent": ua}, timeout=15)
        if r.status_code == 200:
            d = r.json()
            access_token = d.get("access_token")
            if access_token:
                return {
                    "access_token": access_token,
                    "refresh_token": d.get("refresh_token") or refresh,
                    "expires_in": d.get("expires_in", 1209599),
                }
            if resume_hash:
                log_debug(f"OAuth: refresh response missing access_token for {resume_hash[:12]}")
            return {}
        if r.status_code == 400:
            try:
                err = r.json().get("error", "")
            except Exception:
                err = ""
            if err == "invalid_client":
                return None
        if resume_hash:
            log_debug(f"OAuth: refresh failed {r.status_code} for {resume_hash[:12]}")
        return {}
    except Exception as e:
        log_debug(f"OAuth refresh error: {e}")
        return {}


def _do_token_exchange(code: str, client_id: str, client_secret: str, redirect_uri: str, ua: str, resume_hash: str = ""):
    """Exchange code for token. Returns token dict on success, None if invalid_client (fallback needed), {} on other failure."""
    try:
        r = HH.post("https://hh.ru/oauth/token", data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        }, headers={"User-Agent": ua, "Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
        if r.status_code == 200:
            d = r.json()
            access_token = d.get("access_token")
            if access_token:
                return {
                    "access_token": access_token,
                    "refresh_token": d.get("refresh_token", ""),
                    "expires_in": d.get("expires_in", 1209599),
                }
            if resume_hash:
                log_debug(f"OAuth: authorize response missing access_token for {resume_hash[:12]}")
            return {}
        if r.status_code == 400:
            try:
                err = r.json().get("error", "")
            except Exception:
                err = ""
            if err == "invalid_client":
                return None
        if resume_hash:
            log_debug(f"OAuth: token exchange failed {r.status_code} for {resume_hash[:12]}")
        return {}
    except Exception as e:
        log_debug(f"OAuth: authorize error: {e}")
        return {}


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

        ua = _mobile_user_agent()

        # Try refresh first
        with _oauth_lock:
            cached = _oauth_tokens.get(key, {})
        refresh = cached.get("refresh_token", "")
        if refresh:
            refresh_id, refresh_secret, refresh_ua = _refresh_identity(cached, ua)
            token_data = _do_refresh(refresh, refresh_id, refresh_secret, refresh_ua, resume_hash)
            if token_data is None and cached.get("source") != "mobile_otp" and _HH_OAUTH_CLIENT_ID_2 and _HH_OAUTH_CLIENT_SECRET_2:
                token_data = _do_refresh(refresh, _HH_OAUTH_CLIENT_ID_2, _HH_OAUTH_CLIENT_SECRET_2, ua, resume_hash)
            if token_data:
                access_token = token_data["access_token"]
                new_refresh = token_data["refresh_token"]
                expires_in = token_data["expires_in"]
                token_data_full = {
                    "access_token": access_token,
                    "refresh_token": new_refresh,
                    "expires_at": time.time() + expires_in,
                    "_expires_monotonic": time.monotonic() + expires_in,
                    **({"source": "mobile_otp"} if cached.get("source") == "mobile_otp" else {}),
                }
                with _oauth_lock:
                    _oauth_tokens[key] = token_data_full
                    # backward-compat plain key for external readers
                    _oauth_tokens[resume_hash] = {
                        k: v for k, v in token_data_full.items() if not k.startswith("_")
                    }
                _save_oauth_tokens()
                log_debug(f"OAuth: refreshed token for {resume_hash[:12]}")
                return access_token

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
            r1 = HH.get("https://hh.ru/oauth/authorize", params={
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
                r2 = HH.post("https://hh.ru/oauth/authorize", data={
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
            token_data = _do_token_exchange(code, _HH_OAUTH_CLIENT_ID, _HH_OAUTH_CLIENT_SECRET, _HH_OAUTH_REDIRECT, ua, resume_hash)
            if token_data is None and _HH_OAUTH_CLIENT_ID_2 and _HH_OAUTH_CLIENT_SECRET_2:
                token_data = _do_token_exchange(code, _HH_OAUTH_CLIENT_ID_2, _HH_OAUTH_CLIENT_SECRET_2, _HH_OAUTH_REDIRECT, ua, resume_hash)
            if token_data:
                access_token = token_data["access_token"]
                existing_refresh = cached.get("refresh_token", "")
                new_refresh = token_data["refresh_token"] or existing_refresh
                expires_in = token_data["expires_in"]
                token_data_full = {
                    "access_token": access_token,
                    "refresh_token": new_refresh,
                    "expires_at": time.time() + expires_in,
                    "_expires_monotonic": time.monotonic() + expires_in,
                }
                with _oauth_lock:
                    _oauth_tokens[key] = token_data_full
                    # backward-compat plain key for external readers
                    _oauth_tokens[resume_hash] = {
                        k: v for k, v in token_data_full.items() if not k.startswith("_")
                    }
                _save_oauth_tokens()
                log_debug(f"OAuth: obtained token for {resume_hash[:12]}, expires in {expires_in}s")
                return access_token
        except Exception as e:
            log_debug(f"OAuth: authorize error: {e}")
        return ""


def refresh_oauth_tokens_proactive(min_ttl_hours: int = 48) -> dict:
    """Profilakticheski refresh: пробежать все сохранённые токены и обновить
    те, у которых до истечения меньше `min_ttl_hours` часов. Защищает
    от случая, когда аккаунт долго не используется (пауза, лимит HH) и
    refresh_token успевает истечь раньше следующего apply.

    Returns: {'checked': N, 'refreshed': K, 'failed': F}
    """
    threshold = time.time() + min_ttl_hours * 3600
    ua = _mobile_user_agent()
    with _oauth_lock:
        snapshot = list(_oauth_tokens.items())
    seen_refresh: set = set()
    stats = {"checked": 0, "refreshed": 0, "failed": 0}
    for key, cached in snapshot:
        stats["checked"] += 1
        if not isinstance(cached, dict):
            continue
        if cached.get("expires_at", 0) >= threshold:
            continue
        refresh = cached.get("refresh_token", "")
        if not refresh or refresh in seen_refresh:
            continue
        seen_refresh.add(refresh)
        resume_hash = key.split("::", 1)[0]
        # Per-resume_hash lock — синхронизируется с lazy refresh из
        # `_obtain_oauth_token`, чтобы не делать двух parallel-refresh с
        # одним и тем же refresh_token (HH ротирует → второй получает invalid_grant).
        lock = _get_refresh_lock(resume_hash)
        with lock:
            with _oauth_lock:
                latest = _oauth_tokens.get(key, {}) or {}
            if latest.get("expires_at", 0) >= threshold:
                continue  # обновили пока ждали лок
            latest_refresh = latest.get("refresh_token", "") or refresh
            refresh_id, refresh_secret, refresh_ua = _refresh_identity(latest, ua)
            token_data = _do_refresh(latest_refresh, refresh_id, refresh_secret, refresh_ua, resume_hash)
            if token_data is None and latest.get("source") != "mobile_otp" and _HH_OAUTH_CLIENT_ID_2 and _HH_OAUTH_CLIENT_SECRET_2:
                token_data = _do_refresh(latest_refresh, _HH_OAUTH_CLIENT_ID_2, _HH_OAUTH_CLIENT_SECRET_2, ua, resume_hash)
            if not token_data:
                stats["failed"] += 1
                log_debug(f"OAuth proactive: refresh failed for {resume_hash[:12]}")
                continue
            new_full = {
                "access_token": token_data["access_token"],
                "refresh_token": token_data["refresh_token"],
                "expires_at": time.time() + token_data["expires_in"],
                "_expires_monotonic": time.monotonic() + token_data["expires_in"],
                **({"source": "mobile_otp"} if latest.get("source") == "mobile_otp" else {}),
            }
            with _oauth_lock:
                _oauth_tokens[key] = new_full
                # backward-compat plain key
                _oauth_tokens[resume_hash] = {k: v for k, v in new_full.items() if not k.startswith("_")}
            _save_oauth_tokens()
            stats["refreshed"] += 1
            log_debug(f"OAuth proactive: refreshed {resume_hash[:12]} (+{token_data['expires_in']}s)")
    return stats


_extras_cache: dict = {}  # {(kind, resume_hash): (expiry_ts, value)}
_extras_lock = threading.Lock()


def _extras_get(kind: str, resume_hash: str, ttl: int, fetcher):
    """TTL cache wrapper for OAuth extras fetchers.
    Returns cached value if alive, else calls fetcher and caches result.
    Fetcher returns None on error → not cached, retry next call."""
    key = (kind, resume_hash)
    now = time.time()
    with _extras_lock:
        expiry, val = _extras_cache.get(key, (0, None))
    if expiry > now:
        return val
    try:
        val = fetcher()
    except Exception as e:
        log_debug(f"OAuth extras {kind}({resume_hash[:8]}) error: {e}")
        return None
    if val is None:
        return None
    with _extras_lock:
        _extras_cache[key] = (now + ttl, val)
    return val


def _oauth_headers(acc: dict) -> dict:
    tok = _obtain_oauth_token(acc)
    if not tok:
        return {}
    return {"User-Agent": _mobile_user_agent(), "Authorization": f"Bearer {tok}"}


def fetch_saved_vacancy_searches(acc: dict) -> list:
    """Pull user's saved vacancy searches from hh.ru.
    Returns list of {name, url, items_url} — items_url has the full search
    params already encoded, can be fed straight into _collect_via_oauth_api.
    Cached 1h."""
    rh = acc.get("resume_hash", "")
    if not rh:
        return []
    def _do():
        H = _oauth_headers(acc)
        if not H:
            return None
        out: list = []
        page = 0
        while page < 5:
            r = HH.get("https://api.hh.ru/saved_searches/vacancies",
                             headers=H, params={"per_page": 50, "page": page}, timeout=5)
            if r.status_code != 200:
                break
            d = r.json()
            for it in d.get("items", []):
                out.append({
                    "id": str(it.get("id", "")),
                    "name": it.get("name", "") or "—",
                    "items_url": it.get("items", {}).get("url", "") or it.get("url", ""),
                    "new_count": int(it.get("new_items", {}).get("count", 0) or 0),
                })
            if page + 1 >= d.get("pages", 0):
                break
            page += 1
        return out
    return _extras_get("saved_searches", rh, 3600, _do) or []


def fetch_favorited_vacancies(acc: dict) -> list:
    """User's favorited vacancies. Returns list of vid strings (just the ids).
    Cached 30 min."""
    rh = acc.get("resume_hash", "")
    if not rh:
        return []
    def _do():
        H = _oauth_headers(acc)
        if not H:
            return None
        ids: list = []
        page = 0
        while page < 5:
            r = HH.get("https://api.hh.ru/vacancies/favorited",
                             headers=H, params={"per_page": 50, "page": page}, timeout=5)
            if r.status_code != 200:
                break
            d = r.json()
            for it in d.get("items", []):
                vid = str(it.get("id", "") or "")
                if vid:
                    ids.append(vid)
            if page + 1 >= d.get("pages", 0):
                break
            page += 1
        return ids
    return _extras_get("favorited", rh, 1800, _do) or []


def fetch_blacklisted_vacancies(acc: dict) -> set:
    """User's blacklisted vacancies. Returns set of vid strings.
    Cached 30 min."""
    rh = acc.get("resume_hash", "")
    if not rh:
        return set()
    def _do():
        H = _oauth_headers(acc)
        if not H:
            return None
        ids: set = set()
        page = 0
        while page < 5:
            r = HH.get("https://api.hh.ru/vacancies/blacklisted",
                             headers=H, params={"per_page": 50, "page": page}, timeout=5)
            if r.status_code != 200:
                break
            d = r.json()
            for it in d.get("items", []):
                vid = str(it.get("id", "") or "")
                if vid:
                    ids.add(vid)
            if page + 1 >= d.get("pages", 0):
                break
            page += 1
        return ids
    cached = _extras_get("blacklisted", rh, 1800, _do)
    return cached if isinstance(cached, set) else set(cached or [])


_employer_rating_cache: dict = {}  # {eid: (expiry, {rating, reviews_count, recommendations_percent})}
_employer_rating_lock = threading.Lock()


def fetch_employer_rating(acc: dict, employer_id: str) -> dict:
    """Pull employer reviews summary via OAuth API (`/employers/{eid}/reviews`).
    Returns {rating: float, reviews_count: int, recommendations_percent: int} or {}.
    Cached 24h globally — same employer == same rating regardless of which
    account asks. None on transport error (not cached → retried later).
    Empty dict {} when employer has no reviews (cached briefly to avoid
    re-asking)."""
    if not employer_id:
        return {}
    now = time.time()
    with _employer_rating_lock:
        cached = _employer_rating_cache.get(employer_id)
        if cached and cached[0] > now:
            return cached[1]
    H = _oauth_headers(acc)
    if not H:
        return {}
    try:
        r = HH.get(
            f"https://api.hh.ru/employers/{employer_id}/reviews",
            headers=H, timeout=5,
        )
        if r.status_code == 404:
            with _employer_rating_lock:
                _employer_rating_cache[employer_id] = (now + 3600, {})
            return {}
        if r.status_code != 200:
            return {}
        d = r.json()
        try:
            rating = float(d.get("total_rating") or 0)
        except (ValueError, TypeError):
            rating = 0.0
        info = {
            "rating": rating,
            "reviews_count": int(d.get("reviews_count") or 0),
            "recommendations_percent": int(d.get("recommendations_percent") or 0),
        }
    except Exception as e:
        log_debug(f"employer_rating({employer_id}) error: {e}")
        with _employer_rating_lock:
            _employer_rating_cache[employer_id] = (now + 60, {})
        return {}
    # 24h cache — рейтинги меняются медленно
    with _employer_rating_lock:
        _employer_rating_cache[employer_id] = (now + 86400, info)
    return info


_vacancy_details_cache: dict = {}  # {vid: (expiry, dict)}
_vacancy_details_lock = threading.Lock()


def fetch_vacancy_details(acc: dict, vid: str) -> dict:
    """GET /vacancies/{vid} via OAuth — full vacancy fields beyond search.
    Returns {auto_response, quick_responses_allowed, accredited_it_employer,
    key_skills:[name], work_format:[id], languages:[id]}. Cached 6h.
    {} on transient error → retried next call."""
    if not vid:
        return {}
    now = time.time()
    with _vacancy_details_lock:
        cached = _vacancy_details_cache.get(vid)
        if cached and cached[0] > now:
            return cached[1]
    H = _oauth_headers(acc)
    if not H:
        return {}
    try:
        r = HH.get(f"https://api.hh.ru/vacancies/{vid}", headers=H, timeout=5)
        if r.status_code == 404:
            with _vacancy_details_lock:
                _vacancy_details_cache[vid] = (now + 3600, {"archived": True})
            return {"archived": True}
        if r.status_code != 200:
            # Negative cache 60s — без этого упавший HH провоцирует retry-шторм
            # на каждой вакансии в filter loop.
            with _vacancy_details_lock:
                _vacancy_details_cache[vid] = (now + 60, {})
            return {}
        d = r.json()
        emp = d.get("employer") or {}
        info = {
            "auto_response": bool(d.get("auto_response")),
            "quick_responses_allowed": bool(d.get("quick_responses_allowed")),
            "accredited_it_employer": bool(emp.get("accredited_it_employer")),
            "trusted_employer": bool(emp.get("trusted")),
            "key_skills": [s.get("name", "") for s in (d.get("key_skills") or []) if isinstance(s, dict)],
            "work_format": [
                (w.get("id") if isinstance(w, dict) else str(w))
                for w in (d.get("work_format") or [])
            ],
            "languages": [
                (l.get("id") if isinstance(l, dict) else str(l))
                for l in (d.get("languages") or [])
            ],
            "response_letter_required": bool(d.get("response_letter_required")),
            "billing_type": (d.get("billing_type") or {}).get("id", ""),
        }
    except Exception as e:
        log_debug(f"vacancy_details({vid}) error: {e}")
        with _vacancy_details_lock:
            _vacancy_details_cache[vid] = (now + 60, {})
        return {}
    with _vacancy_details_lock:
        _vacancy_details_cache[vid] = (now + 21600, info)  # 6h
    return info


_negotiations_count_cache: dict = {}  # {resume_hash: (expiry, {today, today_msk_date})}
_negotiations_count_lock = threading.Lock()


def fetch_negotiations_today_count(acc: dict) -> dict:
    """Реальное число сегодняшних откликов (по MSK) — источник истины для
    HH daily-limit'а. Используется чтобы перестать угадывать
    `hard_stopped` и автоматом снимать stop когда лимит реально сброшен.

    Returns {'today': N, 'msk_date': 'YYYY-MM-DD', 'total_found': M} or {} on error.
    Cached 5 min.
    """
    rh = acc.get("resume_hash", "")
    if not rh:
        return {}
    now = time.time()
    with _negotiations_count_lock:
        cached = _negotiations_count_cache.get(rh)
        if cached and cached[0] > now:
            return cached[1]
    H = _oauth_headers(acc)
    if not H:
        return {}
    try:
        from datetime import datetime
        try:
            from zoneinfo import ZoneInfo
            MSK = ZoneInfo("Europe/Moscow")
        except Exception:
            MSK = None
        today_msk = datetime.now(MSK).date() if MSK else datetime.now().date()
        midnight = datetime.combine(today_msk, datetime.min.time(), tzinfo=MSK) if MSK else None
        n_today = 0
        total_found = 0
        oldest_dt = None
        for page in range(5):
            r = HH.get(
                "https://api.hh.ru/negotiations",
                headers=H, params={"per_page": 100, "page": page}, timeout=5,
            )
            if r.status_code != 200:
                break
            d = r.json()
            if page == 0:
                total_found = int(d.get("found", 0) or 0)
            items = d.get("items", [])
            if not items:
                break
            for it in items:
                try:
                    dt = datetime.fromisoformat(it.get("created_at", ""))
                except Exception:
                    continue
                msk_dt = dt.astimezone(MSK) if MSK else dt
                if midnight is None or msk_dt >= midnight:
                    n_today += 1
                oldest_dt = dt
            # Лента отсортирована по новейшим первая. Как только дошли до
            # вакансии раньше midnight — дальше тоже только старые, можно стоп.
            if oldest_dt:
                msk_oldest = oldest_dt.astimezone(MSK) if MSK else oldest_dt
                if midnight and msk_oldest < midnight:
                    break
        info = {
            "today": n_today,
            "msk_date": str(today_msk),
            "total_found": total_found,
        }
    except Exception as e:
        log_debug(f"negotiations_count error: {e}")
        return {}
    with _negotiations_count_lock:
        _negotiations_count_cache[rh] = (now + 300, info)
    return info


def fetch_resume_status(acc: dict) -> dict:
    """Resume status: published/blocked, finished, progress.percentage, moderation_note.
    Cached 5 min."""
    rh = acc.get("resume_hash", "")
    if not rh:
        return {}
    def _do():
        H = _oauth_headers(acc)
        if not H:
            return None
        r = HH.get(f"https://api.hh.ru/resumes/{rh}/status", headers=H, timeout=5)
        if r.status_code != 200:
            return None
        d = r.json()
        return {
            "status_id": (d.get("status") or {}).get("id", ""),
            "status_name": (d.get("status") or {}).get("name", ""),
            "blocked": bool(d.get("blocked")),
            "finished": bool(d.get("finished")),
            "progress": int((d.get("progress") or {}).get("percentage", 0) or 0),
            "moderation_note": [
                (n.get("name") if isinstance(n, dict) else str(n))
                for n in (d.get("moderation_note") or [])
            ],
        }
    return _extras_get("resume_status", rh, 300, _do) or {}


def _oauth_apply(acc: dict, vid: str, message: str = "") -> tuple:
    """Apply to vacancy via OAuth API. Returns (result_str, info_dict)."""
    from app.llm import _randomize_text
    token = _obtain_oauth_token(acc)
    if not token:
        return "error", {"exception": "OAuth token не получен"}
    resume_hash = acc.get("resume_hash", "")
    try:
        message = _randomize_text(message) if message else message
        resume_hash_quoted = urllib.parse.quote(resume_hash, safe="")
        data = {"vacancy_id": vid, "resume_id": resume_hash_quoted}
        if message:
            data["message"] = message
        r = HH.post(
            "https://api.hh.ru/negotiations",
            headers={"User-Agent": _mobile_user_agent(), "Authorization": f"Bearer {token}",
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
        elif r.status_code == 401:
            # Очищаем кэшированный токен: иначе manager на каждом следующем apply
            # будет переиспользовать тот же rejected токен → бесконечная петля 401.
            log_debug(f"OAuth apply auth_error for {resume_hash[:12]} vid={vid}")
            invalidate_oauth_token(resume_hash, acc)
            return "auth_error", {}
        elif r.status_code == 403:
            # 403 from POST /negotiations is normally a business-rule denial
            # (vacancy restrictions, questionnaire, visibility), not an expired
            # OAuth token. Invalidating here emptied oauth_tokens.json after a
            # perfectly successful mobile login. Only 401 proves bad auth.
            try:
                detail = r.json()
                errors = detail.get("errors", []) if isinstance(detail, dict) else []
                raw = errors[0].get("value", "forbidden") if errors and isinstance(errors[0], dict) else "forbidden"
            except Exception:
                raw = "forbidden"
            return "error", {"raw": raw, "http_status": 403}
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
        resume_hash_quoted = urllib.parse.quote(resume_hash, safe="")
        r = HH.post(
            f"https://api.hh.ru/resumes/{resume_hash_quoted}/publish",
            headers={"User-Agent": _mobile_user_agent(), "Authorization": f"Bearer {token}"},
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


def fetch_negotiation_messages_oauth(acc: dict, neg_id, max_messages: int = 20) -> list:
    """GET /negotiations/{neg_id}/messages — chat history через официальный
    OAuth API (без cookies). Возвращает [{sender, text, msg_id, viewed_by_me,
    author_type}] в хронологическом порядке (oldest first), последние
    `max_messages` записей.

    Заменяет reverse-engineered chatik.hh.ru-scraping когда:
    - cookies протухли (degraded mode),
    - либо включён CONFIG.chat_use_oauth.
    """
    if not neg_id:
        return []
    H = _oauth_headers(acc)
    if not H:
        return []
    try:
        r = HH.get(
            f"https://api.hh.ru/negotiations/{neg_id}/messages",
            headers=H, params={"per_page": max_messages, "order_by": "asc"},
            timeout=5,
        )
        if r.status_code != 200:
            log_debug(f"OAuth chat history neg={neg_id}: HTTP {r.status_code}")
            return []
        items = (r.json() or {}).get("items", []) or []
        out: list = []
        for m in items[-max_messages:]:
            author = m.get("author") or {}
            atype = (author.get("participant_type") or "").lower()  # 'applicant' | 'employer'
            sender = "applicant" if atype == "applicant" else "employer"
            out.append({
                "sender": sender,
                "text": (m.get("text") or "").strip(),
                "msg_id": m.get("id"),
                "viewed_by_me": bool(m.get("viewed_by_me")),
                "author_type": atype,
            })
        return out
    except Exception as e:
        log_debug(f"OAuth chat history neg={neg_id} error: {e}")
        return []


def send_negotiation_message_oauth(acc: dict, neg_id, text: str) -> bool:
    """POST /negotiations/{neg_id}/messages — альтернатива
    `send_chat_message_oauth` (которая работает через /common/chats).
    Бот выбирает этот путь когда у нас есть neg_id (а не chat_id) и/или
    в degraded mode. Возвращает True/False."""
    if not neg_id:
        return False
    H = _oauth_headers(acc)
    if not H:
        return False
    try:
        r = HH.post(
            f"https://api.hh.ru/negotiations/{neg_id}/messages",
            headers={**H, "Content-Type": "application/json"},
            json={"message": text}, timeout=15,
        )
        log_debug(f"OAuth /negotiations send neg={neg_id}: HTTP {r.status_code} | {r.text[:200]}")
        if r.status_code in (200, 201, 204):
            return True
        if r.status_code == 403:
            # Invalidate token — потом lazy-refresh подхватит
            rh = acc.get("resume_hash", "")
            if rh:
                invalidate_oauth_token(rh, acc)
        return False
    except Exception as e:
        log_debug(f"OAuth /negotiations send neg={neg_id} error: {e}")
        return False


def send_chat_message_oauth(acc: dict, chat_id, text: str, is_automated: bool = True):
    """Отправить сообщение в чат через ОФИЦИАЛЬНЫЙ HH OAuth API.

    POST https://api.hh.ru/common/chats/{chat_id}/messages с Bearer token.
    Возвращает True (ok), "chat_not_found", "no_token", или False (другая ошибка).

    Отличия от reverse-engineered chatik.hh.ru/api/send:
    - Официальный путь, не нарушает HH ToS
    - is_automated: true честно помечает что сообщение от AI (требуется
      по правилам HH для AI-generated content)
    - Используется тот же chat_id что и chatik (числовой ID)
    """
    import uuid as _uuid
    token = _obtain_oauth_token(acc)
    if not token:
        return "no_token"
    try:
        cid = int(str(chat_id).strip())
    except (ValueError, TypeError):
        return False
    ua = _mobile_user_agent()
    payload = {
        "text": text,
        "idempotency_key": str(_uuid.uuid4()),
        "is_automated": bool(is_automated),
    }
    try:
        r = HH.post(
            f"https://api.hh.ru/common/chats/{cid}/messages",
            json=payload,
            headers={
                "User-Agent": ua,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            timeout=15,
        )
        log_debug(f"OAuth chat send chat_id={cid}: HTTP {r.status_code} | {r.text[:300]}")
        if r.status_code in (200, 201, 204):
            return True
        if r.status_code == 404:
            return "chat_not_found"
        if r.status_code == 403:
            # OAuth token может протухнуть. Invalidate чтобы _obtain_oauth_token
            # сделал refresh на следующем вызове.
            resume_hash = acc.get("resume_hash", "")
            if resume_hash:
                invalidate_oauth_token(resume_hash, acc)
            return False
        if r.status_code == 409:
            try:
                body = r.json()
            except Exception:
                body = {}
            errs = body.get("errors") or []
            joined = " ".join(str(e.get("type",""))+" "+str(e.get("value","")) for e in errs).lower()
            if any(m in joined for m in ("not_found","not_exist","archived","closed","chat_not_found")):
                return "chat_not_found"
            return False
        return False
    except Exception as e:
        log_debug(f"OAuth chat send chat_id={cid} error: {e}")
        return False


def fetch_negotiations_statistic(acc: dict) -> dict:
    """`GET api.hh.ru/negotiations_statistic/mine` — mobile-endpoint из
    ru.hh.android v26.28.1 (probe'нут 2026-08-03, работает через web OAuth-token).
    Возвращает {responses_count, responses_required} — streak-геймификация
    HH: сколько откликов нужно за период чтобы получить бейдж "часто отвечает".
    Cached 30 min.
    """
    rh = acc.get("resume_hash", "")
    if not rh:
        return {}
    now = time.time()
    key = f"stat::{rh}"
    with _negotiations_count_lock:
        cached = _negotiations_count_cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
    H = _oauth_headers(acc)
    if not H:
        return {}
    # mobile-endpoint требует x-force-app-access + mobile UA (без них 406)
    H = {**H, "x-force-app-access": "true", "User-Agent": _mobile_user_agent()}
    try:
        r = HH.get("https://api.hh.ru/negotiations_statistic/mine",
                   headers=H, timeout=8)
        if r.status_code != 200:
            return {}
        data = r.json()
        streak = (data.get("applicant_statistic") or {}).get("responses_streak") or {}
        out = {
            "responses_count": int(streak.get("responses_count") or 0),
            "responses_required": int(streak.get("responses_required") or 0),
        }
        with _negotiations_count_lock:
            _negotiations_count_cache[key] = (now + 1800, out)
        return out
    except Exception as e:
        log_debug(f"fetch_negotiations_statistic {rh[:12]}: {e}")
        return {}
