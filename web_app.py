"""HH.RU Auto Response Bot - FastAPI Web Dashboard"""
import os
import sys
from app.routes import app
import uvicorn


_SAFE_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _resolve_host() -> str:
    """Validate HH_BOT_HOST: by default only loopback allowed.
    Чтобы экспозить наружу, нужно явно выставить HH_BOT_UNSAFE_EXPOSE=1
    (kimi-search-3 #9: defense против env injection).
    """
    raw = os.environ.get("HH_BOT_HOST", "127.0.0.1").strip()
    if raw in _SAFE_HOSTS:
        return raw
    if os.environ.get("HH_BOT_UNSAFE_EXPOSE", "").strip() in ("1", "true", "yes"):
        return raw  # admin signed off
    sys.stderr.write(
        f"[hh-bot] HH_BOT_HOST={raw!r} blocked: not in {_SAFE_HOSTS}. "
        f"Set HH_BOT_UNSAFE_EXPOSE=1 to override (NOT recommended without API auth).\n"
    )
    return "127.0.0.1"


if __name__ == "__main__":
    host = _resolve_host()
    port = int(os.environ.get("HH_BOT_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")
