"""
WsManager — singleton-менеджер WS-слушателей websocket.hh.ru (Phase 1, mobile push-канал).

Одно WS-соединение на аккаунт. Каждый активный слушатель — отдельный
daemon-тред со своим asyncio event loop (asyncio.new_event_loop()), внутри
которого живёт HHWebSocketClient.run_forever() из app/ws_client.py.
Автопереподключение (backoff 1..60с) уже внутри клиента — менеджер только
запускает/останавливает треды и ведёт статусы/статистику.

Модель исполнения и остановки
-----------------------------
- Тред слушателя: токен → клиент → run_forever(), цикл пока не выставлен
  stop_event. OAuth-токен получается синхронно (oauth._obtain_oauth_token)
  внутри треда; если токена нет — статус no_token и ретрай каждые ~30с, пока
  слушатель включён (токен может появиться позже).
- Остановка из другого треда: выставляем entry.stop_event, затем
  asyncio.run_coroutine_threadsafe(client.close(), loop) и join треда с
  таймаутом. close() клиента идемпотентен, run_forever выходит по close().
- Ожидание внутри сессии не блокирует loop (polling stop_event с
  asyncio.sleep), чтобы запланированный через run_coroutine_threadsafe
  close() мог выполниться сразу.

Статусы слушателя (видны в status(), JSON потребляет UI static/index.html)
---------------------------------------------------------------------------
  connecting    — слушатель запущен, соединение устанавливается. Клиент не
                  даёт on_connect-колбэка, поэтому chosen честный вариант:
                  connected ставится только по первому пришедшему событию;
                  до первого события — connecting;
  connected     — соединение живое: подтверждено хотя бы одним событием;
  reconnecting  — обрыв соединения (on_disconnect клиента), клиент
                  реконнектится своим backoff'ом;
  no_token      — нет OAuth-токена, ретрай ~раз в 30с;
  error         — ошибка (ws_client недоступен / run_forever упал);
  disabled      — слушатель выключен (acc["ws_realtime"]=False) ЛИБО
                  приостановлен паузой: suspend()/suspend_account() глушат
                  слушатель и в status() он отдаётся как disabled
                  (пауза = слушатель остановлен до resume);
  disabled_global — acc["ws_realtime"]=True, но глобальный флаг
                  CONFIG.use_websocket_realtime выключен.

Пауза (suspend/resume)
----------------------
suspend() глушит только АКТИВНЫЕ (живые треды) слушатели и запоминает какие
были активны; resume() восстанавливает только их. suspend_account(idx)/
resume_account(idx) — то же для одного аккаунта. Включение слушателя через
enable() во время паузы не стартует тред сразу: намерение запоминается и
слушатель стартует в соответствующем resume.

Все публичные методы синхронные, потокобезопасные (threading.Lock) и не
кидают исключения наружу (всё под try/except + log_debug) — их вызывают
FastAPI-роуты (app/routes/ws.py) и BotManager (app/manager.py).

Импорты app.ws_client и app.instances — ленивые (внутри методов/тредов):
модуль обязан импортироваться даже когда ws_client.py ещё не существует,
и без циклического импорта с app.manager.
"""

import asyncio
import threading
from datetime import datetime

from app.config import CONFIG
from app.logging_utils import log_debug

# Ретрай, пока нет OAuth-токена (он может появиться позже).
_NO_TOKEN_RETRY_SEC = 30.0
# Пауза перед повтором после ошибки (импорт ws_client / падение run_forever /
# ошибка создания клиента) — чтобы не долбить сервер в tight-loop.
_ERROR_RETRY_SEC = 30.0
# Таймауты остановки: исполнение close() в loop клиента и join треда.
_CLOSE_TIMEOUT_SEC = 5.0
_JOIN_TIMEOUT_SEC = 7.0

__all__ = ["ws_manager", "WsManager"]


class _Entry:
    """Состояние WS-слушателя одного аккаунта (все поля — под WsManager._lock,
    кроме stop_event: threading.Event сам по себе потокобезопасен)."""

    __slots__ = (
        "idx", "status", "events_total", "last_event_type", "last_event_at",
        "thread", "loop", "client", "stop_event",
        "suspended", "active_before_suspend",
    )

    def __init__(self, idx: int):
        self.idx = idx
        self.status = "disabled"
        self.events_total = 0
        self.last_event_type: str | None = None
        self.last_event_at: str | None = None   # "HH:MM:SS"
        self.thread: threading.Thread | None = None
        self.loop = None          # asyncio loop треда слушателя
        self.client = None        # HHWebSocketClient (пока живёт в loop)
        self.stop_event = threading.Event()
        self.suspended = False              # слушатель приостановлен паузой
        self.active_before_suspend = False  # был активен в момент suspend


class WsManager:
    """Менеджер WS-слушателей websocket.hh.ru: одно соединение на аккаунт."""

    def __init__(self):
        self._lock = threading.Lock()
        self._entries: dict[int, _Entry] = {}
        self._suspended = False            # глобальная пауза бота
        self._acc_suspended: set[int] = set()  # аккаунты на паузе

    # ============================================================
    # ПУБЛИЧНЫЙ API — HTTP-роуты (app/routes/ws.py)
    # ============================================================

    def enable(self, idx: int) -> dict:
        """Включить слушатель для аккаунта idx.

        Ставит acc["ws_realtime"]=True. Если глобальный флаг
        CONFIG.use_websocket_realtime выключен — слушатель НЕ стартует
        (а уже работающий, если флаг выключили в рантайме, глушится) и
        возвращается status=disabled_global. Иначе стартует тред слушателя.
        """
        try:
            from app.instances import bot  # ленивый: избегаем циклического импорта
            states = bot.account_states
            if not (0 <= idx < len(states)):
                log_debug(f"ws_manager.enable: некорректный idx={idx!r}")
                return {"enabled": False, "status": "error"}
            acc = states[idx].acc
            acc["ws_realtime"] = True
            if not getattr(CONFIG, "use_websocket_realtime", False):
                # Глобальный флаг выключен: не стартуем; если что-то работало
                # (флаг выключили в рантайме) — глушим ради консистентности.
                self._teardown(idx, remember=False)
                with self._lock:
                    self._ensure_entry(idx).status = "disabled_global"
                return {"enabled": True, "status": "disabled_global"}
            self._start(idx, acc)
            with self._lock:
                status = self._ensure_entry(idx).status
            return {"enabled": True, "status": status}
        except Exception as e:
            log_debug(f"ws_manager.enable({idx}) error: {e}")
            return {"enabled": False, "status": "error"}

    def disable(self, idx: int) -> dict:
        """Выключить слушатель для аккаунта idx: флаг в False + остановка треда."""
        try:
            from app.instances import bot
            states = bot.account_states
            if 0 <= idx < len(states):
                states[idx].acc["ws_realtime"] = False
                self._teardown(idx, remember=False)
            return {"enabled": False, "status": "disabled"}
        except Exception as e:
            log_debug(f"ws_manager.disable({idx}) error: {e}")
            return {"enabled": False, "status": "disabled"}

    def status(self) -> dict:
        """Сводка для UI: глобальный флаг + per-account статусы слушателей.

        Формат: {"use_websocket_realtime": bool,
                 "accounts": {idx: {"enabled", "status", "events_total",
                                     "last_event_type", "last_event_at"}}}.
        Приостановленный паузой слушатель отдаётся как status="disabled".
        """
        global_flag = bool(getattr(CONFIG, "use_websocket_realtime", False))
        accounts: dict[int, dict] = {}
        try:
            from app.instances import bot
            with self._lock:
                for idx, state in enumerate(bot.account_states):
                    enabled = bool(state.acc.get("ws_realtime", False))
                    entry = self._entries.get(idx)
                    if entry is None:
                        st = "disabled_global" if (enabled and not global_flag) else "disabled"
                        accounts[idx] = {
                            "enabled": enabled, "status": st, "events_total": 0,
                            "last_event_type": None, "last_event_at": None,
                        }
                    else:
                        st = "disabled" if entry.suspended else entry.status
                        accounts[idx] = {
                            "enabled": enabled,
                            "status": st,
                            "events_total": entry.events_total,
                            "last_event_type": entry.last_event_type,
                            "last_event_at": entry.last_event_at,
                        }
        except Exception as e:
            log_debug(f"ws_manager.status error: {e}")
        return {"use_websocket_realtime": global_flag, "accounts": accounts}

    # ============================================================
    # ПУБЛИЧНЫЙ API — BotManager (app/manager.py)
    # ============================================================

    def auto_start_enabled(self) -> None:
        """Старт бота: запустить слушатели для всех acc с ws_realtime=True.

        Вызывается из BotManager.start только при CONFIG.use_websocket_realtime.
        Флаг ws_realtime хранится в самом acc dict, поэтому переживает
        перезапуск бота (accounts_data персистентен).
        """
        try:
            if not getattr(CONFIG, "use_websocket_realtime", False):
                return
            from app.instances import bot
            for idx, state in enumerate(list(bot.account_states)):
                try:
                    if state.acc.get("ws_realtime"):
                        self._start(idx, state.acc)
                except Exception as e:
                    log_debug(f"ws_manager.auto_start({idx}) error: {e}")
        except Exception as e:
            log_debug(f"ws_manager.auto_start_enabled error: {e}")

    def stop_all(self) -> None:
        """Полная остановка всех слушателей (вызывается из BotManager.stop)."""
        try:
            with self._lock:
                idxs = list(self._entries.keys())
            for idx in idxs:
                try:
                    self._teardown(idx, remember=False)
                except Exception as e:
                    log_debug(f"ws_manager.stop_all({idx}) error: {e}")
            with self._lock:
                self._entries.clear()
                # Per-account паузы сбрасываются: при следующем старте бота
                # AccountState пересоздаются с paused=False. Глобальный
                # _suspended НЕ сбрасываем — BotManager.paused тоже живёт
                # через restart, остаёмся с ним консистентны.
                self._acc_suspended.clear()
        except Exception as e:
            log_debug(f"ws_manager.stop_all error: {e}")

    def suspend(self) -> None:
        """Глобальная пауза: глушит АКТИВНЫЕ слушатели и запоминает какие были
        активны — resume() восстановит только их. Приостановленный слушатель
        в status() виден как disabled."""
        try:
            with self._lock:
                self._suspended = True
            for idx in self._running_idxs():
                try:
                    self._teardown(idx, remember=True)
                except Exception as e:
                    log_debug(f"ws_manager.suspend({idx}) error: {e}")
        except Exception as e:
            log_debug(f"ws_manager.suspend error: {e}")

    def resume(self) -> None:
        """Снять глобальную паузу: восстановить слушатели, активные до suspend()."""
        try:
            with self._lock:
                self._suspended = False
                candidates = [
                    idx for idx, e in self._entries.items()
                    if e.suspended and e.active_before_suspend
                ]
            for idx in candidates:
                self._resume_entry(idx)
        except Exception as e:
            log_debug(f"ws_manager.resume error: {e}")

    def suspend_account(self, idx: int) -> None:
        """Пауза одного аккаунта: глушит его слушатель (если активен) и
        запоминает, что он был активен."""
        try:
            with self._lock:
                self._acc_suspended.add(idx)
            self._teardown(idx, remember=True)
        except Exception as e:
            log_debug(f"ws_manager.suspend_account({idx}) error: {e}")

    def resume_account(self, idx: int) -> None:
        """Снять паузу аккаунта: восстановить его слушатель, если до паузы он
        был активен (и acc всё ещё включён)."""
        try:
            with self._lock:
                self._acc_suspended.discard(idx)
            self._resume_entry(idx)
        except Exception as e:
            log_debug(f"ws_manager.resume_account({idx}) error: {e}")

    # ============================================================
    # ВНУТРЕННЕЕ: запуск / остановка / пауза
    # ============================================================

    def _ensure_entry(self, idx: int) -> _Entry:
        """Взять (или создать) entry аккаунта. Вызывать ТОЛЬКО под self._lock."""
        entry = self._entries.get(idx)
        if entry is None:
            entry = _Entry(idx)
            self._entries[idx] = entry
        return entry

    def _running_idxs(self) -> list[int]:
        """Индексы аккаунтов, чьи треды слушателей живы прямо сейчас."""
        with self._lock:
            return [
                idx for idx, e in self._entries.items()
                if e.thread is not None and e.thread.is_alive()
            ]

    def _start(self, idx: int, acc: dict) -> None:
        """Запустить тред слушателя для аккаунта (идемпотентно).

        Если бот/аккаунт на паузе — тред НЕ стартует: запоминаем намерение
        (active_before_suspend) и слушатель поднимется в resume/resume_account.
        """
        with self._lock:
            entry = self._ensure_entry(idx)
            if entry.thread is not None and entry.thread.is_alive():
                return  # уже работает
            if self._suspended or idx in self._acc_suspended:
                entry.active_before_suspend = True
                entry.suspended = True
                entry.status = "disabled"
                return
            entry.stop_event = threading.Event()
            entry.suspended = False
            entry.active_before_suspend = False
            entry.status = "connecting"
            label = str(acc.get("short") or acc.get("name") or idx)
            thread = threading.Thread(
                target=self._run, args=(idx, acc, entry),
                daemon=True, name=f"ws-rt-{label}",
            )
            entry.thread = thread
        try:
            thread.start()
        except Exception as e:
            log_debug(f"ws_manager._start({idx}): thread start error: {e}")
            with self._lock:
                if entry.thread is thread:
                    entry.thread = None
                    entry.status = "error"

    def _teardown(self, idx: int, remember: bool) -> None:
        """Остановить слушателя idx (если жив) и отцепить ресурсы от entry.

        remember=True используется suspend/suspend_account: запоминаем что
        слушатель был активен (active_before_suspend) и ставим suspended —
        status() отдаёт его как disabled до resume.
        Долгая часть (close + join) выполняется ВНЕ self._lock.
        """
        with self._lock:
            entry = self._entries.get(idx)
            if entry is None:
                return
            was_running = entry.thread is not None and entry.thread.is_alive()
            entry.active_before_suspend = was_running if remember else False
            entry.suspended = remember
            thread, loop, client = entry.thread, entry.loop, entry.client
            stop_event = entry.stop_event
            entry.thread = None
            entry.loop = None
            entry.client = None
            entry.status = "disabled"
        try:
            stop_event.set()
        except Exception:
            pass
        if loop is not None and client is not None:
            try:
                future = asyncio.run_coroutine_threadsafe(client.close(), loop)
                try:
                    future.result(timeout=_CLOSE_TIMEOUT_SEC)
                except Exception as e:
                    log_debug(f"ws_manager._teardown({idx}): close() не выполнился: {e}")
            except Exception as e:
                log_debug(f"ws_manager._teardown({idx}): не удалось запланировать close(): {e}")
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=_JOIN_TIMEOUT_SEC)
            if thread.is_alive():
                log_debug(f"ws_manager._teardown({idx}): тред не завершился за {_JOIN_TIMEOUT_SEC}с (daemon, оставлен)")

    def _resume_entry(self, idx: int) -> None:
        """Поднять слушателя после паузы, если аккаунт всё ещё включён."""
        try:
            from app.instances import bot
            states = bot.account_states
            if not (0 <= idx < len(states)):
                return
            acc = states[idx].acc
            if not acc.get("ws_realtime"):
                return
            if not getattr(CONFIG, "use_websocket_realtime", False):
                with self._lock:
                    entry = self._entries.get(idx)
                    if entry is not None:
                        entry.status = "disabled_global"
                return
            self._start(idx, acc)
        except Exception as e:
            log_debug(f"ws_manager._resume_entry({idx}) error: {e}")

    # ============================================================
    # ВНУТРЕННЕЕ: тред слушателя
    # ============================================================

    def _own(self, entry: _Entry) -> bool:
        """Текущий тред всё ещё является тредом этого entry (не отцеплен
        _teardown'ом). Вызывать ТОЛЬКО под self._lock."""
        return entry.thread is threading.current_thread()

    def _run(self, idx: int, acc: dict, entry: _Entry) -> None:
        """Тред слушателя: свой event loop + сессия токен→клиент→run_forever."""
        label = str(acc.get("short") or acc.get("name") or idx)
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            with self._lock:
                if self._own(entry):
                    entry.loop = loop
            loop.run_until_complete(self._session(idx, acc, entry))
        except Exception as e:
            log_debug(f"ws_manager [{label}] тред упал: {type(e).__name__}: {e}")
            with self._lock:
                if self._own(entry):
                    entry.status = "error"
        finally:
            try:
                loop.close()
            except Exception:
                pass
            with self._lock:
                # Чистим только если это всё ещё НАШИ ссылки: entry мог быть
                # переиспользован новым тредом после _teardown.
                if entry.loop is loop:
                    entry.loop = None
                if self._own(entry):
                    entry.thread = None

    async def _session(self, idx: int, acc: dict, entry: _Entry) -> None:
        """Основной цикл сессии: obtain token → клиент → run_forever().

        Авто-реконнект внутри клиента (backoff 1..60с), поэтому здесь только
        получение/ротация токена и обработка фатальных выходов run_forever.
        """
        from app import oauth  # ленивый импорт

        label = str(acc.get("short") or acc.get("name") or idx)
        while not entry.stop_event.is_set():
            # 1) OAuth-токен. Синхронный HTTP допустим: loop у треда свой.
            token = ""
            try:
                token = oauth._obtain_oauth_token(acc) or ""
            except Exception as e:
                log_debug(f"ws_manager [{label}] obtain token error: {e}")
            if not token:
                with self._lock:
                    if self._own(entry):
                        entry.status = "no_token"
                log_debug(f"ws_manager [{label}] нет OAuth-токена, ретрай через {_NO_TOKEN_RETRY_SEC:.0f}с")
                if await self._wait_stop(entry, _NO_TOKEN_RETRY_SEC):
                    return
                continue

            # 2) Клиент. Импорт внутри треда: ws_client.py может быть ещё не
            # готов — тогда статус error и ретрай, модуль ws_manager работает.
            try:
                from app.ws_client import HHWebSocketClient
            except Exception as e:
                log_debug(f"ws_manager [{label}] импорт app.ws_client не удался: {e}")
                with self._lock:
                    if self._own(entry):
                        entry.status = "error"
                if await self._wait_stop(entry, _ERROR_RETRY_SEC):
                    return
                continue

            def _on_event(event):
                self._handle_event(idx, acc, entry, event)

            def _on_disconnect():
                self._handle_disconnect(entry)

            try:
                client = HHWebSocketClient(
                    token,
                    _on_event,
                    on_disconnect=_on_disconnect,
                    label=label,
                )
            except Exception as e:
                log_debug(f"ws_manager [{label}] создание клиента упало: {e}")
                with self._lock:
                    if self._own(entry):
                        entry.status = "error"
                if await self._wait_stop(entry, _ERROR_RETRY_SEC):
                    return
                continue

            with self._lock:
                if self._own(entry):
                    entry.client = client
                    entry.status = "connecting"
            try:
                await client.run_forever()
            except Exception as e:
                log_debug(f"ws_manager [{label}] run_forever error: {type(e).__name__}: {e}")
                with self._lock:
                    if self._own(entry):
                        entry.status = "error"
                if await self._wait_stop(entry, _ERROR_RETRY_SEC):
                    return
                continue
            finally:
                with self._lock:
                    if entry.client is client:
                        entry.client = None

            # run_forever выходит только по close() (т.е. нас остановили).
            if entry.stop_event.is_set():
                return
            # Неожиданный «чистый» выход без close: короткая пауза и повтор.
            log_debug(f"ws_manager [{label}] run_forever вышел без close — перезапуск")
            if await self._wait_stop(entry, 5.0):
                return

    async def _wait_stop(self, entry: _Entry, timeout: float) -> bool:
        """Ждать stop_event до timeout секунд, НЕ блокируя loop: polling с
        asyncio.sleep позволяет run_coroutine_threadsafe(client.close())
        выполниться пока мы ждём. True = дождались стопа."""
        elapsed = 0.0
        step = 0.5
        while not entry.stop_event.is_set():
            if elapsed >= timeout:
                return False
            await asyncio.sleep(step)
            elapsed += step
        return True

    # ============================================================
    # ВНУТРЕННЕЕ: колбэки клиента
    # ============================================================

    def _handle_event(self, idx: int, acc: dict, entry: _Entry, event) -> None:
        """Обёртка on_event клиента: статистика + передача события в бота.

        Вызывается из треда слушателя (из loop). Статистика и статус
        обновляются только пока тред не отцеплен _teardown'ом; передача в
        bot.on_realtime_event — в отдельном try/except, наружу ничего не
        кидаем (клиент не должен падать из-за обработчика).
        """
        try:
            with self._lock:
                if not self._own(entry):
                    return  # слушатель останавливается — событие уже не наше
                entry.events_total += 1
                entry.last_event_type = getattr(event, "type", "") or None
                entry.last_event_at = datetime.now().strftime("%H:%M:%S")
                # Событие дошло — соединение гарантированно живое.
                if entry.status in ("connecting", "reconnecting"):
                    entry.status = "connected"
        except Exception as e:
            log_debug(f"ws_manager [{idx}] stats error: {e}")
        try:
            from app.instances import bot  # ленивый: избегаем циклического импорта
            bot.on_realtime_event(acc, event)
        except Exception as e:
            log_debug(f"ws_manager [{idx}] on_realtime_event error: {e}")

    def _handle_disconnect(self, entry: _Entry) -> None:
        """Обёртка on_disconnect клиента: обрыв → reconnecting (клиент сам
        реконнектится своим backoff'ом)."""
        try:
            with self._lock:
                if not self._own(entry):
                    return
                if entry.status in ("connected", "connecting"):
                    entry.status = "reconnecting"
        except Exception as e:
            log_debug(f"ws_manager disconnect-callback error: {e}")


# Singleton: единственный экземпляр на процесс (как bot/manager в app.instances).
ws_manager = WsManager()
