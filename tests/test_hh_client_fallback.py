"""Тесты auto-fallback mobile → web (app/hh_client_fallback.py, Phase 2).

Без живого HTTP: работают на fake-клиентах с полным набором методов
контракта HHClient, записывающих вызовы. Fallback-статусы — по
app.hh_mobile_transport.is_fallback_status (0/401/403/5xx); прочие
статусы (например 404) перекидываются без обращения к web.
"""
import asyncio
import concurrent.futures

import pytest

from app.config import CONFIG
from app.hh_client import HHClient, HHClientBase, MobileOnlyOps, WebOnlyOps
from app.hh_client_fallback import FallbackHHClient, _METHODS
from app.hh_client_factory import get_client
from app.hh_client_mobile import MobileHHClient
from app.hh_client_web import WebHHClient
from app.hh_mobile_transport import MobileAPIError

ACC = {"name": "fb1", "cookies": {}, "resume_hash": "rh1"}

# async-методы контракта: делегаты обёртки их await'ят, поэтому fake
# реализует их как async def (остальные — обычный def).
_ASYNC_METHODS = {"submit_response", "fill_questionnaire"}


def _run_coro(coro):
    # Тот же приём, что в tests/test_hh_client_delegates.py: pytest-playwright
    # (e2e) может держать «running» loop в главном потоке, поэтому
    # asyncio.run() исполняем в отдельном потоке.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


class _FakeClient:
    """Fake HH-клиент: все методы контракта, записывает вызовы.

    behaviors: имя метода → callable; вызывается с теми же аргументами
    (может вернуть значение или кинуть исключение). Метод без behavior
    возвращает ("<tag>", "<имя метода>") — sentinel для проверки, какой
    именно клиент ответил.
    """

    def __init__(self, tag: str, behaviors: dict = None):
        self.acc = ACC
        self.tag = tag
        self.calls = []
        self.behaviors = behaviors or {}

    def _dispatch(self, name, args, kwargs):
        self.calls.append((name, args, kwargs))
        behavior = self.behaviors.get(name)
        if behavior is not None:
            return behavior(*args, **kwargs)
        return (self.tag, name)


def _make_sync(name):
    def method(self, *args, **kwargs):
        return self._dispatch(name, args, kwargs)

    method.__name__ = name
    return method


def _make_async(name):
    async def method(self, *args, **kwargs):
        return self._dispatch(name, args, kwargs)

    method.__name__ = name
    return method


for _name in _METHODS:
    if _name in _ASYNC_METHODS:
        setattr(_FakeClient, _name, _make_async(_name))
    else:
        setattr(_FakeClient, _name, _make_sync(_name))


def _client(mobile_behaviors=None, web_behaviors=None):
    mobile = _FakeClient("mobile", mobile_behaviors)
    web = _FakeClient("web", web_behaviors)
    return FallbackHHClient(mobile, web), mobile, web


# ── Контракт: полный набор методов HHClient, isinstance ─────────────────────


def test_wrapper_has_every_hh_client_method():
    expected = set(HHClient.__abstractmethods__) | {"fetch_counters"}
    # публичные callable-атрибуты класса — в точности контракт, без посторонних
    public = {
        name
        for name, value in vars(FallbackHHClient).items()
        if not name.startswith("_") and callable(value)
    }
    assert public == expected
    # абстрактных методов не осталось — класс инстанцируется
    assert FallbackHHClient.__abstractmethods__ == frozenset()
    # _METHODS синхронизирован с контрактом (guard от потери метода)
    assert set(_METHODS) == set(HHClient.__abstractmethods__)


def test_isinstance_full_contract():
    client, _, _ = _client()
    assert isinstance(client, HHClient)
    assert isinstance(client, HHClientBase)
    assert isinstance(client, WebOnlyOps)
    assert isinstance(client, MobileOnlyOps)


def test_exposes_wrapped_clients_mode_and_acc():
    mobile = _FakeClient("mobile")
    web = _FakeClient("web")
    client = FallbackHHClient(mobile, web)
    assert client.mobile is mobile
    assert client.web is web
    assert client.acc is mobile.acc
    assert client.mode == "mobile"


# ── Делегирование: успех mobile → web не трогается ──────────────────────────


def test_mobile_success_returns_mobile_result_web_untouched():
    client, mobile, web = _client()
    assert client.fetch_thread("neg1") == ("mobile", "fetch_thread")
    assert mobile.calls == [("fetch_thread", ("neg1",), {})]
    assert web.calls == []


def test_async_mobile_success_returns_mobile_result_web_untouched():
    client, mobile, web = _client()
    res = _run_coro(client.submit_response("v1"))
    assert res == ("mobile", "submit_response")
    assert mobile.calls == [("submit_response", ("v1",), {})]
    assert web.calls == []


# ── Делегирование: fallback-статусы → повтор через web ──────────────────────


@pytest.mark.parametrize("status", [0, 401, 403, 500, 502, 599])
def test_fallback_statuses_retry_web(status):
    def boom(*args, **kwargs):
        raise MobileAPIError(status, payload="err", url="/m")

    client, mobile, web = _client(mobile_behaviors={"send_message": boom})

    assert client.send_message("neg1", "hi") == ("web", "send_message")
    assert len(mobile.calls) == 1
    assert web.calls == [("send_message", ("neg1", "hi"), {})]


def test_kwargs_forwarded_to_web_on_fallback():
    def boom(*args, **kwargs):
        raise MobileAPIError(500, url="/m")

    client, _, web = _client(mobile_behaviors={"send_message": boom})

    client.send_message("neg1", "hi", topic_id="t7")
    assert web.calls == [("send_message", ("neg1", "hi"), {"topic_id": "t7"})]


def test_async_fallback_status_retries_web():
    def boom(*args, **kwargs):
        raise MobileAPIError(401, payload="expired", url="/m")

    client, mobile, web = _client(mobile_behaviors={"submit_response": boom})

    res = _run_coro(client.submit_response("v1", 500))
    assert res == ("web", "submit_response")
    assert len(mobile.calls) == 1
    assert web.calls == [("submit_response", ("v1", 500), {})]


# ── Делегирование: НЕ fallback-статус → перекидываем, web не трогаем ────────


@pytest.mark.parametrize("status", [400, 404, 409, 422])
def test_non_fallback_status_reraises_web_untouched(status):
    err = MobileAPIError(status, payload="bad", url="/m")

    def boom(*args, **kwargs):
        raise err

    client, _, web = _client(mobile_behaviors={"fetch_chat_history": boom})

    with pytest.raises(MobileAPIError) as ei:
        client.fetch_chat_history("c1")
    assert ei.value is err  # тот же объект, без преобразования
    assert web.calls == []


def test_async_non_fallback_status_reraises_web_untouched():
    err = MobileAPIError(404, payload="nf", url="/m")

    def boom(*args, **kwargs):
        raise err

    client, _, web = _client(mobile_behaviors={"fill_questionnaire": boom})

    with pytest.raises(MobileAPIError) as ei:
        _run_coro(client.fill_questionnaire("v1"))
    assert ei.value is err
    assert web.calls == []


# ── Делегирование: NotImplementedError mobile → web ───────────────────────────


def test_mobile_not_implemented_retries_web():
    def stub(*args, **kwargs):
        raise NotImplementedError("phase 2: TODO mobile fetch_chat_list")

    client, _, web = _client(mobile_behaviors={"fetch_chat_list": stub})

    assert client.fetch_chat_list() == ("web", "fetch_chat_list")
    assert web.calls == [("fetch_chat_list", (), {})]


def test_async_mobile_not_implemented_retries_web():
    # fill_questionnaire — web-only: mobile-заглушка, web реализует.
    def stub(*args, **kwargs):
        raise NotImplementedError("phase 3: TODO mobile fill_questionnaire")

    client, _, web = _client(mobile_behaviors={"fill_questionnaire": stub})

    res = _run_coro(client.fill_questionnaire("v1", "Dev", "Ромашка"))
    assert res == ("web", "fill_questionnaire")
    assert web.calls == [("fill_questionnaire", ("v1", "Dev", "Ромашка"), {})]


def test_not_implemented_on_both_reraises():
    # fetch_counters — mobile-only: web-аналога нет, оба кидают
    # NotImplementedError → он перекидывается наружу.
    def stub(*args, **kwargs):
        raise NotImplementedError("нет аналога")

    client, _, _ = _client(
        mobile_behaviors={"fetch_counters": stub},
        web_behaviors={"fetch_counters": stub},
    )
    with pytest.raises(NotImplementedError):
        client.fetch_counters()


# ── Фабрика: mobile → обёртка, web/auto → голый WebHHClient ─────────────────


def test_factory_mobile_returns_fallback_wrapper(monkeypatch):
    monkeypatch.setattr(CONFIG, "default_client_mode", "web")
    acc = {"mode": "mobile", "name": "a1", "cookies": {}, "resume_hash": "rh1"}

    client = get_client(acc)

    assert isinstance(client, FallbackHHClient)
    assert isinstance(client, HHClient)
    assert isinstance(client.mobile, MobileHHClient)
    assert isinstance(client.web, WebHHClient)
    assert client.acc is acc
    assert client.mode == "mobile"


def test_factory_web_returns_plain_web_client(monkeypatch):
    monkeypatch.setattr(CONFIG, "default_client_mode", "web")
    acc = {"mode": "web", "name": "a1", "cookies": {}, "resume_hash": "rh1"}

    client = get_client(acc)

    assert isinstance(client, WebHHClient)
    assert not isinstance(client, FallbackHHClient)


def test_factory_auto_stays_plain_web_client(monkeypatch):
    monkeypatch.setattr(CONFIG, "default_client_mode", "web")
    acc = {"mode": "auto", "name": "a1", "cookies": {}, "resume_hash": "rh1"}

    client = get_client(acc)

    assert isinstance(client, WebHHClient)
    assert not isinstance(client, FallbackHHClient)
