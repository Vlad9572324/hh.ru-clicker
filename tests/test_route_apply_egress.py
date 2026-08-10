"""Split-egress: wiring HH_PROXY в aiohttp-запросы routes/apply.py.

Все HTTP-запросы к HH обязаны идти через HH_PROXY (audit HIGH #5). В
app/routes/apply.py для этого каждый aiohttp-блок раскладывает прокси через
`_aio_egress_kwargs()` (реэкспорт из app.hh_http через app.hh_apply):
- http(s)-прокси → `proxy=...` на КАЖДЫЙ session.get/post-вызов;
- socks-прокси → ProxyConnector в конструктор ClientSession (здесь не
  проверяется: aiohttp_socks не установлен в тестовом окружении);
- без прокси → ни proxy=, ни connector (прямой egress — легитимно только
  когда HH_PROXY пуст).

Тесты функциональные: `app.routes.apply.aiohttp` подменяется рекордером
(async context manager), который запоминает kwargs конструктора ClientSession
и kwargs каждого запроса + раздаёт заготовленные ответы. Реальных сетевых
вызовов нет; bot-хелперы, add_applied и get_client — шпионы/стабы
(паттерны из tests/test_route_apply_phase3.py).

Покрываемые блоки файла:
1. _fetch_questionnaire_data (GET формы опросника) — через test-required
   ветку /api/apply/check;
2. /api/apply/check (POST /applicant/vacancy_response/popup);
3. /api/apply/submit web-flow (GET формы + POST формы).

pytest-asyncio в проекте нет — async handler'ы гоняются через asyncio.run
(хелпер _run устойчив к занятому потоку — паттерн phase3-тестов).
"""

import asyncio
import threading
import types

import pytest

import app.routes.apply as apply_route
from app import hh_http
from app.instances import bot
from app.routes.apply import api_apply_check, api_apply_submit

PROXY_URL = "http://proxy.test:3128"


def _run(coro):
    """Исполнить корутину через asyncio.run, устойчиво к занятому потоку."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict = {}

    def _target():
        try:
            box["result"] = asyncio.run(coro)
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


# ── Стабы транспорта ──────────────────────────────────────────────────────────


class _StubResponse:
    """Ответ aiohttp-запроса: async context manager + .text()."""

    def __init__(self, status=200, text="", headers=None):
        self.status = status
        self._text = text
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def text(self):
        return self._text


class _FormData:
    def __init__(self):
        self.fields = []

    def add_field(self, name, value):
        self.fields.append((name, value))


class _SessionRecorder:
    """Стаб ClientSession: пишет ctor-kwargs и kwargs запросов в рекордер,
    раздаёт заготовленные ответы по порядку."""

    def __init__(self, recorder, *args, **kwargs):
        self._recorder = recorder
        recorder.sessions.append({"ctor_kwargs": kwargs})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _request(self, method, url, **kwargs):
        self._recorder.requests.append({"method": method, "url": url, **kwargs})
        if not self._recorder.responses:
            raise AssertionError(
                f"неожиданный запрос {method} {url} — список ответов исчерпан")
        return self._recorder.responses.pop(0)

    def get(self, url, **kwargs):
        return self._request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._request("POST", url, **kwargs)


class _AioRecorder:
    """Замена модуля aiohttp внутри app.routes.apply (ClientSession +
    ClientTimeout + FormData — только они там используются)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.sessions: list = []
        self.requests: list = []

    def ClientSession(self, *args, **kwargs):
        return _SessionRecorder(self, *args, **kwargs)

    def ClientTimeout(self, **kwargs):
        return kwargs

    def FormData(self):
        return _FormData()


# ── Фикстуры ──────────────────────────────────────────────────────────────────


@pytest.fixture
def aio_recorder(monkeypatch):
    """Инсталлятор рекордера вместо apply_route.aiohttp."""

    def _install(responses):
        rec = _AioRecorder(responses)
        monkeypatch.setattr(apply_route, "aiohttp", rec)
        return rec

    return _install


@pytest.fixture
def egress_proxy():
    """Выставляет HH_PROXY=http-прокси через set_proxy(); восстанавливает."""
    old = hh_http.proxy_url()
    hh_http.set_proxy(PROXY_URL)
    yield PROXY_URL
    hh_http.set_proxy(old or "")


@pytest.fixture
def no_egress_proxy():
    """Гарантирует пустой HH_PROXY (прямой egress); восстанавливает."""
    old = hh_http.proxy_url()
    hh_http.set_proxy("")
    yield
    hh_http.set_proxy(old or "")


ACC = {
    "name": "acc1",
    "cookies": {"_xsrf": "x"},
    "resume_hash": "rh1",
    "letter": "cover letter",
    "mode": "web",
}


@pytest.fixture
def bot_stub(monkeypatch):
    """Подменяет bot-хелперы и add_applied шпионами (без диска и сети)."""
    acc = dict(ACC)
    state = types.SimpleNamespace(sent=0, questionnaire_sent=0, short="a1", color="green")
    logs: list = []
    applied: list = []
    monkeypatch.setattr(bot, "_get_apply_acc", lambda idx: dict(acc))
    monkeypatch.setattr(bot, "_get_apply_state", lambda idx: state)
    monkeypatch.setattr(
        bot, "_add_log",
        lambda short, color, msg, level="info", neg_id="": logs.append((short, color, msg, level)),
    )
    monkeypatch.setattr(apply_route, "add_applied",
                        lambda name, vid, info=None: applied.append((name, vid)))
    return {"acc": acc, "state": state, "logs": logs, "applied": applied}


class _FakeWebClient:
    """Клиент без FallbackHHClient-признака → api_apply_submit идёт web-flow."""


@pytest.fixture
def web_mode(monkeypatch):
    """get_client возвращает не-FallbackHHClient → старый web-form flow."""
    monkeypatch.setattr(apply_route, "get_client", lambda acc: _FakeWebClient())


#popup-ответ с shortVacancy: статус 200 → роут вернёт "sent" (уже отправлен)
_POPUP_SENT = _StubResponse(
    200,
    '{"responseStatus": {"shortVacancy": {"name": "Dev", "company": {"name": "Co"}}}}',
)
# popup со ссылкой на опрос: НЕ 200 (200 → ветка "sent") и не 401/403 (auth)
_POPUP_TEST_REQUIRED = _StubResponse(400, '<div class="test-required">пройдите опрос</div>')
# HTML формы опросника: без вопросов, не login-страница
_FORM_HTML = _StubResponse(200, '<html><form><input type="hidden" name="_xsrf" value="tok1"></form></html>')
# 302 на переговоры → успешный submit
_SUBMIT_REDIRECT = _StubResponse(302, "", headers={"location": "/applicant/negotiations"})


# ── 1. /api/apply/check: POST popup уходит через http-прокси ─────────────────


def test_check_post_uses_http_proxy(aio_recorder, egress_proxy, bot_stub):
    rec = aio_recorder([_POPUP_SENT])

    resp = _run(api_apply_check({"account_idx": 0, "vacancy_id": "777"}))

    assert resp["status"] == "sent"  # детерминированно дошли до ответа
    assert len(rec.requests) == 1
    call = rec.requests[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/applicant/vacancy_response/popup")
    # http-ветка: прокси на каждый запрос, НЕ connector на сессию
    assert call["proxy"] == PROXY_URL
    assert len(rec.sessions) == 1
    assert "connector" not in rec.sessions[0]["ctor_kwargs"]


def test_check_questionnaire_get_uses_http_proxy(aio_recorder, egress_proxy, bot_stub):
    """test-required ветка: и POST popup, и GET формы опросника
    (_fetch_questionnaire_data) обязаны нести proxy=."""
    rec = aio_recorder([_POPUP_TEST_REQUIRED, _FORM_HTML])

    resp = _run(api_apply_check({"account_idx": 0, "vacancy_id": "777"}))

    assert resp["status"] == "test_required"
    assert [r["method"] for r in rec.requests] == ["POST", "GET"]
    assert "/applicant/vacancy_response?vacancyId=777" in rec.requests[1]["url"]
    for call in rec.requests:
        assert call.get("proxy") == PROXY_URL, \
            f"{call['method']} {call['url']} ушёл без HH_PROXY"


# ── 2. /api/apply/submit web-flow: GET формы + POST формы через прокси ───────


def test_submit_web_flow_both_requests_use_http_proxy(aio_recorder, egress_proxy,
                                                      bot_stub, web_mode):
    rec = aio_recorder([_FORM_HTML, _SUBMIT_REDIRECT])

    resp = _run(api_apply_submit({"account_idx": 0, "vacancy_id": "777"}))

    assert resp["status"] == "sent"
    assert [r["method"] for r in rec.requests] == ["GET", "POST"]
    for call in rec.requests:
        assert "/applicant/vacancy_response" in call["url"]
        assert call.get("proxy") == PROXY_URL, \
            f"{call['method']} ушёл без HH_PROXY"
    # обе сессии созданы без connector (http-ветка)
    for sess in rec.sessions:
        assert "connector" not in sess["ctor_kwargs"]
    assert bot_stub["applied"] == [("acc1", "777")]


# ── 3. Без прокси: ни proxy=, ни connector ───────────────────────────────────


def test_check_without_proxy_has_no_proxy_kwargs(aio_recorder, no_egress_proxy, bot_stub):
    rec = aio_recorder([_POPUP_SENT])

    resp = _run(api_apply_check({"account_idx": 0, "vacancy_id": "777"}))

    assert resp["status"] == "sent"
    assert len(rec.requests) == 1
    assert "proxy" not in rec.requests[0], \
        "без HH_PROXY запрос не должен получать proxy="
    assert "connector" not in rec.sessions[0]["ctor_kwargs"], \
        "без HH_PROXY сессия не должна получать connector"


def test_submit_without_proxy_has_no_proxy_kwargs(aio_recorder, no_egress_proxy,
                                                  bot_stub, web_mode):
    rec = aio_recorder([_FORM_HTML, _SUBMIT_REDIRECT])

    resp = _run(api_apply_submit({"account_idx": 0, "vacancy_id": "777"}))

    assert resp["status"] == "sent"
    assert len(rec.requests) == 2
    for call in rec.requests:
        assert "proxy" not in call
    for sess in rec.sessions:
        assert "connector" not in sess["ctor_kwargs"]
