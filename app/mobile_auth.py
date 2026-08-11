"""HH Android-compatible OTP authentication and its local configuration.

The HTTP contract is mirrored from the decompiled HH Android 26.29 client.  This
module deliberately does not try to turn OAuth credentials into browser cookies:
the official OTP response contains tokens, not a hh.ru browser session.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlparse

import requests


DATA_DIR = Path("data")
CONFIG_FILE = DATA_DIR / "config.json"
LEGACY_CONFIG_FILE = DATA_DIR / "mobile_auth_config.json"
STATE_FILE = DATA_DIR / "mobile_auth_state.json"

MASK = "********"
SENSITIVE_KEYS = {"app_client_token", "oauth_client_secret"}
DEFAULTS: dict[str, Any] = {
    "app_package": "ru.hh.android",
    "app_version_name": "26.29",
    "app_version_code": 11476,
    "user_agent_template": "%s/%s.%d, Device: %s, Android OS: %s (UUID: %s)",
    "app_client_token": "K811HJNKQA8V1UN53I6PN1J1CMAD2L1M3LU6LPAU849BCT031KDSSM485FDPJ6UF",
    "oauth_client_id": "HIOMIAS39CA9DICTA7JIO64LQKQJF5AGIK74G9ITJKLNEDAOH5FHS5G1JI7FOEGD",
    "oauth_client_secret": "V9M870DE342BGHFRUJ5FTCGCUA1482AN0DI8C5TFI9ULMA89H10N60NOP8I4JMVS",
    "device_model": "Pixel 10",
    "android_release": "17",
    "device_uuid": "8f42e879-43c7-4d86-a671-31ea36ed924b",
    "base_url": "https://api.hh.ru",
}
ENV_KEYS = {
    "app_package": "HH_APP_PACKAGE",
    "app_version_name": "HH_APP_VERSION_NAME",
    "app_version_code": "HH_APP_VERSION_CODE",
    "user_agent_template": "HH_USER_AGENT_TEMPLATE",
    "app_client_token": "HH_APP_CLIENT_TOKEN",
    "oauth_client_id": "HH_OAUTH_CLIENT_ID",
    "oauth_client_secret": "HH_OAUTH_CLIENT_SECRET",
    "device_model": "HH_DEVICE_MODEL",
    "android_release": "HH_ANDROID_RELEASE",
    "device_uuid": "HH_DEVICE_UUID",
    "base_url": "HH_API_BASE_URL",
}
_lock = threading.RLock()
_web_overrides: dict[str, Any] = {}

# Антибрутфорс OTP: лимиты персистятся в STATE_FILE и переживают рестарт процесса.
OTP_MAX_ATTEMPTS = 5
OTP_LOCKOUT_SECONDS = 15 * 60
OTP_STATE_TTL_SECONDS = 300
REQUEST_CODE_THROTTLE_SECONDS = 60
REQUEST_CODE_DAILY_LIMIT = 10
_otp_lock = threading.Lock()


def _seconds_until_midnight() -> int:
    """Секунд до полуночи — retry_after при достижении дневного лимита кодов."""
    now = datetime.now()
    midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    return max(int((midnight - now).total_seconds()), 1)


class MobileAuthError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400, retry_after: int | None = None,
                 captcha_url: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.captcha_url = captcha_url


@dataclass(frozen=True)
class MobileConfig:
    app_package: str
    app_version_name: str
    app_version_code: int
    user_agent_template: str
    app_client_token: str
    oauth_client_id: str
    oauth_client_secret: str
    device_model: str
    android_release: str
    device_uuid: str
    base_url: str

    @property
    def user_agent(self) -> str:
        try:
            value = self.user_agent_template % (
                self.app_package, self.app_version_name, self.app_version_code,
                self.device_model, self.android_release, self.device_uuid,
            )
        except (TypeError, ValueError) as exc:
            raise MobileAuthError("Шаблон User-Agent должен содержать %s/%s/%d/%s/%s/%s") from exc
        return value.encode("ascii", errors="ignore").decode("ascii")


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


# Allowlist хостов мобильного API: точный хост либо суффикс с точкой на границе.
# Благодаря точке в начале суффиксов не проходят hh.ru.attacker.com, evilhh.ru,
# api.hh.ru.evil.com и прочие похожие домены.
ALLOWED_BASE_URL_HOSTS = ("api.hh.ru", ".hh.ru", ".hh.kz")


def validate_base_url(url: str) -> str:
    """Проверяет и нормализует base_url мобильного API.

    Принимает только https://-адрес с хостом из ALLOWED_BASE_URL_HOSTS,
    без userinfo, порта (кроме 443), пути, query и fragment.  Любое нарушение
    поднимает MobileAuthError со статусом 400; при успехе возвращает
    нормализованный вид "https://<host>" (без порта и завершающего "/").
    """
    if not isinstance(url, str) or not url.strip():
        raise MobileAuthError("Base URL должен быть непустой строкой")
    try:
        parsed = urlparse(url.strip())
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as exc:
        raise MobileAuthError("Base URL не является корректным адресом") from exc
    if parsed.scheme != "https":
        raise MobileAuthError("Base URL должен использовать протокол https")
    if parsed.username is not None or parsed.password is not None:
        raise MobileAuthError("Base URL не должен содержать userinfo (user@host)")
    if not hostname:
        raise MobileAuthError("Base URL должен содержать имя хоста")
    if not any(hostname == allowed or hostname.endswith(allowed) for allowed in ALLOWED_BASE_URL_HOSTS):
        raise MobileAuthError("Base URL должен указывать на api.hh.ru или поддомен *.hh.ru / *.hh.kz")
    if port not in (None, 443):
        raise MobileAuthError("Base URL не должен содержать порт, отличный от 443")
    if parsed.path not in ("", "/"):
        raise MobileAuthError("Base URL не должен содержать путь")
    if parsed.query or parsed.fragment:
        raise MobileAuthError("Base URL не должен содержать query или fragment")
    return "https://" + hostname


def _coerce(values: dict[str, Any]) -> dict[str, Any]:
    out = dict(values)
    try:
        out["app_version_code"] = int(out["app_version_code"])
    except (TypeError, ValueError, KeyError) as exc:
        raise MobileAuthError("APP_VERSION_CODE должен быть положительным целым числом") from exc
    if out["app_version_code"] <= 0:
        raise MobileAuthError("APP_VERSION_CODE должен быть положительным целым числом")
    for key in DEFAULTS:
        if key == "app_version_code":
            continue
        if not isinstance(out.get(key), str) or not out[key].strip():
            raise MobileAuthError(f"Параметр {key} не должен быть пустым")
        out[key] = out[key].strip()
    try:
        uuid.UUID(out["device_uuid"])
    except (ValueError, AttributeError) as exc:
        raise MobileAuthError("DEVICE_UUID должен быть валидным UUID") from exc
    out["base_url"] = validate_base_url(out["base_url"])
    cfg = MobileConfig(**out)
    if not cfg.user_agent:
        raise MobileAuthError("Итоговый User-Agent пуст")
    return out


@lru_cache(maxsize=1)
def effective_config() -> tuple[MobileConfig, dict[str, str]]:
    """Resolve web override > environment > config file > built-in default."""
    root_config = _read_object(CONFIG_FILE)
    file_values = root_config.get("mobile_auth", {}) if isinstance(root_config.get("mobile_auth"), dict) else {}
    if not file_values:
        # One-time backward compatibility for builds that used a separate file.
        file_values = _read_object(LEGACY_CONFIG_FILE)
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    with _lock:
        web = dict(_web_overrides)
    for key, default in DEFAULTS.items():
        if key in web:
            values[key], sources[key] = web[key], "web"
        elif os.environ.get(ENV_KEYS[key], "").strip():
            values[key], sources[key] = os.environ[ENV_KEYS[key]], "environment"
        elif key in file_values:
            values[key], sources[key] = file_values[key], "file"
        else:
            values[key], sources[key] = default, "default"
    values = _coerce(values)
    return MobileConfig(**values), sources


def _invalidate_config_caches() -> None:
    effective_config.cache_clear()
    try:
        from app.user_agent import invalidate_mobile_user_agent_cache

        invalidate_mobile_user_agent_cache()
    except ImportError:
        pass


def public_config() -> dict[str, Any]:
    cfg, sources = effective_config()
    values = asdict(cfg)
    for key in SENSITIVE_KEYS:
        values[key] = MASK if values[key] else ""
    return {"values": values, "sources": sources, "user_agent": cfg.user_agent}


def save_config(updates: dict[str, Any]) -> dict[str, Any]:
    unknown = set(updates) - set(DEFAULTS)
    if unknown:
        raise MobileAuthError("Неизвестные параметры: " + ", ".join(sorted(unknown)))
    current, _ = effective_config()
    merged = asdict(current)
    for key, value in updates.items():
        if key in SENSITIVE_KEYS and (value in (None, "", MASK)):
            continue
        merged[key] = value
    merged = _coerce(merged)
    with _lock:
        # Share the main config write lock so bot settings and mobile settings
        # cannot overwrite each other during concurrent saves.
        from app.config import _config_write_lock, config_snapshot
        with _config_write_lock:
            existing = _read_object(CONFIG_FILE)
            # На чистой установке OTP-авторизация является первой операцией,
            # создающей config.json. Материализуем полную основную схему сразу.
            # Существующие и неизвестные корневые ключи имеют приоритет, чтобы
            # сохранение mobile_auth никогда не сбрасывало настройки пользователя.
            root_config = config_snapshot()
            root_config.update(existing)
            root_config["mobile_auth"] = merged
            _atomic_write(CONFIG_FILE, root_config)
            LEGACY_CONFIG_FILE.unlink(missing_ok=True)
        _web_overrides.clear()
        _web_overrides.update(merged)
        _invalidate_config_caches()
    return public_config()


def reset_config() -> dict[str, Any]:
    with _lock:
        _web_overrides.clear()
        from app.config import _config_write_lock
        with _config_write_lock:
            root_config = _read_object(CONFIG_FILE)
            root_config.pop("mobile_auth", None)
            _atomic_write(CONFIG_FILE, root_config)
            LEGACY_CONFIG_FILE.unlink(missing_ok=True)
        _invalidate_config_caches()
    return public_config()


def generate_device_uuid() -> str:
    return str(uuid.uuid4())


def mask_login(login: str) -> str:
    if "@" in login:
        name, domain = login.split("@", 1)
        return (name[:2] + "***@" + domain) if name else "***@" + domain
    digits = re.sub(r"\D", "", login)
    return ("+***" + digits[-4:]) if digits else "***"


def _safe_error(response: requests.Response) -> MobileAuthError:
    retry = response.headers.get("Retry-After")
    retry_after = int(retry) if retry and retry.isdigit() else None
    message = "HH отклонил запрос"
    captcha_url = None
    try:
        payload = response.json()
        # НЕ логируем payload целиком: ответ HH может содержать телефон/login (PII).
        errors = payload.get("errors", []) if isinstance(payload, dict) else []
        first = errors[0] if errors and isinstance(errors[0], dict) else {}
        kind, value = first.get("type", ""), first.get("value", "")
        if value == "confirmation_code_expired":
            message = "Код подтверждения истёк. Запросите новый код."
        elif kind == "bad_argument" and value == "confirmation_code":
            message = "Неверный код подтверждения."
        elif "captcha" in (kind + value).lower():
            message = "HH требует CAPTCHA. Откройте ссылку, пройдите проверку и повторите запрос."
            candidate = first.get("captcha_url")
            if isinstance(candidate, str):
                parsed = urlparse(candidate)
                host = (parsed.hostname or "").lower()
                if parsed.scheme == "https" and (host == "hh.ru" or host.endswith(".hh.ru")):
                    captcha_url = candidate
        elif response.status_code == 429:
            message = "Слишком много запросов. Повторите позже."
    except (ValueError, TypeError):
        pass
    return MobileAuthError(
        message, status_code=response.status_code, retry_after=retry_after,
        captcha_url=captcha_url,
    )


def _otp_locked_until(state: dict[str, Any]) -> int:
    """Эффективный конец OTP-lockout по state.

    Учитывает и прямой locked_until, и last_lockout_at + OTP_LOCKOUT_SECONDS:
    даже если state будет переписан без locked_until, момент старта lockout
    (last_lockout_at) не даёт обойти блокировку запросом нового кода.
    Возвращает 0, если активной блокировки нет.
    """
    locked_until = int(state.get("locked_until") or 0)
    last_lockout_at = int(state.get("last_lockout_at") or 0)
    if last_lockout_at:
        locked_until = max(locked_until, last_lockout_at + OTP_LOCKOUT_SECONDS)
    return locked_until


class HHMobileClient:
    def __init__(self, config: MobileConfig | None = None, session: requests.Session | None = None):
        self.config = config or effective_config()[0]
        self.session = session or requests.Session()
        # Единый egress: мобильный OTP/API-трафик тоже идёт через HH_PROXY, если он
        # задан (иначе сервер светится hh.ru с двух IP — реального и прокси).
        # requests[socks] поддерживает socks5h через PySocks.
        # Fail-closed: если прокси задан, но механизм egress сломан/недоступен —
        # падаем с ошибкой, а НЕ молча идём напрямую (раньше любой внутренний сбой
        # превращался в прямой egress в обход заданной защиты).
        try:
            from app.hh_http import egress_proxy
            _proxy = egress_proxy()
        except Exception as exc:
            if os.environ.get("HH_PROXY", "").strip():
                raise MobileAuthError(
                    "HH_PROXY задан, но egress-прокси не удалось применить — прямой выход запрещён",
                    status_code=503,
                ) from exc
            # HH_PROXY не задан — легитимный режим работы без прокси.
            _proxy = ""
        if _proxy and not self.session.proxies:
            self.session.proxies = {"http": _proxy, "https": _proxy}

    def _request(self, method: str, path: str, *, token: str = "", data=None, params=None) -> Any:
        headers = {"Accept": "application/json", "User-Agent": self.config.user_agent}
        if token:
            headers.update({"Authorization": f"Bearer {token}", "x-hh-app-active": "true"})
        else:
            headers.update({
                "Authorization": f"Bearer {self.config.app_client_token}",
                "X-Force-App-Access": "true",
            })
        # Per-request прокси: egress читается в момент запроса, а не один раз в
        # __init__, чтобы runtime-смена HH_PROXY через app.hh_http.set_proxy()
        # подхватывалась долгоживущими клиентами без пересоздания. Когда прокси
        # не задан — kwarg не передаём вовсе: session.proxies из __init__
        # продолжает действовать (в т.ч. у injected sessions со своими настройками).
        try:
            from app.hh_http import egress_proxies
            _runtime_proxies = egress_proxies()
        except Exception:
            # Конфиг egress недоступен — остаёмся на session-level прокси из
            # __init__, где fail-closed проверка уже прошла.
            _runtime_proxies = None
        kwargs: dict[str, Any] = dict(data=data, params=params, headers=headers, timeout=20)
        if _runtime_proxies is not None:
            kwargs["proxies"] = _runtime_proxies
        try:
            response = self.session.request(
                method, self.config.base_url + "/" + path.lstrip("/"),
                **kwargs,
            )
        except requests.RequestException as exc:
            raise MobileAuthError("Не удалось соединиться с HH") from exc
        if response.status_code >= 400:
            raise _safe_error(response)
        try:
            return response.json() if response.content else {}
        except ValueError as exc:
            raise MobileAuthError("HH вернул некорректный JSON") from exc

    def request_code(self, login: str, login_type: str, notification_type: str | None = None) -> dict:
        if login_type not in {"phone", "email"}:
            raise MobileAuthError("Тип входа должен быть phone или email")
        with _otp_lock:
            now = int(time.time())
            state = _read_object(STATE_FILE)
            # Lockout за перебор кодов НЕ снимается запросом нового кода: пока не
            # истёк TTL от last_lockout_at, новый код не выдаётся, attempts и
            # активный challenge не трогаются (иначе обход: 5 попыток -> подождал
            # throttle -> новый код -> ещё 5 попыток, и так бесконечно).
            locked_until = _otp_locked_until(state)
            if locked_until > now:
                raise MobileAuthError(
                    "Превышено число попыток. Повторите позже.",
                    status_code=429, retry_after=locked_until - now,
                )
            # Throttle: не чаще одного запроса кода в REQUEST_CODE_THROTTLE_SECONDS (анти-SMS-бомба).
            if state and now - int(state.get("requested_at") or 0) < REQUEST_CODE_THROTTLE_SECONDS:
                wait = REQUEST_CODE_THROTTLE_SECONDS - (now - int(state.get("requested_at") or 0))
                raise MobileAuthError(
                    "Слишком частые запросы кода. Повторите позже.",
                    status_code=429, retry_after=wait,
                )
            # Дневной лимит: не более REQUEST_CODE_DAILY_LIMIT кодов в сутки на логин.
            today = date.today().isoformat()
            request_count = int(state.get("request_count") or 0) if state.get("request_day") == today else 0
            if request_count >= REQUEST_CODE_DAILY_LIMIT:
                raise MobileAuthError(
                    "Достигнут дневной лимит запросов кода. Повторите завтра.",
                    status_code=429, retry_after=_seconds_until_midnight(),
                )
            payload = self._request(
                "POST", f"one_time_password/{login_type}/generate",
                params={"allow_multiaccount_creation": "false"},
                data={"login": login, "notification_type": notification_type or ""},
            )
            if not isinstance(payload, dict):
                raise MobileAuthError("Неожиданный ответ HH")
            # Новый код — новый цикл попыток: lockout к этому моменту уже истёк
            # (проверен выше), attempts сбрасываются, блокировка не переносится.
            _atomic_write(STATE_FILE, {
                "login": login, "login_type": login_type,
                "requested_at": int(time.time()),
                "retry_after": payload.get("can_request_code_again_in", 0),
                "code_length": payload.get("code_length"),
                "notification_type": payload.get("notification_type"),
                "request_day": today,
                "request_count": request_count + 1,
                "attempts": 0,
            })
            return payload

    def login(self, code: str) -> tuple[dict, dict, list]:
        # Mutex на весь сценарий: защита от параллельного перебора из threadpool
        # и от перезаписи STATE_FILE одновременными запросами.
        with _otp_lock:
            now = int(time.time())
            state = _read_object(STATE_FILE)
            if not state.get("login") or state.get("login_type") not in {"phone", "email"}:
                raise MobileAuthError("Сначала запросите код подтверждения")
            locked_until = _otp_locked_until(state)
            if locked_until > now:
                raise MobileAuthError(
                    "Превышено число попыток. Повторите позже.",
                    status_code=429, retry_after=locked_until - now,
                )
            if now - int(state.get("requested_at") or 0) > OTP_STATE_TTL_SECONDS:
                raise MobileAuthError("Код подтверждения истёк. Запросите новый код.", status_code=410)
            expected = state.get("code_length")
            if not code or (expected and (not code.isdigit() or len(code) != int(expected))):
                raise MobileAuthError(f"Введите цифровой код длиной {expected}" if expected else "Введите код")
            try:
                tokens = self._request(
                    "POST", f"one_time_password/{state['login_type']}/login",
                    params={"allow_multiaccount_creation": "false"},
                    data={"login": state["login"], "confirmation_code": code, "user_type": "applicant"},
                )
            except MobileAuthError:
                # Любая ошибка подтверждения (неверный/истёкший код и т.п.) — неудачная попытка.
                # 5-я попытка ещё отдаёт честный ответ HH; lockout срабатывает на следующей.
                attempts = int(state.get("attempts") or 0) + 1
                state["attempts"] = attempts
                if attempts >= OTP_MAX_ATTEMPTS:
                    lockout_start = int(time.time())
                    state["locked_until"] = lockout_start + OTP_LOCKOUT_SECONDS
                    # last_lockout_at фиксирует момент старта блокировки: по нему
                    # request_code проверяет TTL и не сбрасывает lockout новым кодом.
                    state["last_lockout_at"] = lockout_start
                _atomic_write(STATE_FILE, state)
                raise
            if not isinstance(tokens, dict) or not tokens.get("access_token"):
                raise MobileAuthError("Ответ HH не содержит access_token")
            now = int(time.time())
            tokens["obtained_at"] = now
            if tokens.get("expires_in") is not None:
                tokens["expires_at"] = now + int(tokens["expires_in"])
            me = self._request("GET", "me", token=tokens["access_token"], params={"with_user_statuses": "true"})
            resumes_payload = self._request("GET", "resumes/mine", token=tokens["access_token"])
            resumes = resumes_payload.get("items", []) if isinstance(resumes_payload, dict) else []
            return tokens, (me if isinstance(me, dict) else {}), [x for x in resumes if isinstance(x, dict)]

    def collect_vacancies(self, token: str, resumes: list[dict], per_page: int = 20) -> dict[str, Any]:
        result: dict[str, Any] = {"fetched_at": int(time.time()), "by_resume": {}}
        for resume in resumes:
            resume_id = str(resume.get("id") or "").strip()
            if not resume_id:
                continue
            items, page, pages = [], 0, 1
            while page < pages:
                payload = self._request(
                    "GET", f"resumes/{resume_id}/similar_vacancies", token=token,
                    params={"page": page, "per_page": per_page, "responses_count_enabled": "true",
                            "with_chat_info": "true", "check_misleading_vacancy_alert": "true"},
                )
                if not isinstance(payload, dict):
                    break
                items.extend(x for x in payload.get("items", []) if isinstance(x, dict))
                pages = min(max(int(payload.get("pages", 1)), 1), 100)
                page += 1
            result["by_resume"][resume_id] = {"title": resume.get("title", ""), "items": items}
        return result

    def create_browser_cookies(self, token: str, me: dict) -> dict[str, str]:
        """Follow the Android app's official autologin bridge into hh.ru WebView.

        APK path: GET /autologin_key/{hhid} -> append ``loginkey`` to an hh.ru
        URL -> WebView/CookieManager receives Set-Cookie.  Redirects are followed
        manually so the one-time key and bearer token can never reach another host.
        """
        hhid = str(me.get("id") or "").strip()
        if not hhid:
            raise MobileAuthError("Ответ /me не содержит id для autologin")
        payload = self._request("GET", f"autologin_key/{quote(hhid, safe='')}", token=token)
        key = payload.get("key") if isinstance(payload, dict) else None
        if not isinstance(key, str) or not key:
            raise MobileAuthError("HH не вернул ключ autologin")

        url = "https://hh.ru/?" + urlencode({"loginkey": key})
        headers = {"Accept": "text/html,application/xhtml+xml", "User-Agent": self.config.user_agent}
        for _ in range(10):
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or not (host == "hh.ru" or host.endswith(".hh.ru")):
                raise MobileAuthError("HH autologin попытался перейти на внешний адрес")
            try:
                response = self.session.get(url, headers=headers, timeout=20, allow_redirects=False)
            except requests.RequestException as exc:
                raise MobileAuthError("Не удалось открыть штатный HH autologin URL") from exc
            if response.status_code not in {301, 302, 303, 307, 308}:
                if response.status_code >= 400:
                    raise _safe_error(response)
                break
            location = response.headers.get("Location", "")
            if not location:
                break
            url = urljoin(url, location)
        else:
            raise MobileAuthError("Слишком много перенаправлений HH autologin")

        cookies: dict[str, str] = {}
        for cookie in self.session.cookies:
            domain = (cookie.domain or "").lstrip(".").lower()
            if domain == "hh.ru" or domain.endswith(".hh.ru"):
                if cookie.name in {"hhtoken", "hhuid", "_xsrf", "crypted_id"}:
                    cookies[cookie.name] = cookie.value
        if me.get("crypted_id") and not cookies.get("crypted_id"):
            cookies["crypted_id"] = str(me["crypted_id"])
        if not cookies.get("hhtoken") or not cookies.get("_xsrf"):
            raise MobileAuthError("Autologin завершился без обязательных hhtoken/_xsrf cookies")
        return cookies


def upsert_browser_sessions(cookies: dict[str, str], me: dict, resumes: list[dict]) -> int:
    """Merge verified autologin cookies into one browser session per HH user."""
    if not cookies.get("hhtoken") or not cookies.get("_xsrf"):
        raise MobileAuthError("Нельзя сохранить неполную браузерную сессию")
    from app.storage import load_browser_sessions, save_browser_sessions

    sessions = load_browser_sessions()
    if not isinstance(sessions, list):
        sessions = []
    first_name = str(me.get("first_name") or "HH").strip()
    last_name = str(me.get("last_name") or "").strip()
    display_name = (first_name + " " + last_name).strip()
    user_id = str(me.get("id") or "").strip()
    all_resumes = [{"hash": str(r.get("id")).strip(), "title": r.get("title", "")}
                   for r in resumes if isinstance(r, dict) and str(r.get("id") or "").strip()]
    hashes = {r["hash"] for r in all_resumes}
    existing = next((s for s in sessions if isinstance(s, dict) and user_id and str(s.get("user_id") or "") == user_id), None)
    if existing is None:
        existing = next((s for s in sessions if isinstance(s, dict) and hashes & {
            str(r.get("hash") or "") for r in (s.get("all_resumes") or []) if isinstance(r, dict)
        }), None)
    if existing is not None:
        active = str(existing.get("resume_hash") or "")
        known = {r["hash"]: r for r in all_resumes}
        for old in existing.get("all_resumes") or []:
            if isinstance(old, dict) and str(old.get("hash") or "") not in known:
                known[str(old.get("hash"))] = old
        existing.update({"user_id": user_id, "cookies": dict(cookies), "all_resumes": list(known.values()),
                         "use_oauth": True, "mode": "mobile"})
        if not active:
            existing["resume_hash"] = all_resumes[0]["hash"] if all_resumes else ""
    else:
        sessions.append({
                "user_id": user_id,
                "name": display_name or "HH Mobile",
                "short": first_name or "HH",
                "color": "cyan",
                "cookies": dict(cookies),
                "resume_hash": all_resumes[0]["hash"] if all_resumes else "",
                "enabled": True,
                "bot_active": False,
                "paused": False,
                "all_resumes": all_resumes,
                "degraded_fallback_enabled": False,
                "use_oauth": True,
                "mode": "mobile",  # mobile OTP flow → mobile-clients (Hedi, hh_recommendations и т.д.)
                "urls": [],
                "url_pages": {},
            })
    save_browser_sessions(sessions)
    try:
        from app.instances import bot
        bot.temp_sessions[:] = sessions
    except Exception:
        pass
    return 1


def auth_status() -> dict[str, Any]:
    state = _read_object(STATE_FILE)
    if not state:
        return {"stage": "idle"}
    # code_length намеренно не отдаём: длина кода — разведка для атакующего.
    return {
        "stage": "code_requested", "login_masked": mask_login(str(state.get("login", ""))),
        "login_type": state.get("login_type"), "requested_at": state.get("requested_at"),
        "retry_after": state.get("retry_after", 0),
        "notification_type": state.get("notification_type"),
    }


def clear_auth_state() -> None:
    STATE_FILE.unlink(missing_ok=True)
