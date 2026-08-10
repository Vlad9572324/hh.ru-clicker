"""Тесты app.ws_client.HHWebSocketClient (Phase 1, push-канал websocket.hh.ru).

Написаны строго по зафиксированному контракту, независимо от реализации:

    HHWebSocketClient(access_token, on_event, on_disconnect=None, *, label="",
                      connection_base="https://websocket.hh.ru",
                      backoff_base=1.0, backoff_max=60.0, backoff_factor=2.0)
    async connect() -> ws     # GET {base}/connection/data?connectionMode=direct
    async listen(ws)          # цикл чтения кадров
    async run_forever()       # connect+listen с reconnect'ом, выход по close()
    async close()             # graceful, идемпотентный
    _backoff_delay(attempt)   # backoff_base * backoff_factor**attempt, <= backoff_max

Сеть полностью офлайн (только 127.0.0.1):
- GET-handshake мокается библиотекой `responses` (regex на URL — хост и query
  не важны; перехват глобальный, поэтому работает и из треда asyncio.to_thread);
- вместо реального push-сервера — фейковый websockets.serve на эфемерном порту.

pytest-asyncio НЕ установлен: каждый асинхронный сценарий запускается из
синхронной тест-функции через asyncio.run(...). Все backoff'ы крошечные
(0.01 c), суммарный прогон — единицы секунд.
"""

import asyncio
import json
import re

import pytest
import responses
import websockets

from app.ws_client import HHWebSocketClient, WsHandshakeError
from app.ws_events import WsEvent

# Regex на URL handshake: не фиксируем ни хост, ни точный query-параметр —
# важен только путь /connection/data (контракт: GET {connection_base}/connection/data).
HANDSHAKE_URL_RE = re.compile(r".*/connection/data.*")


# ── Вспомогательные хелперы ────────────────────────────────────────────────


def _make_client(on_event, *, on_disconnect=None,
                 backoff_base=0.01, backoff_max=0.05):
    """Клиент с тестовым токеном и крошечными backoff'ами (офлайн-прогон)."""
    return HHWebSocketClient(
        "test-access-token",
        on_event,
        on_disconnect=on_disconnect,
        label="test",
        backoff_base=backoff_base,
        backoff_max=backoff_max,
        backoff_factor=2.0,
    )


def _valid_frame(chat_id="123456", text="hi"):
    """Валидный кадр push-канала (формат из реверса APK)."""
    return json.dumps({
        "type": "chat_message_create",
        "data": {
            "eventType": "chat_message_create",
            "time": "2026-08-10T12:00:00Z",
            "fromCurrentDevice": False,
            "eventData": {"chatId": chat_id, "text": text},
        },
    })


async def _start_ws_server(handler):
    """Фейковый push-сервер на 127.0.0.1 с эфемерным портом → (server, port)."""
    server = await websockets.serve(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def _stop_ws_server(server):
    server.close()
    await server.wait_closed()


async def _await_task(task, timeout=3.0):
    """Ждём завершения задачи run_forever.

    CancelledError допускается (cancel — легитимный способ остановки),
    любое другое исключение проваливает тест. Таймаут защищает от зависания.
    """
    try:
        await asyncio.wait_for(task, timeout)
    except asyncio.CancelledError:
        pass


# ── 1. connect → receive → dispatch ────────────────────────────────────────


def test_connect_receive_dispatch():
    """Handshake → ws-коннект → валидный кадр доставлен, мусор пропущен."""

    async def scenario():
        events = []
        got_event = asyncio.Event()

        def on_event(ev):
            events.append(ev)
            got_event.set()

        async def handler(ws, path=None):
            # Один валидный кадр + два мусорных (не-JSON и пустой объект).
            await ws.send(_valid_frame())
            await ws.send("not json")
            await ws.send("{}")
            # Держим соединение открытым, чтобы клиент оставался в listen-цикле.
            try:
                while True:
                    await ws.recv()
            except websockets.ConnectionClosed:
                pass

        server, port = await _start_ws_server(handler)
        try:
            with responses.RequestsMock(assert_all_requests_are_fired=False) as rsp:
                rsp.add(
                    responses.GET,
                    HANDSHAKE_URL_RE,
                    json={"url": f"ws://127.0.0.1:{port}/"},
                    status=200,
                )
                client = _make_client(on_event)
                task = asyncio.create_task(client.run_forever())
                try:
                    await asyncio.wait_for(got_event.wait(), 3.0)
                    # Даём мусорным кадрам дойти — они не должны стать событиями.
                    await asyncio.sleep(0.2)

                    assert len(rsp.calls) == 1, "один handshake на одно соединение"
                    assert len(events) == 1, "мусорные кадры пропускаются"
                    ev = events[0]
                    assert isinstance(ev, WsEvent)
                    assert ev.type == "chat_message_create"
                    assert ev.chat_id == "123456"
                    assert ev.from_current_device is False
                    assert ev.timestamp == "2026-08-10T12:00:00Z"
                    assert ev.event_data == {"chatId": "123456", "text": "hi"}
                finally:
                    await client.close()
                    await _await_task(task)
        finally:
            await _stop_ws_server(server)

    asyncio.run(scenario())


# ── 2. reconnect на disconnect ─────────────────────────────────────────────


def test_reconnect_after_server_disconnect():
    """Сервер рвёт соединение после первого кадра — клиент переподключается."""

    async def scenario():
        events = []
        enough = asyncio.Event()
        disconnects = []
        connect_count = 0

        def on_event(ev):
            events.append(ev)
            # Ждём события минимум с двух разных подключений.
            if len({e.chat_id for e in events}) >= 2:
                enough.set()

        def on_disconnect(*args, **kwargs):
            disconnects.append(1)

        async def handler(ws, path=None):
            nonlocal connect_count
            connect_count += 1
            # Кадр с уникальным chat_id = номер подключения, затем разрыв.
            await ws.send(_valid_frame(chat_id=str(connect_count)))
            await asyncio.sleep(0.05)  # даём кадру уйти до close-handshake
            # Выход из хендлера — сервер закрывает соединение.

        server, port = await _start_ws_server(handler)
        try:
            with responses.RequestsMock(assert_all_requests_are_fired=False) as rsp:
                rsp.add(
                    responses.GET,
                    HANDSHAKE_URL_RE,
                    json={"url": f"ws://127.0.0.1:{port}/"},
                    status=200,
                )
                client = _make_client(on_event, on_disconnect=on_disconnect)
                task = asyncio.create_task(client.run_forever())
                try:
                    await asyncio.wait_for(enough.wait(), 5.0)

                    assert connect_count >= 2, "клиент не переподключился"
                    assert {e.chat_id for e in events} >= {"1", "2"}, \
                        "события должны прийти с обоих подключений"
                    assert len(disconnects) >= 1, \
                        "on_disconnect должен вызываться при разрыве"
                    # Каждый reconnect — новый handshake.
                    assert len(rsp.calls) >= 2
                finally:
                    await client.close()
                    await _await_task(task)
        finally:
            await _stop_ws_server(server)

    asyncio.run(scenario())


# ── 3. backoff series (чистая формула, без сети) ───────────────────────────


def test_backoff_delay_formula_defaults():
    """_backoff_delay при дефолтах (1.0, 60.0, 2.0): 1,2,4,8,16,32,60,60..."""
    client = HHWebSocketClient("t", on_event=lambda *a: None)
    expected = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]
    for attempt, want in enumerate(expected):
        assert client._backoff_delay(attempt) == pytest.approx(want), \
            f"attempt={attempt}"


def test_backoff_delay_formula_custom_and_cap():
    """Кастомные параметры и потолок backoff_max."""
    client = HHWebSocketClient(
        "t", on_event=lambda *a: None,
        backoff_base=0.01, backoff_max=0.05, backoff_factor=2.0,
    )
    got = [client._backoff_delay(i) for i in range(4)]
    assert got == pytest.approx([0.01, 0.02, 0.04, 0.05]), \
        "экспоненциальный рост с потолком backoff_max"


# ── 4. handshake error → retry ─────────────────────────────────────────────


def test_ws_handshake_error_is_exception():
    """WsHandshakeError экспортируется и является исключением."""
    assert issubclass(WsHandshakeError, Exception)


def test_handshake_error_retries_and_clean_stop():
    """GET /connection/data → 500: клиент ретраит, close() останавливает без ошибок."""

    async def scenario():
        with responses.RequestsMock(assert_all_requests_are_fired=False) as rsp:
            rsp.add(
                responses.GET,
                HANDSHAKE_URL_RE,
                json={"error": "internal error"},
                status=500,
            )
            client = _make_client(lambda ev: None)
            task = asyncio.create_task(client.run_forever())
            try:
                # Ждём минимум две попытки handshake (первая + retry после backoff).
                loop = asyncio.get_running_loop()
                deadline = loop.time() + 5.0
                while len(rsp.calls) < 2 and loop.time() < deadline:
                    await asyncio.sleep(0.02)
                assert len(rsp.calls) >= 2, "клиент не ретраит после ошибки handshake"
            finally:
                await client.close()
                await _await_task(task)  # должен завершиться без исключений

            # После close() цикл остановлен: новых попыток handshake нет.
            calls_after_close = len(rsp.calls)
            await asyncio.sleep(0.2)
            assert len(rsp.calls) == calls_after_close, \
                "после close() retry-цикл должен быть остановлен"

    asyncio.run(scenario())


# ── 5. graceful cancel ─────────────────────────────────────────────────────


def test_graceful_close_during_listen_is_idempotent():
    """close() во время активного listen завершает run_forever; повторный close безопасен."""

    async def scenario():
        connected = asyncio.Event()

        async def handler(ws, path=None):
            connected.set()
            try:
                while True:
                    await ws.recv()
            except websockets.ConnectionClosed:
                pass

        server, port = await _start_ws_server(handler)
        try:
            with responses.RequestsMock(assert_all_requests_are_fired=False) as rsp:
                rsp.add(
                    responses.GET,
                    HANDSHAKE_URL_RE,
                    json={"url": f"ws://127.0.0.1:{port}/"},
                    status=200,
                )
                client = _make_client(lambda ev: None)
                task = asyncio.create_task(client.run_forever())
                try:
                    await asyncio.wait_for(connected.wait(), 3.0)
                    await asyncio.sleep(0.05)  # listen точно в цикле чтения

                    await client.close()
                    await _await_task(task)  # без исключений и без зависания

                    # Идемпотентность: повторный close не падает.
                    await client.close()
                finally:
                    if not task.done():
                        task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
        finally:
            await _stop_ws_server(server)

    asyncio.run(scenario())


def test_external_consumer_cancel_pattern():
    """Паттерн MobileHHClient.subscribe_events: close() → task.cancel() → await с подавлением."""

    async def scenario():
        connected = asyncio.Event()
        events = []

        async def handler(ws, path=None):
            connected.set()
            try:
                while True:
                    await ws.recv()
            except websockets.ConnectionClosed:
                pass

        server, port = await _start_ws_server(handler)
        try:
            with responses.RequestsMock(assert_all_requests_are_fired=False) as rsp:
                rsp.add(
                    responses.GET,
                    HANDSHAKE_URL_RE,
                    json={"url": f"ws://127.0.0.1:{port}/"},
                    status=200,
                )
                client = _make_client(events.append)
                task = asyncio.create_task(client.run_forever())
                await asyncio.wait_for(connected.wait(), 3.0)

                # Финализация потребителя ровно как в subscribe_events.
                await client.close()
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
                assert task.done(), "задача run_forever должна быть завершена"
        finally:
            await _stop_ws_server(server)

    asyncio.run(scenario())
