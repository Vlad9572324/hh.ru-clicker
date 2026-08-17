"""Stable, per-account Android identities for HH mobile requests."""

from functools import lru_cache
import random
import threading
import uuid

from app.logging_utils import log_debug


DEFAULT_MOBILE_USER_AGENT = (
    "ru.hh.android/26.29.11476, Device: Pixel 10, Android OS: 17 "
    "(UUID: 8f42e879-43c7-4d86-a671-31ea36ed924b)"
)
DEFAULT_WEBVIEW_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEVICE_MODELS = ["Pixel 8", "Pixel 9", "Pixel 10", "Samsung Galaxy S24", "Xiaomi 14"]
ANDROID_RELEASES = ["13", "14", "15"]
APP_VERSION_NAME = "26.28.1"
_identity_lock = threading.Lock()


def generate_device_identity() -> dict[str, str]:
    """Create one Android fingerprint to persist with an account."""
    return {
        "device_uuid": str(uuid.uuid4()),
        "model": random.choice(DEVICE_MODELS),
        "android_release": random.choice(ANDROID_RELEASES),
        "app_version_name": APP_VERSION_NAME,
    }


def ensure_device_identity(acc: dict | None) -> dict | None:
    """Return an account identity, lazily adding one for legacy accounts."""
    if not isinstance(acc, dict):
        return None
    identity = acc.get("device_identity")
    if isinstance(identity, dict) and identity.get("device_uuid"):
        return identity
    # One account can be hit by several workers on startup.  Only one identity
    # may win, otherwise concurrent first requests could expose two UUIDs.
    with _identity_lock:
        identity = acc.get("device_identity")
        if not isinstance(identity, dict) or not identity.get("device_uuid"):
            identity = generate_device_identity()
            acc["device_identity"] = identity
    return identity


def _ascii(value: str) -> str:
    """Match APK Regex("[^\\x00-\\x7F]").replace(value, "")."""
    return value.encode("ascii", errors="ignore").decode("ascii")


def mobile_user_agent(acc: dict | None = None) -> str:
    """Build an Android UA from the stable account identity, or the default."""
    identity = ensure_device_identity(acc) if acc is not None else None
    if identity:
        return _ascii(
            f"ru.hh.android/{identity.get('app_version_name', APP_VERSION_NAME)}, "
            f"Device: {identity.get('model', 'Pixel 10')}, "
            f"Android OS: {identity.get('android_release', '15')} "
            f"(UUID: {identity['device_uuid']})"
        )
    return _default_mobile_user_agent()


@lru_cache(maxsize=1)
def _default_mobile_user_agent() -> str:
    """Build the global fallback UA from editable mobile-auth settings."""
    try:
        from app.mobile_auth import effective_config

        cfg, _ = effective_config()
        return _ascii(cfg.user_agent)
    except Exception as exc:
        log_debug(f"User-Agent: failed to load mobile settings: {exc}")
        return DEFAULT_MOBILE_USER_AGENT


def invalidate_mobile_user_agent_cache() -> None:
    _default_mobile_user_agent.cache_clear()


def webview_user_agent(base_user_agent: str = DEFAULT_WEBVIEW_USER_AGENT) -> str:
    """Return a desktop browser identity for HH web products."""
    return _ascii(base_user_agent).strip()
