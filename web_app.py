"""Compatibility entry point for the HH.ru FastAPI dashboard."""

import uvicorn

from hh_backend.bot import *  # noqa: F403
from hh_backend.hh_client import *  # noqa: F403
from hh_backend.routes import *  # noqa: F403
from hh_backend.state import *  # noqa: F403
from hh_backend.storage import *  # noqa: F403


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
