"""Функциональные тесты egress-wiring'а aiohttp-путей app/hh_apply.py.

Security fix split-egress: ВСЕ HTTP-запросы к HH.ru обязаны идти через
HH_PROXY. Обе aiohttp.ClientSession в hh_apply.py (send_response_async и
fill_and_submit_questionnaire) берут (sess_kw, req_kw) из
hh_http._aio_egress_kwargs(); проверяем что kwargs реально доезжают:

- http(s)-прокси  → sess_kw пустые, каждый session.get/post получает proxy=...;
- прокси нет      → ни в конструкторе сессии, ни в запросах нет proxy/connector.

(socks-ветка с ProxyConnector здесь не гоняется: aiohttp_socks не установлен
в тестовом окружении; её fail-closed поведение покрыто отдельно.)

pytest-asyncio нет — корутины запускаем через asyncio.run() в отдельном
потоке (pytest-playwright держит session-scoped loop «running» в главном
потоке, прямой asyncio.run() в main-thread падает с RuntimeError).
"""
import asyncio
import concurrent.futures

import pytest

import app.hh_apply as hh_apply
from app import hh_http

PROXY_URL = "http://proxy.test:3128"


def _run_coro(coro):
    """Запуск корутины через asyncio.run() в отдельном потоке — см. докстринг
    модуля. Исключения корутины пробрасываются через future.result()."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


# ── fixtures: прокси в hh_http singleton ─────────────────────────────────────

@pytest.fixture
def hh_proxy():
    """Выставить http-прокси runtime, вернуть как было (включая пустой)."""
    old = hh_http.proxy_url()
    hh_http.set_proxy(PROXY_URL)
    yield PROXY_URL
    hh_http.set_proxy(old)


@pytest.fixture
def hh_no_proxy():
    """Гарантированно прямой egress (HH_PROXY мог прийти из env)."""
    old = hh_http.proxy_url()
    hh_http.set_proxy("")
    yield
    hh_http.set_proxy(old)


# ── recorder-замена aiohttp.ClientSession ────────────────────────────────────

class _RecResp:
    """Стаб aiohttp-ответа: .status, .headers, async .text()."""

    def __init__(self, status=200, text=""):
        self.status = status
        self._text = text
        self.headers = {}

    async def text(self):
        return self._text


class _RecCallCtx:
    """async with session.get/post(...) as r: — отдаёт записанный стаб."""

    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *a):
        return False


class _RecordingSession:
    """Подмена ClientSession: запоминает kwargs конструктора и каждого
    get/post-вызова. Ответы — стабы из recorder'а."""

    def __init__(self, recorder, *args, **kwargs):
        self._recorder = recorder
        recorder.ctor_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def get(self, url, **kw):
        self._recorder.calls.append(("GET", url, kw))
        return _RecCallCtx(self._recorder.get_resp)

    def post(self, url, **kw):
        self._recorder.calls.append(("POST", url, kw))
        return _RecCallCtx(self._recorder.post_resp)


class _SessionRecorder:
    def __init__(self, *, get_resp=None, post_resp=None):
        self.ctor_kwargs = None
        self.calls = []  # list of (method, url, kwargs)
        self.get_resp = get_resp or _RecResp()
        self.post_resp = post_resp or _RecResp()


def _install_recorder(monkeypatch, **resp_kw):
    """Подменить aiohttp.ClientSession на recorder в модуле app.hh_apply."""
    rec = _SessionRecorder(**resp_kw)

    def _factory(*args, **kwargs):
        return _RecordingSession(rec, *args, **kwargs)

    monkeypatch.setattr(hh_apply.aiohttp, "ClientSession", _factory)
    return rec


def _make_acc():
    return {
        "name": "t",
        "cookies": {"_xsrf": "x", "hhtoken": "t"},
        "resume_hash": "rh",
        "letter": "hi",
    }


@pytest.fixture
def no_ai_letter(monkeypatch):
    """Заглушить generate_hh_ai_letter чтобы не ходить в реальный HH API."""
    async def _stub(*args, **kwargs):
        return ""
    monkeypatch.setattr(hh_apply, "generate_hh_ai_letter", _stub)


# ── send_response_async ──────────────────────────────────────────────────────

def test_send_response_async_http_proxy_in_request_kwargs(hh_proxy, no_ai_letter, monkeypatch):
    """http-прокси: sess_kw пустые, POST получает proxy=HH_PROXY."""
    rec = _install_recorder(
        monkeypatch,
        post_resp=_RecResp(200, '{"success":true,"topic_id":"1"}'),
    )

    result, info = _run_coro(hh_apply.send_response_async(_make_acc(), "123"))

    assert result == "sent" and info.get("topic_id") == "1"
    # конструктор сессии: без proxy/connector (http-ветка решает proxy= на запрос)
    assert "connector" not in rec.ctor_kwargs
    assert "proxy" not in rec.ctor_kwargs
    # единственный запрос — POST popup, и в нём прокси
    assert len(rec.calls) == 1
    method, url, kw = rec.calls[0]
    assert method == "POST"
    assert url.endswith("/applicant/vacancy_response/popup")
    assert kw.get("proxy") == PROXY_URL


def test_send_response_async_no_proxy_direct(hh_no_proxy, no_ai_letter, monkeypatch):
    """Без прокси: ни в конструкторе сессии, ни в запросе нет proxy/connector."""
    rec = _install_recorder(
        monkeypatch,
        post_resp=_RecResp(200, '{"success":true,"topic_id":"1"}'),
    )

    result, _info = _run_coro(hh_apply.send_response_async(_make_acc(), "123"))

    assert result == "sent"
    assert "connector" not in rec.ctor_kwargs
    assert "proxy" not in rec.ctor_kwargs
    assert len(rec.calls) == 1
    _method, _url, kw = rec.calls[0]
    assert "proxy" not in kw
    assert "connector" not in kw


# ── fill_and_submit_questionnaire ────────────────────────────────────────────

def test_questionnaire_form_get_passes_proxy(hh_proxy, monkeypatch):
    """GET формы опроса получает proxy=HH_PROXY. Ответ 403 → ("auth_error", {})
    до всякого POST — простой детерминированный срез через egress-ветку."""
    rec = _install_recorder(monkeypatch, get_resp=_RecResp(403, ""))

    result, info = _run_coro(
        hh_apply.fill_and_submit_questionnaire(_make_acc(), "777", "Dev", "Comp")
    )

    assert (result, info) == ("auth_error", {})
    assert "connector" not in rec.ctor_kwargs
    assert "proxy" not in rec.ctor_kwargs
    # один GET формы; POST не успевает случиться (early-return на 403)
    assert len(rec.calls) == 1
    method, url, kw = rec.calls[0]
    assert method == "GET"
    assert "/applicant/vacancy_response?vacancyId=777" in url
    assert kw.get("proxy") == PROXY_URL


def test_questionnaire_no_proxy_direct(hh_no_proxy, monkeypatch):
    """Без прокси GET формы идёт напрямую: нигде нет proxy/connector."""
    rec = _install_recorder(monkeypatch, get_resp=_RecResp(403, ""))

    result, _info = _run_coro(
        hh_apply.fill_and_submit_questionnaire(_make_acc(), "777", "Dev", "Comp")
    )

    assert result == "auth_error"
    assert "connector" not in rec.ctor_kwargs
    assert "proxy" not in rec.ctor_kwargs
    _method, _url, kw = rec.calls[0]
    assert "proxy" not in kw
    assert "connector" not in kw
