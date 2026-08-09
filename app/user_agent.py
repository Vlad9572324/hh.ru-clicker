"""Shared APK-compatible User-Agent for every HH request."""

from app.logging_utils import log_debug


DEFAULT_MOBILE_USER_AGENT = (
    "ru.hh.android/26.29.11476, Device: Pixel 10, Android OS: 17 "
    "(UUID: 8f42e879-43c7-4d86-a671-31ea36ed924b)"
)
DEFAULT_WEBVIEW_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _ascii(value: str) -> str:
    """Match APK Regex("[^\\x00-\\x7F]").replace(value, "")."""
    return value.encode("ascii", errors="ignore").decode("ascii")


def mobile_user_agent() -> str:
    """Build the current Android UA from editable mobile-auth settings."""
    try:
        from app.mobile_auth import effective_config

        cfg, _ = effective_config()
        return _ascii(cfg.user_agent)
    except Exception as exc:
        log_debug(f"User-Agent: failed to load mobile settings: {exc}")
        return DEFAULT_MOBILE_USER_AGENT


def webview_user_agent(base_user_agent: str = DEFAULT_WEBVIEW_USER_AGENT) -> str:
    """Match UserAgentGenerator.a(): existing WebView UA + Android app UA."""
    return f"{_ascii(base_user_agent).strip()} {mobile_user_agent()}".strip()
