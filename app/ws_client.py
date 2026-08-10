"""
ws_client.py — WebSocket-клиент push-канала HH.ru (websocket.hh.ru).

Протокол (реверс APK ru.hh.android 26.28.1, подтверждён live-прототипом):

1. Handshake: GET {connection_base}/connection/data?connectionMode=direct
   с заголовками Authorization: Bearer <token>, User-Agent: ru.hh.android/26.28.1,
   x-force-app-access: true → HTTP 200
   {"url": "wss://websocket.hh.ru/ws/connect?sd=<signed blob>&cm=direct"}.
   ВАЖНО: api.hh.ru для этого пути отдаёт 404 — только websocket.hh.ru.
   `sd` короткоживущий → на КАЖДЫЙ реконнект заново запрашиваем /connection/data.
2. Сам WS-коннект БЕЗ auth-заголовков — токен зашит сервером в signed url.
3. Кадры: text JSON {"type": <eventType>, "data": {"eventType": str,
   "time": str, "fromCurrentDevice": bool, "eventData": {...}}}
   (парсинг — app.ws_events.parse_event).
4. Канал строго READ-ONLY: в сокет ничего не отправляется, subscribe-фреймов
   нет; APK-клиент (okhttp) не шлёт пинги → ping_interval=None.
5. Ответ /connection/data и wss-url никогда не логируются целиком:
   sd — живая короткоживущая сессия (см. _mask_ws_url).

Реконнекты — экспоненциальный backoff (1s, 2s, 4s, ... с потолком backoff_max),
счётчик attempt сбрасывается после успешного коннекта. Backoff-сон мгновенно
прерывается вызовом close() (asyncio.Event + asyncio.wait).

Прокси: handshake-GET по умолчанию ходит НАПРЯМУЮ (HH_WS_USE_PROXY=0), даже
если в env заданы HTTP_PROXY/HTTPS_PROXY; HH_WS_USE_PROXY=1 — через прокси
из env HH_PROXY (если задан). Сам WS-сокет — всегда напрямую.
"""

import asyncio
import os
from collections.abc import Callable

import requests
import websockets

from app.logging_utils import log_debug
from app.ws_events import parse_event, WsEvent

__all__ = ["HHWebSocketClient", "WsHandshakeError"]

# User-Agent мобильного APK — протокол воспроизводится один в один.
_MOBILE_UA = "ru.hh.android/26.28.1"


class WsHandshakeError(Exception):
    """Ошибка handshake: /connection/data вернул не-200/нет url, либо WS-коннект не удался."""


def _mask_ws_url(url: str) -> str:
    """Маскировать signed blob `sd` в wss-url — это живая short-lived сессия.

    Полный url никогда не должен попадать в логи; вmasked-виде оставляем
    scheme/host/path и длину sd (полезно для диагностики).
    """
    if not url or "sd=" not in url:
        return url or ""
    head, rest = url.split("sd=", 1)
    amp = rest.find("&")
    sd = rest if amp == -1 else rest[:amp]
    tail = "" if amp == -1 else rest[amp:]
    return f"{head}sd={sd[:8]}...[masked, {len(sd)} chars]{tail}"


class HHWebSocketClient:
    """Read-only слушатель push-канала websocket.hh.ru с авто-реконнектами.

    Типовой цикл использования (см. MobileHHClient.subscribe_events):

        client = HHWebSocketClient(token, on_event=q.put_nowait, label=label)
        task = asyncio.get_running_loop().create_task(client.run_forever())
        ...
        await client.close()
        task.cancel()

    on_event(ws_event) — синхронный колбэк, получает распарсенный WsEvent
    (parse_event(raw); None-кадры пропускаются). Его исключения глотаются:
    один плохой колбэк не должен ронять слушатель.
    on_disconnect() — опциональный колбэк обрыва установленной сессии
    (без аргументов, его исключения тоже глотаются).

    После close() клиент считается остановленным: повторный run_forever
    сразу завершается.
    """

    def __init__(
        self,
        access_token: str,
        on_event: Callable[[WsEvent], None],
        on_disconnect: Callable[[], None] | None = None,
        *,
        label: str = "",
        connection_base: str = "https://websocket.hh.ru",
        backoff_base: float = 1.0,
        backoff_max: float = 60.0,
        backoff_factor: float = 2.0,
    ):
        self._access_token = access_token
        self._on_event = on_event
        self._on_disconnect = on_disconnect
        self._label = label or "ws"
        self._connection_base = connection_base.rstrip("/")
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._backoff_factor = backoff_factor
        # Состояние жизненного цикла.
        self._closed = False
        self._stop_event: asyncio.Event | None = None
        self._ws = None

    # ── Backoff ───────────────────────────────────────────────────────────────

    def _backoff_delay(self, attempt: int) -> float:
        """Чистая формула задержки: base * factor**attempt с потолком backoff_max.

        attempt нумеруется с 0: при дефолтах 1s, 2s, 4s, ... 60s.
        """
        return min(self._backoff_base * (self._backoff_factor ** attempt), self._backoff_max)

    # ── Handshake ─────────────────────────────────────────────────────────────

    def _handshake_proxies(self) -> dict:
        """proxies-dict для handshake-GET.

        HH_WS_USE_PROXY=0 (дефолт) → напрямую: явные None-значения заставляют
        requests игнорировать env-прокси (HTTP_PROXY/HTTPS_PROXY).
        HH_WS_USE_PROXY=1 → через HH_PROXY, если он задан; иначе тоже напрямую.

        Каждый раз возвращаем НОВЫЙ dict: requests.merge_environment_settings
        мутирует переданный dict (setdefault при подмешивании env-прокси).
        """
        if os.environ.get("HH_WS_USE_PROXY", "0").strip() == "1":
            proxy = os.environ.get("HH_PROXY", "").strip()
            if proxy:
                return {"http": proxy, "https": proxy}
        return {"http": None, "https": None}

    async def _fetch_ws_url(self) -> str:
        """Шаг 1: GET /connection/data?connectionMode=direct → signed wss-url.

        requests — блокирующая библиотека, поэтому запрос уходит в поток
        через asyncio.to_thread. sd короткоживущий: метод вызывается заново
        на каждый реконнект. Тело ответа не логируется (там может быть sd).
        """
        endpoint = f"{self._connection_base}/connection/data"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "User-Agent": _MOBILE_UA,
            "x-force-app-access": "true",
        }

        def _get():
            return requests.get(
                endpoint,
                params={"connectionMode": "direct"},
                headers=headers,
                proxies=self._handshake_proxies(),
                timeout=15,
            )

        try:
            r = await asyncio.to_thread(_get)
        except Exception as e:
            # CancelledError — BaseException и сюда не попадает.
            raise WsHandshakeError(f"/connection/data: сетевая ошибка {type(e).__name__}: {e}") from e

        if r.status_code != 200:
            raise WsHandshakeError(f"/connection/data вернул HTTP {r.status_code}")
        try:
            payload = r.json()
        except ValueError as e:
            raise WsHandshakeError("/connection/data вернул не-JSON тело") from e
        ws_url = payload.get("url") if isinstance(payload, dict) else None
        if not isinstance(ws_url, str) or not ws_url.startswith(("wss://", "ws://")):
            raise WsHandshakeError("/connection/data вернул некорректный 'url'")
        return ws_url

    async def connect(self):
        """Handshake + WS-коннект; возвращает открытый сокет.

        Любая ошибка (не-200, нет url в JSON, сеть, WS-handshake) →
        WsHandshakeError. WS-коннект без auth-заголовков: токен зашит в
        signed url, пинги отключены (APK-клиент их не шлёт).
        """
        ws_url = await self._fetch_ws_url()
        try:
            ws = await websockets.connect(ws_url, open_timeout=15, ping_interval=None)
        except Exception as e:
            # Только имя типа: str(e) может содержать url с живой sd.
            raise WsHandshakeError(f"WS-коннект не удался: {type(e).__name__}") from e
        log_debug(f"ws [{self._label}] подключен: {_mask_ws_url(ws_url)}")
        return ws

    # ── Слушатель ─────────────────────────────────────────────────────────────

    async def listen(self, ws):
        """Пассивное слушание: кадры → parse_event → on_event.

        Канал строго read-only — в сокет ничего не отправляется. Возврат при
        обрыве (ConnectionClosed); исключения on_event глотаются с log_debug.
        Прочие исключения пропускаются наверх, в run_forever (backoff).
        """
        try:
            async for message in ws:
                event = parse_event(message)
                if event is None:
                    continue
                try:
                    self._on_event(event)
                except Exception as e:
                    log_debug(f"ws [{self._label}] ошибка on_event: {type(e).__name__}: {e}")
        except websockets.exceptions.ConnectionClosed:
            # Нормальный обрыв — run_forever переподключится с backoff.
            return

    # ── Жизненный цикл ────────────────────────────────────────────────────────

    async def _interruptible_sleep(self, delay: float) -> bool:
        """Backoff-сон: выходит мгновенно, если close() взвёл stop-event.

        Возвращает True, если запрошена остановка (цикл продолжать не нужно).
        """
        if delay <= 0:
            return self._closed
        stop_task = asyncio.get_running_loop().create_task(self._stop_event.wait())
        try:
            await asyncio.wait({stop_task}, timeout=delay)
        finally:
            stop_task.cancel()
            try:
                await stop_task
            except asyncio.CancelledError:
                pass
        return self._closed or self._stop_event.is_set()

    async def _safe_close(self, ws) -> None:
        """Закрыть ws, игнорируя ошибки (он уже может быть закрыт/сломан)."""
        if ws is None:
            return
        try:
            await ws.close()
        except Exception:
            pass

    def _fire_on_disconnect(self) -> None:
        """Колбэк обрыва установленной сессии: без аргументов, глотаем исключения."""
        if self._on_disconnect is None:
            return
        try:
            self._on_disconnect()
        except Exception as e:
            log_debug(f"ws [{self._label}] ошибка on_disconnect: {type(e).__name__}: {e}")

    async def run_forever(self) -> None:
        """Цикл connect → listen → backoff → реконнект. Выход только по close().

        Счётчик attempt сбрасывается после успешного коннекта: серия фейлов
        наращивает задержку (1s, 2s, 4s, ... до backoff_max), а после
        успешной сессии следующий обрыв снова ждёт лишь backoff_base.
        Backoff-сон прерывается мгновенно вызовом close().
        """
        if self._stop_event is None:
            self._stop_event = asyncio.Event()
        attempt = 0
        while not self._closed:
            try:
                ws = await self.connect()
            except Exception as e:
                log_debug(f"ws [{self._label}] ошибка коннекта: {e}")
            else:
                if self._closed:
                    # close() вызван, пока шёл handshake: гасим сокет и выходим.
                    await self._safe_close(ws)
                    break
                attempt = 0
                self._ws = ws
                try:
                    await self.listen(ws)
                except Exception as e:
                    log_debug(f"ws [{self._label}] ошибка слушателя: {type(e).__name__}: {e}")
                finally:
                    self._ws = None
                    await self._safe_close(ws)
                if self._closed:
                    break
                self._fire_on_disconnect()

            # Экспоненциальный backoff до следующего коннекта.
            delay = self._backoff_delay(attempt)
            attempt += 1
            log_debug(f"ws [{self._label}] реконнект через {delay:.0f}s (попытка {attempt})")
            if await self._interruptible_sleep(delay):
                break

    async def close(self) -> None:
        """Остановка: флаг, закрытие активного WS, завершение run_forever.

        Идемпотентен; безопасен при вызове до/во время/после run_forever.
        """
        already_closed = self._closed
        self._closed = True
        if self._stop_event is not None:
            self._stop_event.set()
        ws, self._ws = self._ws, None
        if ws is not None:
            await self._safe_close(ws)
        if not already_closed:
            log_debug(f"ws [{self._label}] остановлен")
