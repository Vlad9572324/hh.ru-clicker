"""
Logging utilities and login-page detection helper.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

DATA_DIR = Path("data")
DEBUG_LOG_FILE = DATA_DIR / "debug.log"

_logger = None
_logger_lock_init = False


def _get_logger() -> logging.Logger:
    """Lazy-init RotatingFileHandler. Создание handler'а откладывается до первого
    log_debug() чтобы import работал даже когда data/ недоступен (например в тестах
    или когда файл root-owned)."""
    global _logger, _logger_lock_init
    if _logger is not None:
        return _logger
    if _logger_lock_init:
        # Re-entrant защита: если init упал — не пытаемся снова, отдаём silent logger.
        return logging.getLogger("hh_bot_null")
    _logger_lock_init = True
    try:
        DATA_DIR.mkdir(exist_ok=True)
        lg = logging.getLogger("hh_bot")
        lg.setLevel(logging.DEBUG)
        handler = RotatingFileHandler(
            DEBUG_LOG_FILE,
            maxBytes=50 * 1024 * 1024,  # 50MB на файл
            backupCount=3,               # debug.log + .1 + .2 + .3 = до 200MB
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        lg.addHandler(handler)
        lg.propagate = False
        _logger = lg
        return lg
    except Exception:
        # data/ unreadable / permission denied — fall back на silent stderr.
        return logging.getLogger("hh_bot_null")


def log_debug(message: str):
    """Записать отладочное сообщение в файл (с ротацией)."""
    _get_logger().debug(message)


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
