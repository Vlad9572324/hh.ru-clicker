"""
Logging utilities and login-page detection helper.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

DEBUG_LOG_FILE = DATA_DIR / "debug.log"

_logger = logging.getLogger("hh_bot")
if not _logger.handlers:
    _logger.setLevel(logging.DEBUG)
    _handler = RotatingFileHandler(
        DEBUG_LOG_FILE,
        maxBytes=50 * 1024 * 1024,  # 50MB per file
        backupCount=3,               # debug.log + .1 + .2 + .3 = до 200MB
        encoding="utf-8",
    )
    _handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    _logger.addHandler(_handler)
    _logger.propagate = False


def log_debug(message: str):
    """Записать отладочное сообщение в файл (с ротацией)."""
    _logger.debug(message)


def _is_login_page(html: str) -> bool:
    """Определить, является ли HTML страница страницей входа HH (протухшие куки)."""
    if not html:
        return False
    return (
        '"/account/login"' in html
        or "hh.ru/account/login" in html
        or "Войти в аккаунт" in html
        or '"accountLogin"' in html
    )
