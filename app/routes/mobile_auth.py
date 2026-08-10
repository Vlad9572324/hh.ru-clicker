"""Web API for HH phone/email OTP authentication."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.mobile_auth import (
    HHMobileClient, MobileAuthError, auth_status, clear_auth_state,
    generate_device_uuid, public_config, reset_config, save_config,
    upsert_browser_sessions,
)
from app.oauth import import_mobile_tokens, remove_mobile_tokens
from app.logging_utils import log_debug


router = APIRouter(prefix="/api/mobile-auth", tags=["mobile-auth"])


class SettingsBody(BaseModel):
    values: dict


class RequestCodeBody(BaseModel):
    login: str
    login_type: str
    notification_type: str | None = None


class VerifyBody(BaseModel):
    code: str


def _error(exc: MobileAuthError):
    return JSONResponse(
        {"ok": False, "error": str(exc), "retry_after": exc.retry_after,
         "captcha_url": exc.captcha_url},
        status_code=exc.status_code if 400 <= exc.status_code < 500 else 502,
    )


@router.get("/settings")
async def get_settings():
    try:
        return {"ok": True, **public_config(), "priority": "web > environment > file > default"}
    except MobileAuthError as exc:
        return _error(exc)


@router.put("/settings")
async def put_settings(body: SettingsBody):
    try:
        return {"ok": True, **save_config(body.values)}
    except MobileAuthError as exc:
        return _error(exc)


@router.post("/settings/validate")
async def validate_settings(body: SettingsBody):
    try:
        # Validation uses the same path as persistence; restore is unnecessary because
        # this endpoint intentionally validates effective values without an HH request.
        from app.mobile_auth import effective_config, _coerce
        current, _ = effective_config()
        merged = current.__dict__.copy()
        for key, value in body.values.items():
            if value not in ("", "********", None):
                merged[key] = value
        values = _coerce(merged)
        from app.mobile_auth import MobileConfig
        return {"ok": True, "user_agent": MobileConfig(**values).user_agent}
    except MobileAuthError as exc:
        return _error(exc)


@router.post("/settings/reset")
async def restore_defaults():
    try:
        return {"ok": True, **reset_config()}
    except MobileAuthError as exc:
        return _error(exc)


@router.post("/settings/uuid")
async def new_uuid():
    return {"ok": True, "device_uuid": generate_device_uuid()}


@router.get("/status")
async def get_status():
    return {"ok": True, **auth_status()}


@router.post("/request-code")
async def request_code(body: RequestCodeBody):
    try:
        return await run_in_threadpool(_request_code, body)
    except MobileAuthError as exc:
        return _error(exc)


def _request_code(body: RequestCodeBody):
    login = body.login.strip()
    if not login:
        raise MobileAuthError("Введите телефон или email")
    result = HHMobileClient().request_code(login, body.login_type, body.notification_type)
    return {"ok": True, **auth_status(), "can_request_code_again_in": result.get("can_request_code_again_in", 0)}


def _verify_code(body: VerifyBody):
    client = HHMobileClient()
    log_debug("mobile_auth verify: login start")
    tokens, me, resumes = client.login(body.code.strip())
    log_debug(f"mobile_auth verify: login done, resumes={len(resumes)}")
    # Успешный вход должен материализовать настройки даже при значениях по умолчанию.
    save_config({})
    try:
        log_debug("mobile_auth verify: import_mobile_tokens start")
        imported = import_mobile_tokens(tokens, resumes, me)
        log_debug(f"mobile_auth verify: import_mobile_tokens done, imported={imported}")
    except (TypeError, ValueError, OSError) as exc:
        log_debug(f"mobile_auth verify: import_mobile_tokens error: {type(exc).__name__}: {exc}")
        raise MobileAuthError("Токены получены, но не удалось безопасно обновить oauth_tokens.json") from exc

    # Similar vacancies are an optional, potentially multi-minute operation.
    # They are loaded lazily by the regular account UI after verify.
    vacancies_count = 0
    try:
        log_debug("mobile_auth verify: create_browser_cookies start")
        cookies = client.create_browser_cookies(tokens["access_token"], me)
        log_debug(f"mobile_auth verify: create_browser_cookies done, cookies={len(cookies)}")
        log_debug("mobile_auth verify: upsert_browser_sessions start")
        browser_sessions = upsert_browser_sessions(cookies, me, resumes)
        log_debug(f"mobile_auth verify: upsert_browser_sessions done, sessions={browser_sessions}")
    except MobileAuthError as exc:
        log_debug(f"mobile_auth verify: browser session error: {type(exc).__name__}: {exc}")
        raise MobileAuthError(
            f"Вход выполнен, но аккаунт не добавлен: {exc}",
            status_code=exc.status_code,
        ) from exc
    if browser_sessions <= 0:
        log_debug("mobile_auth verify: upsert_browser_sessions returned zero")
        raise MobileAuthError("Вход выполнен, но браузерная сессия не создана", status_code=500)
    clear_auth_state()
    return {
        "ok": True, "stage": "authenticated", "user": {
            "id": me.get("id"), "first_name": me.get("first_name"), "last_name": me.get("last_name"),
        },
        "resumes": len(resumes), "oauth_tokens_imported": imported,
        "vacancies_count": vacancies_count, "vacancies_deferred": True, "vacancies_error": "",
        "browser_session_created": browser_sessions > 0,
        "browser_sessions_updated": browser_sessions,
        "browser_session_note": (
            f"Обновлено браузерных сессий: {browser_sessions}."
            if browser_sessions else "Браузерная сессия не создана"
        ),
    }


@router.post("/verify")
async def verify_code(body: VerifyBody):
    try:
        # Весь сценарий использует синхронный HTTP и может занимать минуты.
        return await run_in_threadpool(_verify_code, body)
    except MobileAuthError as exc:
        return _error(exc)


@router.post("/logout")
async def logout():
    clear_auth_state()
    removed = remove_mobile_tokens()
    return {"ok": True, "stage": "idle", "removed_tokens": removed, "note": "Локальное состояние и мобильные OAuth-токены удалены."}
