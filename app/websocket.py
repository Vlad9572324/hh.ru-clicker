"""
WebSocket connection manager for broadcasting state updates.
"""

import asyncio

from fastapi import WebSocket

from app.logging_utils import log_debug


class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        if not self.active:
            return
        # Параллельная отправка всем клиентам сразу (gather), не последовательно.
        # Раньше: 50 половинно-открытых сокетов × 3s timeout = 150s блокированный
        # broadcast loop (kimi-r13-2 #8). Теперь все таймауты идут одновременно → max 3s total.
        # Snapshot active list — иначе concurrent disconnect() мутирует во время iteration.
        active_snapshot = list(self.active)

        async def _send_one(ws):
            try:
                await asyncio.wait_for(ws.send_json(data), timeout=3.0)
                return None
            except TypeError as e:
                # Serialize-ошибка — баг данных, не клиента; не дропаем сокет.
                log_debug(f"broadcast serialize error: {e}")
                return None
            except (asyncio.TimeoutError, Exception) as e:
                log_debug(f"broadcast ws error: {type(e).__name__}: {e}")
                return ws  # mark dead

        results = await asyncio.gather(
            *[_send_one(ws) for ws in active_snapshot],
            return_exceptions=False,
        )
        for dead_ws in results:
            if dead_ws is not None and dead_ws in self.active:
                self.active.remove(dead_ws)
