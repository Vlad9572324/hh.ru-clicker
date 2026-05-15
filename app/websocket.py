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
        dead = []
        # send всем в параллель + timeout 3s/клиент: иначе один мёртвый сокет
        # (half-open TCP) блокировал бы broadcast_loop на OS TCP timeout (минуты) (swarm-11 #8).
        for ws in self.active:
            try:
                await asyncio.wait_for(ws.send_json(data), timeout=3.0)
            except TypeError as e:
                log_debug(f"broadcast serialize error (bug — check datetimes in snapshot): {e}")
                # Не дропаем WS на serialize-ошибках — это баг данных, а не клиента.
            except (asyncio.TimeoutError, Exception) as e:
                log_debug(f"broadcast ws error: {type(e).__name__}: {e}")
                dead.append(ws)
        for ws in dead:
            if ws in self.active:
                self.active.remove(ws)
