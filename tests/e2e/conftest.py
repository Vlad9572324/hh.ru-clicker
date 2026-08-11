"""Playwright E2E-фикстуры для GUI-тестов HH-Clicker.

Архитектура (всё мокано, наружу не уходит ни одного запроса):

  session-scoped aiohttp-сервер в daemon-потоке (свой asyncio-loop), port 0:
    * GET /            -> static/index.html
    * GET /static/...  -> файлы из static/
    * GET /ws          -> WebSocket-эндпоинт БЕЗ auth
      (при подключении сразу шлёт {"type":"state_update", ...state},
       зарегистрированный фикстурой `ui` текущего теста)

  HTTP-запросы страницы к /api/* перехватываются через page.route("**/api/**")
  внутри фикстуры `ui` и мокируются из ui.state / ui.data / set_response().

Контракт фикстур (static_url, ws_server, ui) описан в tests/e2e/README.md.
"""

import asyncio
import copy
import json
import os
import re
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest
from aiohttp import WSMsgType, web
from pathlib import Path

# /tmp/mobile-refactor/static
STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
FAILURES_DIR = Path(__file__).resolve().parent / "failures"


# ============================================================
# Дефолтные пейлоады
# ============================================================

def default_state() -> dict:
    """Дефолтный снапшот состояния бота.

    Форма 1:1 повторяет реальный серверный snapshot:
    app/manager.py `get_state_snapshot()` (его шлёт broadcast_loop из
    app/routes/core.py:224 в WS как {"type":"state_update", ...}).
    Значения подобраны так, чтобы renderAll() в static/js/app.js
    (renderHeader/renderAccounts/...) отрабатывал без JS-ошибок.

    Примечание: ключи config повторяют блок "config" из get_state_snapshot();
    упоминавшиеся в ТЗ chat_deduplication/temp_skip* в текущем коде
    ОТСУТСТВУЮТ (проверено grep'ом) — поэтому не включены.
    """
    account = {
        # ── идентичность аккаунта: manager.py get_state_snapshot() ──
        "idx": 0,
        "name": "Иван Тестов (ivan@example.com)",  # renderAccounts: .acc-name
        "short": "ИВ",                              # лог/фильтры/события
        "color": "cyan",                            # CSS: .color-cyan|magenta|green|yellow
        # ── статус: ключи STATUS_MAP в app.js ──
        "status": "idle",
        "status_detail": "",
        # ── счётчики: updateCard() → acc-sent-/acc-tests-/... ──
        "sent": 7,
        "total_applied": 12,
        "tests": 1,
        "errors": 0,
        "already_applied": 3,
        "found_vacancies": 42,
        "current_vacancy_title": "",
        "current_vacancy_company": "",
        "current_vacancy_idx": 0,
        "total_vacancies": 0,
        "salary_skipped": 0,
        "questionnaire_sent": 0,
        "limit_exceeded": False,
        "paused": False,
        "paused_reason": "",
        "next_resume_touch": "",
        "resume_touch_status": "",
        "resume_touch_enabled": True,
        "letter": "Здравствуйте!\n\nИнтересна ваша вакансия.\n\nС уважением, Иван",
        "urls": [],
        "url_pages": {},
        # ── HH-статистика: renderHH / acc-hh- блок карточки ──
        "hh_interviews": 2,
        "hh_interviews_recent": 0,
        "hh_viewed": 5,
        "hh_discards": 0,
        "hh_not_viewed": 1,
        "hh_unread_by_employer": 0,
        "hh_stats_updated": "",
        "hh_stats_loading": False,
        "hh_interviews_list": [],
        "hh_possible_offers": [],
        "action_history": [],
        # ── статистика резюме: updateHeaderResumeStats / acc-rs- блок ──
        "resume_views_7d": 3,
        "resume_views_new": 1,
        "resume_shows_7d": 10,
        "resume_invitations_7d": 1,
        "resume_invitations_new": 0,
        "resume_next_touch_seconds": 0,
        "resume_free_touches": 2,
        "resume_global_invitations": 0,
        "resume_new_invitations_total": 0,
        "acc_event_log": [],
        "apply_tests": False,
        "consecutive_errors": 0,
        "url_stats": {},
        "cookies_expired": False,
        "degraded_mode": False,
        "degraded_skipped": 0,
        "degraded_fallback_enabled": True,
        "resume_status_oauth": {},
        "hh_today_applies": 7,
        "hh_today_applies_updated": "12:00",
        "hh_daily_limit": 200,
        # streak: updateCard() ~3492 "🔥 count/required"
        "responses_streak_count": 2,
        "responses_streak_required": 5,
        # форма из app/oauth.py get_oauth_status()
        "oauth_status": {"has_token": False, "expires_hours": 0, "has_refresh": False},
        "llm_enabled": False,
        "llm_status": "",
        "llm_replied_count": 0,
        "llm_pending_chats": 0,
        "use_oauth": False,
        "daily_sent": 7,
        "daily_limit": 0,          # CONFIG.daily_apply_limit по умолчанию 0 = без лимита
        "hard_stopped": False,
        "last_apply_at": None,
        "last_apply_attempt_at": None,
    }

    return {
        "type": "state_update",
        "uptime_seconds": 3661,  # fmtUptime -> "1ч 01м" (отличается от стартового "⏱ 00:00")
        "paused": False,
        "accounts": [account],
        "recent_responses": [],
        # лог: формат _add_log() из manager.py {time, acc, color, message, level};
        # activity_log — appendleft, т.е. в снапшоте новые записи ПЕРВЫМИ.
        "log": [
            {"time": "12:00:03", "acc": "ИВ", "color": "cyan",
             "message": "✅ Отклик отправлен: Python-разработчик @ Ромашка", "level": "success"},
            {"time": "12:00:02", "acc": "ИВ", "color": "cyan",
             "message": "⏭ Вакансия пропущена: зарплата ниже фильтра", "level": "warning"},
            {"time": "12:00:01", "acc": "", "color": "",
             "message": "⚙️ Конфигурация загружена", "level": "info"},
            {"time": "11:59:59", "acc": "ИВ", "color": "cyan",
             "message": "⚠️ Ошибка сети при сборе (retry)", "level": "error"},
        ],
        "llm_log": [],
        # ── config: 1:1 блок "config" из get_state_snapshot();
        #    дефолты значений из app/config.py class Config ──
        "config": {
            "pages_per_url": 40,
            "response_delay": 1,
            "pause_between_cycles": 60,
            "batch_responses": 3,
            "limit_check_interval": 30,
            "min_salary": 0,
            "auto_pause_errors": 5,
            "auto_apply_tests": False,
            "use_oauth_apply": False,
            "daily_apply_limit": 0,
            "stop_on_hh_limit": True,
            "llm_check_interval": 5,
            "allowed_schedules": [],
            "title_include_keywords": [],
            "title_exclude_keywords": [],
            "questionnaire_templates": [],
            "questionnaire_default_answer": "Готова рассказать подробнее на собеседовании.",
            "letter_templates": [
                {"name": "Стандартное",
                 "text": "Здравствуйте!\n\nЯ заинтересован в вашей вакансии.\n\nС уважением, [ИМЯ]"}
            ],
            "url_pool": [],
            "skip_inconsistent": False,
            "filter_agencies": False,
            "filter_low_competition": False,
            "search_period_days": 0,
            "llm_enabled": False,
            "llm_auto_send": False,
            "llm_fill_questionnaire": False,
            "llm_use_cover_letter": True,
            "llm_use_resume": True,
            "llm_use_quick_replies": True,
            "hh_ai_letter_first_try": True,
            "related_vacancies_enabled": True,
            "llm_model": "gpt-4o-mini",
            "llm_base_url": "https://api.openai.com/v1",
            "llm_status_summary": {},
            "llm_system_prompt": "Ты помощник соискателя работы. Отвечай вежливо и кратко.",
            "llm_api_key_set": False,
            "llm_api_key_fingerprint": "",
            "llm_profiles": [],
            "llm_profile_mode": "fallback",
        },
        # ── global_stats: renderHeader (#global-found/#global-sent/...) ──
        "global_stats": {
            "total_sent": 7,
            "total_tests": 1,
            "total_errors": 0,
            "total_found": 42,
            "storage_total": 15,
            "storage_tests": 2,
        },
        # ключ — short аккаунта (manager.py: _vacancy_queues[s.short])
        "vacancy_queues": {"ИВ": {"remaining": 0, "next": []}},
    }


def default_data() -> dict:
    """Дефолтные пейлоады ленивых GET-эндпоинтов (ui.data).

    Формы ответов — из обработчиков в static/js/app.js:
      /api/applied|tests|vacancies|interviews -> JSON-списки
      /api/hr_contacts -> {total, contacts[]}
      /api/proxy/info  -> {proxy, ip, impersonate} (proxyCheck, авто-вызов
                          через 800мс после DOMContentLoaded!)
      /api/account/<idx>/resume_views -> {stats{...}, history[]}
    """
    return {
        "applied": [],
        "tests": [],
        "vacancies": [],
        "interviews": [],
        "hr_contacts": {"total": 0, "contacts": []},
        "sessions": [],
        "resume_views": {},  # dict idx -> payload; отсутствующий idx -> {"stats": {}, "history": []}
        "proxy_info": {"proxy": "", "ip": "", "impersonate": ""},
        "llm_usage": {},
    }


# ============================================================
# Session-scoped сервер: static + WS
# ============================================================

class WsHub:
    """Объект управления WS-сервером (фикстура `ws_server`).

    Публичный контракт:
      send_state(state_dict)      -> отправить {"type":"state_update", **state_dict} всем активным соединениям
      close_all(code=1000, reason="") -> серверный разрыв активных соединений
      received: list[dict]        -> ВСЕ сообщения, полученные от страницы (sendCmd), за сессию
    """

    def __init__(self):
        self.loop = None            # asyncio-loop серверного потока
        self.base_url = None        # "http://127.0.0.1:<port>"
        self.received = []          # list[dict]
        self.connections = set()    # активные web.WebSocketResponse
        self._connect_state = None
        self._state_lock = threading.Lock()

    # ── вызывается из потока тестов ──

    def set_connect_state(self, state):
        """state, отправляемый каждому НОВОМУ WS-подключению."""
        with self._state_lock:
            self._connect_state = state

    def get_connect_state(self):
        with self._state_lock:
            return copy.deepcopy(self._connect_state) if self._connect_state is not None else None

    def send_state(self, state_dict):
        payload = {"type": "state_update", **state_dict}
        self._run_sync(self._broadcast(payload))

    def close_all(self, code=1000, reason=""):
        self._run_sync(self._close_all(code, reason))

    def _run_sync(self, coro):
        if self.loop is None:
            raise RuntimeError("WS-сервер ещё не запущен")
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=10)

    async def _broadcast(self, payload):
        text = json.dumps(payload, ensure_ascii=False)
        for ws in list(self.connections):
            try:
                await ws.send_str(text)
            except Exception:
                self.connections.discard(ws)

    async def _close_all(self, code, reason):
        conns = list(self.connections)
        self.connections.clear()
        for ws in conns:
            try:
                await ws.close(code=code, message=reason.encode("utf-8"))
            except Exception:
                pass

    # ── вызывается из серверного потока ──

    def register(self, ws):
        self.connections.add(ws)

    def unregister(self, ws):
        self.connections.discard(ws)

    def record(self, msg):
        self.received.append(msg)


class _TestServer:
    """Один сервер на сессию: статика + WS в daemon-потоке со своим loop'ом."""

    def __init__(self, hub):
        self.hub = hub
        self._thread = None
        self._runner = None
        self._ready = threading.Event()
        self._error = None

    def start(self, timeout=15.0):
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="e2e-static-ws-server", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("E2E-сервер не поднялся за отведённое время")
        if self._error is not None:
            raise RuntimeError(f"E2E-сервер упал при старте: {self._error!r}")

    def _build_app(self):
        hub = self.hub
        static_root = STATIC_DIR.resolve()

        async def index_handler(request):
            return web.FileResponse(static_root / "index.html")

        async def static_handler(request):
            rel = request.match_info["path"]
            target = (static_root / rel).resolve()
            if str(target) != str(static_root) and not str(target).startswith(str(static_root) + os.sep):
                raise web.HTTPNotFound()
            if not target.is_file():
                raise web.HTTPNotFound()
            return web.FileResponse(target)

        async def ws_handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            hub.register(ws)
            try:
                snap = hub.get_connect_state()
                if snap is not None:
                    await ws.send_str(json.dumps({"type": "state_update", **snap},
                                                 ensure_ascii=False))
                async for msg in ws:
                    if msg.type == WSMsgType.TEXT:
                        try:
                            data = json.loads(msg.data)
                        except (ValueError, TypeError):
                            data = {"raw": msg.data}
                        hub.record(data)
                    elif msg.type == WSMsgType.BINARY:
                        hub.record({"raw_binary_len": len(msg.data)})
                    elif msg.type == WSMsgType.ERROR:
                        break
            finally:
                hub.unregister(ws)
            return ws

        app = web.Application()
        app.router.add_get("/", index_handler)
        app.router.add_get("/static/{path:.*}", static_handler)
        app.router.add_get("/ws", ws_handler)
        return app

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.hub.loop = loop
        # bind на port 0 — реальный порт берём из socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            self.hub.base_url = f"http://127.0.0.1:{port}"
            self._runner = web.AppRunner(self._build_app())
            loop.run_until_complete(self._runner.setup())
            site = web.SockSite(self._runner, sock)
            loop.run_until_complete(site.start())
        except Exception as e:  # noqa: BLE001 — сообщаем в фикстуру и выходим
            self._error = e
            self._ready.set()
            loop.close()
            return
        self._ready.set()
        loop.run_forever()
        # cleanup после loop.stop() (см. stop())
        loop.run_until_complete(self._runner.cleanup())
        loop.close()

    def stop(self):
        loop = self.hub.loop
        if loop is not None and loop.is_running():
            async def _shutdown():
                for ws in list(self.hub.connections):
                    try:
                        await ws.close(code=1001, message=b"server shutdown")
                    except Exception:
                        pass
            try:
                asyncio.run_coroutine_threadsafe(_shutdown(), loop).result(timeout=5)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)


_SERVER_SINGLETON = None
_SERVER_LOCK = threading.Lock()


def _get_server():
    global _SERVER_SINGLETON
    with _SERVER_LOCK:
        if _SERVER_SINGLETON is None:
            hub = WsHub()
            srv = _TestServer(hub)
            srv.start()
            _SERVER_SINGLETON = srv
        return _SERVER_SINGLETON


@pytest.fixture(scope="session")
def ws_server():
    """Session-scoped объект управления мок-WS-сервером (см. WsHub)."""
    srv = _get_server()
    yield srv.hub
    srv.stop()


@pytest.fixture(scope="session")
def static_url(ws_server):
    """Session-scoped базовый URL локального сервера: "http://127.0.0.1:<port>"."""
    return ws_server.base_url


# ============================================================
# Function-scoped фикстура `ui`
# ============================================================

_NOT_MOCKED = object()

# GET-пути -> ключи ui.data (формы ответов см. default_data)
_DATA_GET_ROUTES = {
    "/api/applied": "applied",
    "/api/tests": "tests",
    "/api/vacancies": "vacancies",
    "/api/interviews": "interviews",
    "/api/hr_contacts": "hr_contacts",
    "/api/sessions": "sessions",
    "/api/proxy/info": "proxy_info",
    "/api/llm_usage": "llm_usage",
}


class UIController:
    """Главный объект E2E-теста. Полный контракт — в tests/e2e/README.md."""

    def __init__(self, page, base_url, hub):
        self.page = page
        self.base_url = base_url
        self.state = default_state()   # мутируется ДО ui.open()
        self.data = default_data()     # мутируется ДО ui.open() или между вызовами
        self.calls = []                # перехваченные HTTP /api/* запросы
        self.page_errors = []          # window-уровневые JS-ошибки (pageerror)
        self._hub = hub
        self._overrides = []           # set_response(): [{method, pattern, body, status}]
        self._opened = False
        self._route_installed = False
        self._cmd_offset = len(hub.received)

    # ── свойства ──

    @property
    def commands(self):
        """WS-сообщения от страницы (sendCmd) за ТЕКУЩИЙ тест."""
        return self._hub.received[self._cmd_offset:]

    # ── основные действия ──

    def open(self):
        """goto + ожидание WS-подключения и полного первичного рендера. Идемпотентна."""
        if self._opened:
            return
        # WS-сервер шлёт этот state каждому новому подключению
        self._hub.set_connect_state(copy.deepcopy(self.state))
        if not self._route_installed:
            self.page.route("**/api/**", self._route_handler)
            self._route_installed = True
        self.page.on("pageerror", lambda err: self.page_errors.append(str(err)))
        self.page.goto(self.base_url + "/", wait_until="load")
        # ws.onopen -> #conn-dot получает класс "connected"
        self.page.wait_for_selector("#conn-dot.connected", timeout=15000)
        # первичный renderAll: #apply-mode-badge пуст в HTML и заполняется
        # только renderHeader(); #global-sent сверяем со снапшотом.
        expected_sent = str(self.state.get("global_stats", {}).get("total_sent", 0))
        self.page.wait_for_function(
            """(expectedSent) => {
                const badge = document.getElementById('apply-mode-badge');
                const sent = document.getElementById('global-sent');
                return !!badge && badge.textContent.length > 0 &&
                       !!sent && sent.textContent.trim() === expectedSent;
            }""",
            arg=expected_sent,
            timeout=15000,
        )
        # Реальный бот шлёт broadcast каждые 0.3с (broadcast_loop в
        # app/routes/core.py). Значения в карточках аккаунтов появляются
        # только со ВТОРОГО snapshot: renderAccounts() при первом рендере
        # лишь создаёт шаблон карточки (buildCardHTML), а updateCard()
        # вызывается начиная со второго. Повторяем state для полноты рендера.
        self.push_state()
        accounts = self.state.get("accounts") or []
        if accounts:
            self.page.wait_for_function(
                """(args) => {
                    const el = document.getElementById('acc-sent-' + args.idx);
                    return !!el && el.textContent.trim() === args.sent;
                }""",
                arg={"idx": accounts[0].get("idx", 0),
                     "sent": str(accounts[0].get("sent", 0))},
                timeout=15000,
            )
        self._opened = True

    def push_state(self):
        """Отправить текущий ui.state через WS (имитация broadcast от бота)."""
        self._hub.send_state(copy.deepcopy(self.state))

    def close_ws(self, code=1000, reason=""):
        """Серверный разрыв WS (для reconnect-тестов)."""
        self._hub.close_all(code=code, reason=reason)

    def set_response(self, method, path_regex, body=None, status=200):
        """Override HTTP-ответа: method+path_regex(search) -> JSON(body), status."""
        self._overrides.append({
            "method": method.upper(),
            "pattern": re.compile(path_regex),
            "body": body,
            "status": int(status),
        })

    def wait_until(self, predicate, timeout=5.0, interval=0.05,
                   message="условие не выполнено за отведённое время"):
        """Поллинг предиката (Python-side) — для ожидания асинхронных эффектов."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            self.page.wait_for_timeout(interval * 1000)
        if not predicate():
            raise AssertionError(message)

    # ── внутренний роутинг page.route("**/api/**") ──

    def _route_handler(self, route):
        request = route.request
        url_path = urlsplit(request.url).path
        method = request.method.upper()
        payload_json = None
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            try:
                payload_json = request.post_data_json
            except Exception:
                payload_json = request.post_data
        self.calls.append({"method": method, "path": url_path,
                           "url": request.url, "json": payload_json})

        # overrides имеют приоритет
        for ov in self._overrides:
            if ov["method"] in (method, "*") and ov["pattern"].search(url_path):
                route.fulfill(
                    status=ov["status"],
                    content_type="application/json",
                    body=json.dumps(ov["body"], ensure_ascii=False),
                )
                return

        if method == "GET":
            payload = self._mocked_get(url_path)
            if payload is _NOT_MOCKED:
                route.fulfill(status=404, content_type="application/json",
                              body=json.dumps({"error": "not mocked"}, ensure_ascii=False))
            else:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(payload, ensure_ascii=False))
            return

        # любой POST/PUT/PATCH/DELETE без override
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"ok": True}, ensure_ascii=False))

    def _mocked_get(self, url_path):
        if url_path == "/api/raw/config":
            return self.state.get("config", {})
        if url_path == "/api/raw/accounts":
            return self.state["accounts"] if "accounts" in self.state else self.state
        if url_path in _DATA_GET_ROUTES:
            return self.data[_DATA_GET_ROUTES[url_path]]
        m = re.fullmatch(r"/api/account/(\d+)/resume_views", url_path)
        if m:
            idx = int(m.group(1))
            return self.data["resume_views"].get(idx, {"stats": {}, "history": []})
        return _NOT_MOCKED


@pytest.fixture
def page(browser):
    """Изолированная Playwright-страница для каждого e2e-теста.

    Не полагаемся на fixture ``page`` из pytest-playwright: в минимальном
    окружении проекта доступна только browser fixture. Отдельный context
    также не даёт cookies, localStorage и route-мокам протекать между тестами.
    """
    context = browser.new_context()
    page_obj = context.new_page()
    try:
        yield page_obj
    finally:
        context.close()


@pytest.fixture
def ui(page, static_url, ws_server):
    """Function-scoped контроллер UI: page + моки state/data/commands/calls."""
    yield UIController(page, static_url, ws_server)


# ============================================================
# Screenshot на fail
# ============================================================

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


@pytest.fixture(autouse=True)
def _screenshot_on_failure(request, page):
    yield
    rep = getattr(request.node, "rep_call", None)
    if rep is not None and rep.failed:
        try:
            FAILURES_DIR.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r"[^\w\-.]+", "_", request.node.name)
            page.screenshot(path=str(FAILURES_DIR / f"{safe_name}.png"))
        except Exception:
            pass


# ============================================================
# Ранний teardown Playwright после ПОСЛЕДНЕГО e2e-теста
# ============================================================
# Синхронный API Playwright крутит свой asyncio-loop в гринлете ОСНОВНОГО
# потока и после каждого sync-вызова делает asyncio._set_running_loop(loop)
# (playwright/_impl/_sync_base.py, SyncBase._sync / EventInfo.value).
# Session-фикстуры pytest-playwright (`browser`, `playwright`) по умолчанию
# живут до конца сессии, поэтому после e2e-тестов в основном потоке остаётся
# «running» loop и asyncio.run() в юнит-тестах падает с
# RuntimeError("asyncio.run() cannot be called from a running event loop").
#
# Решение: browser и playwright останавливаются сразу после последнего
# e2e-теста (обёртка pytest_runtest_protocol ниже). Переопределённые
# session-фикстуры делают teardown идемпотентным, чтобы родные финализаторы
# pytest-playwright на конце сессии не падали на уже остановленных объектах
# (browser.close() на закрытом loop кидает Error).

_PW_STATE = {"playwright": None, "browser": None, "stopped": False}


def _pw_shutdown():
    """Идемпотентно закрыть browser и остановить Playwright (синхронный API).

    pw.stop() внутри playwright идемпотентен сам по себе (_exit_was_called),
    но browser.close() не идемпотентен — состояние tracked здесь.
    """
    if _PW_STATE["stopped"]:
        return
    _PW_STATE["stopped"] = True
    browser = _PW_STATE["browser"]
    playwright_obj = _PW_STATE["playwright"]
    if browser is not None:
        try:
            browser.close()
        except Exception:
            pass
    if playwright_obj is not None:
        try:
            playwright_obj.stop()
        except Exception:
            pass
    _PW_STATE["browser"] = None
    _PW_STATE["playwright"] = None
    # Страховка: после stop в основном потоке не должно остаться «running»
    # loop (run_until_complete в dispatcher-гринлете сбрасывает его сам,
    # т.к. состояние thread-local общее для гринлетов одного потока).
    if asyncio.events._get_running_loop() is not None:
        asyncio._set_running_loop(None)


@pytest.fixture(scope="session")
def playwright():
    """Override фикстуры pytest-playwright (для тестов tests/e2e/).

    Ссылка сохраняется в _PW_STATE для раннего останова в _pw_shutdown();
    финализатор идемпотентен (реальный stop происходит после последнего
    e2e-теста, повторный вызов на конце сессии — no-op).
    """
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    _PW_STATE["playwright"] = pw
    yield pw
    _pw_shutdown()


@pytest.fixture(scope="session")
def browser(playwright):
    """Запустить Chromium без зависимости от pytest-playwright fixtures.

    В проектном venv установлена библиотека ``playwright``, но plugin может
    отсутствовать. Поэтому ``launch_browser``/``page`` от внешнего plugin не
    используются: весь жизненный цикл браузера контролирует этот conftest.
    """
    _PW_STATE["browser"] = playwright.chromium.launch(headless=True)
    yield _PW_STATE["browser"]
    _pw_shutdown()


_E2E_ROOT = Path(__file__).resolve().parent
_PENDING_E2E = None  # set[str]: nodeid ещё не выполненных e2e-тестов


def _is_e2e_item(item) -> bool:
    path_attr = getattr(item, "path", None)
    if path_attr is None:  # pragma: no cover — старый pytest
        path_attr = getattr(item, "fspath", None)
    if path_attr is None:
        return False
    try:
        Path(str(path_attr)).resolve().relative_to(_E2E_ROOT)
        return True
    except ValueError:
        return False


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    """После ПОСЛЕДНЕГО e2e-теста сразу остановить Playwright (см. блок выше).

    Хуки conftest-а действуют на всю сессию после загрузки conftest-а,
    поэтому переход e2e -> юнит-тесты виден здесь независимо от порядка.
    """
    global _PENDING_E2E
    if _PENDING_E2E is None:
        _PENDING_E2E = {
            i.nodeid for i in item.session.items if _is_e2e_item(i)
        }
    result = yield
    if item.nodeid in _PENDING_E2E:
        _PENDING_E2E.discard(item.nodeid)
        if not _PENDING_E2E and _PW_STATE["playwright"] is not None:
            _pw_shutdown()
    return result

