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

MOBILE_BASE = "https://api.hh.ru"
MOBILE_UA = "ru.hh.android/26.28.1"


class MobileAPIError(Exception):
    """Ошибка mobile-вызова api.hh.ru.

    status_code: HTTP-статус ответа; 0 — сетевая ошибка
    (requests.RequestException, запрос не дошёл). payload — JSON ошибки
    (или обрезанный текст ответа), для сетевых — текст исключения.
    """

    def __init__(self, status_code: int, payload=None, url: str = ""):
        self.status_code = status_code
        self.payload = payload
        self.url = url
        super().__init__(f"mobile API {url} -> HTTP {status_code}")


def is_fallback_status(status_code: int) -> bool:
    """True, если при таком сбое mobile-вызова есть смысл повторить через
    web-flow: нет токена/авторизации (401), нет scope (403), сервер лежит
    (5xx), сеть недоступна (0)."""
    return status_code in (0, 401, 403) or 500 <= status_code <= 599


def mobile_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": MOBILE_UA,
        "x-force-app-access": "true",
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
        # Нет токена == нет авторизации → последствия как у HTTP 401:
        # фабрике есть смысл повторить через web-flow.
        raise MobileAPIError(401, payload="no_oauth_token", url=url)
    try:
        r = requests.request(
            method, url,
            params=params, json=json_body, data=form,
            headers=mobile_headers(token),
            # split-egress: api.hh.ru тоже обязан идти через HH_PROXY.
            proxies=egress_proxies(),
            timeout=timeout,
        )
    except requests.RequestException as e:
        log_debug(f"mobile_request {method} {url}: network error {e}")
        raise MobileAPIError(0, payload=str(e), url=url)
    if not (200 <= r.status_code < 300):
        try:
            payload = r.json()
        except ValueError:
            payload = r.text[:500]
        raise MobileAPIError(r.status_code, payload=payload, url=url)
    if not r.content:
        return None
    try:
        return r.json()
    except ValueError:
        return None
