"""
HTTP-роуты управления WS-слушателем websocket.hh.ru (Phase 1, read-only push).

Сам слушатель живёт в app/ws_manager.py (singleton `ws_manager`) — здесь только
тонкие HTTP-обёртки: включение/выключение слушателя для аккаунта + общий статус.

ws_manager пишется параллельно с роутами, поэтому импорт ленивый: пока модуля
нет, роуты честно отдают 503 вместо того чтобы ронять всё приложение.
"""

import inspect

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.instances import bot


router = APIRouter()


def _err(status_code: int, error: str) -> JSONResponse:
    """Единый формат ошибок: {"ok": False, "error": ...} + HTTP-статус."""
    return JSONResponse({"ok": False, "error": error}, status_code=status_code)


def _get_ws_manager():
    """Ленивый импорт ws_manager. Поднимает ImportError, если модуль ещё не готов."""
    from app.ws_manager import ws_manager
    return ws_manager


async def _toggle(idx: int, action: str):
    """Общий каркас enable/disable: валидация idx → вызов ws_manager."""
    # Валидация как в accounts.py: только существующие основные аккаунты.
    if not (0 <= idx < len(bot.account_states)):
        return _err(404, "Аккаунт не найден")
    try:
        ws_manager = _get_ws_manager()
    except ImportError:
        return _err(503, "ws_manager недоступен")
    try:
        result = getattr(ws_manager, action)(idx)
        # ws_manager может оказаться async — поддерживаем оба варианта.
        if inspect.isawaitable(result):
            result = await result
    except Exception as e:
        return _err(500, f"ws_manager: {e}")
    if not isinstance(result, dict):
        result = {"result": result}
    return {"ok": True, **result}


@router.post("/api/ws/{idx}/enable")
async def api_ws_enable(idx: int):
    """Включить WS-слушатель для аккаунта: acc['ws_realtime']=True + старт слушателя.
    Если глобальный флаг CONFIG.use_websocket_realtime выключен, ws_manager вернёт
    статус вида disabled_global — честно пробрасываем его в ответе."""
    return await _toggle(idx, "enable")


@router.post("/api/ws/{idx}/disable")
async def api_ws_disable(idx: int):
    """Выключить WS-слушатель для аккаунта: acc['ws_realtime']=False + стоп."""
    return await _toggle(idx, "disable")


@router.get("/api/ws/status")
async def api_ws_status():
    """Общий статус: глобальный флаг use_websocket_realtime + per-account
    статусы слушателей (connected/reconnecting/no_token/disabled...)."""
    try:
        ws_manager = _get_ws_manager()
    except ImportError:
        return _err(503, "ws_manager недоступен")
    try:
        result = ws_manager.status()
        if inspect.isawaitable(result):
            result = await result
    except Exception as e:
        return _err(500, f"ws_manager: {e}")
    if not isinstance(result, dict):
        result = {"result": result}
    return {"ok": True, **result}
