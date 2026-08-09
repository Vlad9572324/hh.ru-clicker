"""Web API for HH phone/email OTP authentication."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.mobile_auth import (
    HHMobileClient, MobileAuthError, auth_status, clear_auth_state,
    generate_device_uuid, public_config, reset_config, save_config,
    upsert_browser_sessions,
)
from app.oauth import import_mobile_tokens, remove_mobile_tokens


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
        login = body.login.strip()
        if not login:
            raise MobileAuthError("Введите телефон или email")
        result = HHMobileClient().request_code(login, body.login_type, body.notification_type)
        return {"ok": True, **auth_status(), "can_request_code_again_in": result.get("can_request_code_again_in", 0)}
    except MobileAuthError as exc:
        return _error(exc)


@router.post("/verify")
async def verify_code(body: VerifyBody):
    try:
        client = HHMobileClient()
        tokens, me, resumes = client.login(body.code.strip())
        # A successful login materializes the effective mobile settings in the
        # main config.json even when the user kept all default field values.
        save_config({})
        try:
            imported = import_mobile_tokens(tokens, resumes, me)
        except (TypeError, ValueError, OSError) as exc:
            raise MobileAuthError("Токены получены, но не удалось безопасно обновить oauth_tokens.json") from exc
        vacancy_error = ""
        vacancies_count = 0
        try:
            vacancies = client.collect_vacancies(tokens["access_token"], resumes)
            vacancies_count = sum(len(v.get("items", [])) for v in vacancies["by_resume"].values())
        except MobileAuthError as exc:
            vacancy_error = str(exc)
        browser_error = ""
        browser_sessions = 0
        try:
            cookies = client.create_browser_cookies(tokens["access_token"], me)
            browser_sessions = upsert_browser_sessions(cookies, me, resumes)
        except MobileAuthError as exc:
            browser_error = str(exc)
        clear_auth_state()
        return {
            "ok": True, "stage": "authenticated", "user": {
                "id": me.get("id"), "first_name": me.get("first_name"), "last_name": me.get("last_name"),
            },
            "resumes": len(resumes), "oauth_tokens_imported": imported,
            "vacancies_count": vacancies_count, "vacancies_error": vacancy_error,
            "browser_session_created": browser_sessions > 0,
            "browser_sessions_updated": browser_sessions,
            "browser_session_note": (
                f"Обновлено браузерных сессий: {browser_sessions}."
                if browser_sessions else f"OAuth работает, но браузерная сессия не создана: {browser_error}"
            ),
        }
    except MobileAuthError as exc:
        return _error(exc)


@router.post("/logout")
async def logout():
    clear_auth_state()
    removed = remove_mobile_tokens()
    return {"ok": True, "stage": "idle", "removed_tokens": removed, "note": "Локальное состояние и мобильные OAuth-токены удалены."}
