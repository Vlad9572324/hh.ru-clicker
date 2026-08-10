"""Factory HH-клиентов: выбор web/mobile реализации для аккаунта (Phase 0)."""
from app.config import CONFIG
from app.hh_client import HHClient
from app.hh_client_web import WebHHClient
from app.hh_client_mobile import MobileHHClient

# Сентинел ОТСУТСТВУЮЩЕГО поля account["mode"]: object() не совпадает ни с
# None, ни с ""/0, поэтому «поля нет» нормализуется через
# CONFIG.default_client_mode, а не по правилу «не-строка → auto».
_MODE_MISSING = object()


def get_client(account: dict) -> HHClient:
    """Вернуть HH-клиент для аккаунта.

    mode берётся из account["mode"] ("web" | "mobile" | "auto");
    если поля нет — CONFIG.default_client_mode.
    Неизвестный mode трактуется как "web".

    Решение Phase 0 (docs/PHASE_MATRIX.md): "auto" → всегда WebHHClient —
    mobile-клиент ещё не готов (почти все методы кидают NotImplementedError),
    поэтому авто-выбор не должен приводить к mobile даже при живом
    OAuth-токене. MobileHHClient выбирается только при явном mode="mobile".
    """
    mode = _normalize_mode(account.get("mode", _MODE_MISSING))
    if mode == "mobile":
        return MobileHHClient(account)
    return WebHHClient(account)


def _normalize_mode(value):
    """Устойчивая нормализация mode аккаунта (не падает на не-строках).

    _MODE_MISSING (поля "mode" нет) → CONFIG.default_client_mode по тем же
    правилам (финальный fallback → "web");
    не-строка (int/bool/None/...) → "auto";
    строка → strip().lower(), если вне {"web", "mobile", "auto"} →
    CONFIG.default_client_mode по тем же правилам; финальный fallback → "web".
    """
    def _clean(v):
        if isinstance(v, str):
            v = v.strip().lower()
            if v in ("web", "mobile", "auto"):
                return v
        return None

    def _default_mode():
        return _clean(getattr(CONFIG, "default_client_mode", None)) or "web"

    if value is _MODE_MISSING:
        return _default_mode()
    if not isinstance(value, str):
        return "auto"
    return _clean(value) or _default_mode()
