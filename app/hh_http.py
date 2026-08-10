"""Единая точка исходящих HTTP-запросов к hh.ru.

Задачи:
1. **Impersonate Chrome TLS+H2 fingerprint** через `curl_cffi` когда доступен.
   Обычный `requests` использует OpenSSL/urllib3 handshake — HH (и DDoS Guard
   перед ним) распознают JA3/JA4 отпечаток как не-браузерный и режут 403 ещё
   до чтения cookies. `curl_cffi.requests` эмулирует Chrome-TLS byte-for-byte
   (порядок cipher-suites, ALPN, ClientHello extensions) + HTTP/2 SETTINGS
   frame — этого хватает чтобы snapshot браузера считался легитимным.

2. **Diagnostic logging** подозрительных ответов в отдельный `data/diag.log`.
   Пишем: код, тело первые 2 KB, заголовки, tag с классификатором.
   Основной `debug.log` при этом не забиваем.
"""
from __future__ import annotations
import json
import os
import threading
import time
import urllib.parse
from collections import OrderedDict
from pathlib import Path
from typing import Any

try:
    from curl_cffi import requests as _cffi_requests
    from curl_cffi.requests import Session as _CffiSession
    _HAS_CFFI = True
except Exception:
    _cffi_requests = None
    _CffiSession = None
    _HAS_CFFI = False

import requests as _requests

from app.user_agent import mobile_user_agent

# `CHROME_IMPERSONATE` подсказка для curl_cffi — какую версию Chrome мимикрить.
# `chrome124` покрывает большинство свежих HH fingerprint-проверок; можно
# переопределить через env `HH_IMPERSONATE=chrome131` etc.
_IMPERSONATE = os.environ.get("HH_IMPERSONATE", "chrome124")

# Прокси для всех исходящих запросов к hh.ru (обход soft-ban DDoS-Guard по IP).
# Формат: `socks5h://host:port` / `http://host:port`. Пусто = напрямую.
# Пример: HH_PROXY=socks5h://warp:1080 (WARP-sidecar контейнер).
_PROXY = os.environ.get("HH_PROXY", "").strip()

_DIAG_PATH = Path("data/diag.log")
_DIAG_LOCK = threading.Lock()
_DIAG_MAX_SIZE = 10 * 1024 * 1024  # 10 MB → truncate

# Признаки суспект-ответа для diag-логгинга. HH не документирует, эмпирика:
_DDOS_GUARD_MARKERS = (b"ddos-guard", b"DDoS-Guard", b"DDOS_G_", b"ddg1")
_CAPTCHA_MARKERS = (b"captcha_key", b"CAPTCHA", b"captchaSid",
                    "Проверка не пройдена".encode("utf-8"))


def _classify(status: int, body: bytes, headers: dict) -> str:
    """Классифицировать ответ для diag-лога.
    Returns: 'ok' | 'auth' | 'ddos_guard' | 'captcha' | 'ratelimit' |
             'server_error' | 'blocked' | 'suspicious'."""
    if 200 <= status < 300:
        return "ok"
    if status == 429:
        return "ratelimit"
    if 500 <= status < 600:
        return "server_error"
    lower_body = body[:4096].lower() if body else b""
    lower_hdrs = " ".join(f"{k}:{v}".lower() for k, v in (headers or {}).items())
    if any(m.lower() in lower_body for m in _DDOS_GUARD_MARKERS) or "ddos-guard" in lower_hdrs:
        return "ddos_guard"
    if any(m.lower() in lower_body for m in _CAPTCHA_MARKERS):
        return "captcha"
    if status in (401, 403):
        if b"need-login" in lower_body or b"need_login" in lower_body:
            return "auth"
        if b"/account/login" in lower_body:
            return "auth"
        return "blocked"
    if status == 404:
        return "blocked"
    return "suspicious"


def _diag(entry: dict) -> None:
    """Append newline-delimited JSON to data/diag.log. Rotates at 10 MB."""
    try:
        _DIAG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with _DIAG_LOCK:
            try:
                if _DIAG_PATH.exists() and _DIAG_PATH.stat().st_size > _DIAG_MAX_SIZE:
                    # Ротация: сохраняем последние ~5 MB
                    with open(_DIAG_PATH, "rb") as f:
                        f.seek(-_DIAG_MAX_SIZE // 2, os.SEEK_END)
                        tail = f.read()
                    with open(_DIAG_PATH, "wb") as f:
                        f.write(b"# rotated\n")
                        f.write(tail)
            except Exception:
                pass
            with open(_DIAG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


def _record_diag(method: str, url: str, status: int, body: bytes, headers: dict, tag: str,
                 extra: dict | None = None) -> None:
    entry = {
        "t": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tag": tag,
        "method": method,
        "url": url[:300],
        "status": status,
        "impersonated": _HAS_CFFI,
        "headers": {k: v for k, v in (headers or {}).items()
                    if k.lower() in ("server", "cf-ray", "x-request-id", "content-type",
                                     "www-authenticate", "location", "retry-after", "x-cache")},
        "body_head": (body[:2048].decode("utf-8", errors="replace") if body else ""),
    }
    if extra:
        entry.update(extra)
    _diag(entry)


class HHClient:
    """Обёртка над curl_cffi / requests с общим API `.request(...)`.

    Использование:
        r = HH.request("GET", "https://hh.ru/vacancy/1", cookies=acc["cookies"],
                       cookie_jar_key=acc_id)
        r.status_code, r.text, r.headers, r.json()

    При curl_cffi доступен — automatically impersonates Chrome.
    При отсутствии — fallback на стандартный `requests` (старое поведение).
    Оба возвращают одинаковый интерфейс `requests.Response`-совместимый объект.

    Per-account сессии (изоляция cookies):
        `request()` принимает kwarg `cookie_jar_key: str | None` (извлекается
        из kwargs через pop, как `_diag_tag` и т.п.). Когда задан — запрос идёт
        через per-key пару сессий (curl_cffi + requests fallback), хранящуюся
        в LRU-реестре `self._sessions` (макс. 100 ключей; least recently used
        вытесняется). Это устраняет cross-account cookie confusion, когда
        аккаунт B отправлял hhtoken аккаунта A через общую cookie jar.
        `cookies=` kwarg остаётся pass-through к сессии.
        `cookie_jar_key=None` — legacy поведение: общие сессии
        `_session_cffi`/`_session_req` (для запросов без аккаунтного контекста,
        например probe_outbound_ip).
        Fallback при cffi-ошибке идёт в PER-KEY requests-сессию, не в общую.

    Diag-хук: любой не-2xx ответ или подозрительное тело пишет запись в
    `data/diag.log`.
    """

    _MAX_SESSIONS = 100  # LRU-лимит per-account реестра сессий

    def __init__(self):
        self._session_cffi = _CffiSession() if _HAS_CFFI else None
        self._session_req = _requests.Session()
        # Per-account сессии: cookie_jar_key -> {"cffi": ..., "req": ...}.
        # LRU: недавно использованные ключи в конце (move_to_end при доступе).
        self._sessions: OrderedDict[str, dict] = OrderedDict()
        self._sessions_lock = threading.RLock()

    def _get_session(self, cookie_jar_key: str | None) -> tuple[Any, Any]:
        """Вернуть (cffi_session_or_None, requests_session) для данного ключа.

        cookie_jar_key=None → legacy общие сессии (запросы без аккаунтного
        контекста). Иначе — per-key пара сессий из LRU-реестра `self._sessions`
        (ленивое создание; при доступе move_to_end; при превышении
        `_MAX_SESSIONS` вытесняется самая давно не использовавшаяся запись
        через popitem(last=False)). Все операции под `self._sessions_lock`.
        """
        if cookie_jar_key is None:
            return self._session_cffi, self._session_req
        with self._sessions_lock:
            entry = self._sessions.get(cookie_jar_key)
            if entry is None:
                entry = {
                    "cffi": _CffiSession() if _HAS_CFFI else None,
                    "req": _requests.Session(),
                }
                self._sessions[cookie_jar_key] = entry
            self._sessions.move_to_end(cookie_jar_key)
            while len(self._sessions) > self._MAX_SESSIONS:
                _evicted_key, evicted = self._sessions.popitem(last=False)
                # Закрываем вытесненные сессии чтобы их keep-alive/cookies
                # не переиспользовались и не висели в памяти.
                for s in (evicted["cffi"], evicted["req"]):
                    if s is not None:
                        try:
                            s.close()
                        except Exception:
                            pass
            return entry["cffi"], entry["req"]

    def request(self, method: str, url: str, **kwargs) -> Any:
        # Extract our own kwargs
        diag_tag = kwargs.pop("_diag_tag", "")
        skip_diag = kwargs.pop("_skip_diag", False)
        cookie_jar_key = kwargs.pop("cookie_jar_key", None)

        # curl_cffi не поддерживает `files=` в POST → forced fallback на requests
        # (обычно touch_resume / multipart uploads — редкие, не критично для fingerprint).
        force_requests = kwargs.pop("_force_requests", False) or "files" in kwargs

        # Единая страховка для всех вызовов через HH: даже новый endpoint,
        # где caller забудет headers, должен представляться Android-приложением.
        headers = dict(kwargs.get("headers") or {})
        hostname = (urllib.parse.urlparse(url).hostname or "").lower()
        is_hh_host = hostname == "hh.ru" or hostname.endswith(".hh.ru") or hostname == "hh.kz" or hostname.endswith(".hh.kz")
        if is_hh_host and not any(str(key).lower() == "user-agent" for key in headers):
            headers["User-Agent"] = mobile_user_agent()
        if headers:
            kwargs["headers"] = headers

        # Инжектим прокси если задан HH_PROXY и caller не переопределил свой.
        if _PROXY and "proxies" not in kwargs and "proxy" not in kwargs:
            kwargs["proxies"] = {"http": _PROXY, "https": _PROXY}

        # Per-account сессия (cookie_jar_key) или общая legacy (None).
        sess_cffi, sess_req = self._get_session(cookie_jar_key)

        # curl_cffi понимает большинство requests-опций 1:1 + `impersonate`
        if sess_cffi is not None and not force_requests:
            try:
                r = sess_cffi.request(
                    method, url, impersonate=_IMPERSONATE, **kwargs,
                )
                tag = _classify(r.status_code, r.content or b"", dict(r.headers or {}))
                if not skip_diag and tag not in ("ok",):
                    _record_diag(method, url, r.status_code, r.content or b"",
                                 dict(r.headers or {}), tag,
                                 extra={"origin_tag": diag_tag} if diag_tag else None)
                return r
            except Exception as e:
                # На unrecoverable ошибку curl_cffi (segfault, unsupported cert) —
                # логируем и fallback на requests той же per-key сессию (не общую,
                # иначе cross-account cookie confusion сохраняется).
                _record_diag(method, url, -1, str(e).encode("utf-8"), {},
                             tag="cffi_error", extra={"exc": str(e)})

        r = sess_req.request(method, url, **kwargs)
        tag = _classify(r.status_code, r.content or b"", dict(r.headers or {}))
        if not skip_diag and tag not in ("ok",):
            _record_diag(method, url, r.status_code, r.content or b"",
                         dict(r.headers or {}), tag,
                         extra={"origin_tag": diag_tag} if diag_tag else None)
        return r

    def get(self, url: str, **kw): return self.request("GET", url, **kw)
    def post(self, url: str, **kw): return self.request("POST", url, **kw)
    def put(self, url: str, **kw): return self.request("PUT", url, **kw)
    def delete(self, url: str, **kw): return self.request("DELETE", url, **kw)


# Singleton
HH = HHClient()


def is_impersonating() -> bool:
    return _HAS_CFFI


def impersonate_version() -> str:
    return _IMPERSONATE if _HAS_CFFI else "requests(no-impersonate)"


def proxy_url() -> str:
    return _PROXY


def set_proxy(url: str) -> str:
    """Заменить прокси runtime (без рестарта контейнера). Приниает пустую строку
    для отключения. Возвращает актуальный URL после смены.
    Пересоздаёт curl_cffi Session и очищает per-account реестр сессий, чтобы
    старые keep-alive соединения через прежний прокси не переиспользовались
    (per-account сессии лениво пересоздадутся при следующем запросе)."""
    global _PROXY
    url = (url or "").strip()
    _PROXY = url
    # HH-singleton пересоздаём чтобы sticky-connections не остались от старого прокси.
    try:
        HH._session_cffi = _CffiSession() if _HAS_CFFI else None
        HH._session_req = _requests.Session()
    except Exception:
        pass
    # Per-account сессии тоже привязаны к старому прокси — очищаем реестр;
    # лениво пересоздадутся через новый прокси при следующем запросе.
    try:
        with HH._sessions_lock:
            evicted = list(HH._sessions.values())
            HH._sessions.clear()
        for entry in evicted:
            for s in (entry["cffi"], entry["req"]):
                if s is not None:
                    try:
                        s.close()
                    except Exception:
                        pass
    except Exception:
        pass
    return _PROXY


def probe_outbound_ip(timeout: float = 6.0) -> dict:
    """Дёрнуть api.ipify.org через текущий (или дефолтный) сетевой стек и
    вернуть исходящий IP. Полезно проверить активность прокси и что за IP
    видит внешний мир."""
    out = {"proxy": _PROXY, "ip": "", "error": ""}
    try:
        r = HH.get("https://api.ipify.org", timeout=timeout, _skip_diag=True)
        if r.status_code == 200:
            out["ip"] = (r.text or "").strip()
        else:
            out["error"] = f"HTTP {r.status_code}"
    except Exception as e:
        out["error"] = str(e)[:120]
    return out
