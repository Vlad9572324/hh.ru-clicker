"""Общий HTTP-транспорт для mobile-endpoint'ов api.hh.ru (Phase 2).

Все mobile-модули (app/hh_mobile_*.py) ходят через mobile_request():

- HTTP через библиотеку `requests` (не curl_cffi-обёртку HH) — тесты
  mock'ают вызовы через `responses` (конвенция MobileHHClient.fetch_counters);
  прокси инжектится из HH_PROXY через egress_proxies() (split-egress:
  весь hh.ru egress обязан идти через прокси, см. app/hh_http.py);
- Bearer-токен добывается через app.oauth._obtain_oauth_token;
- заголовки: Authorization Bearer + User-Agent ru.hh.android/26.28.1 +
  x-force-app-access: true (контракт APK, см.
  scratchpad/apidocs/apidocs_group_1.yaml);
- 2xx → распарсенный JSON (None при пустом теле);
- не-2xx → MobileAPIError(status_code, payload);
- сетевая ошибка → MobileAPIError(0) — трактуется как fallback-статус.

Fallback-политика: статусы, по которым фабрика клиентов повторяет запрос
через web-flow (cookies), — 0 (сеть), 401 (нет/протух токен), 403 (нет
scope), 5xx (сервер лежит). См. is_fallback_status() и
app/hh_client_fallback.py.
"""

import requests

from app import oauth
from app.hh_http import egress_proxies
from app.logging_utils import log_debug
from app.user_agent import ensure_device_identity, mobile_user_agent
from app.mutation_safety import ensure_mutation_allowed

MOBILE_BASE = "https://api.hh.ru"
MOBILE_UA = "ru.hh.android/26.32.11480"


class MobileAPIError(Exception):
    """Ошибка mobile-вызова api.hh.ru.

    status_code: HTTP-статус ответа; 0 — сетевая ошибка
    (requests.RequestException, запрос не дошёл). payload — JSON ошибки
    (или обрезанный текст ответа), для сетевых — текст исключения.
    """

    def __init__(self, status_code: int, payload=None, url: str = "", *, outcome_unknown=False, challenge_required=False):
        self.status_code = status_code
        self.payload = payload
        self.url = url
        self.outcome_unknown = outcome_unknown
        self.challenge_required = challenge_required
        super().__init__(f"mobile API {url} -> HTTP {status_code}")


def is_fallback_status(status_code: int) -> bool:
    """True, если при таком сбое mobile-вызова есть смысл повторить через
    web-flow: нет токена/авторизации (401), нет scope (403), сервер лежит
    (5xx), сеть недоступна (0)."""
    return status_code in (0, 401, 403) or 500 <= status_code <= 599


def mobile_headers(acc, token: str | None = None) -> dict:
    """Build mobile headers using a stable per-account device fingerprint.

    ``mobile_headers(token)`` remains supported for callers that intentionally
    need the global fallback identity.
    """
    if isinstance(acc, str) and token is None:
        token, acc = acc, None
    identity = ensure_device_identity(acc) if isinstance(acc, dict) else None
    return {
        "Authorization": f"Bearer {token}",
        # APK-compatible package/version + device/UUID identity.
        "User-Agent": mobile_user_agent(acc) or MOBILE_UA,
        **({"X-Device-Uuid": str(identity["device_uuid"])} if identity else {}),
        "x-force-app-access": "true",
        "x-hh-app-active": "true",
        "Accept": "application/json",
    }


def mobile_request(acc: dict, method: str, path: str, *, params=None,
                   json_body=None, form=None, timeout: int = 15):
    """Выполнить запрос к api.hh.ru от имени аккаунта.

    path — путь относительно MOBILE_BASE ("/chats") либо полный URL.
    json_body — JSON-тело; form — form-urlencoded поля (data=...).
    Возвращает распарсенный JSON (None при пустом теле) на 2xx.
    Любая ошибка — MobileAPIError (см. докстринг модуля).
    Прокси инжектится из HH_PROXY (egress_proxies()); None = без прокси.
    """
    url = path if str(path).startswith("http") else MOBILE_BASE + path
    token = oauth._obtain_oauth_token(acc)
    if not token:
        raise MobileAPIError(401, payload="no_oauth_token", url=url)
    mutating = method.upper() not in ("GET", "HEAD", "OPTIONS")
    if mutating:
        ensure_mutation_allowed(acc)
    from app.hh_http import PinnedEgressSession
    try:
        with PinnedEgressSession() as session:
            r = session.request(
                method, url, params=params, json=json_body, data=form,
                headers=mobile_headers(acc, token), timeout=timeout,
            )
    except requests.RequestException as e:
        log_debug(f"mobile_request {method} {url}: network error {e}")
        raise MobileAPIError(0, payload=str(e), url=url, outcome_unknown=mutating)
    if r.status_code == 401:
        # HH может отозвать access token раньше локального expires_at. Не
        # повторяем здесь POST/PUT: следующий вызов получит свежий token, а
        # текущая операция уйдёт в штатную fallback-политику.
        oauth.invalidate_oauth_token(acc.get("resume_hash", ""), acc)
    if not (200 <= r.status_code < 300):
        try:
            payload = r.json()
        except ValueError:
            payload = r.text[:500]
        from app.captcha import capture
        challenge = capture(acc, r.status_code, payload)
        if challenge is not None:
            payload = {'errors': [{'type': 'captcha_required', 'value': 'captcha_required'}]}
        raise MobileAPIError(r.status_code, payload=payload, url=url,
                             outcome_unknown=mutating and r.status_code >= 500,
                             challenge_required=challenge is not None)
    if not r.content:
        if mutating and url.rstrip("/").endswith("/negotiations") and r.status_code not in (201, 204):
            raise MobileAPIError(r.status_code, payload="empty_mutation_response", url=url,
                                 outcome_unknown=True)
        return None
    try:
        return r.json()
    except ValueError:
        raise MobileAPIError(r.status_code, payload="invalid_json", url=url,
                             outcome_unknown=mutating)
