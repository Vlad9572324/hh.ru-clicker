"""Тесты per-account сессий в app.hh_http (CRITICAL fix №3).

Покрываемое поведение:
(a) разные cookie_jar_key → разные instances сессий; повторный доступ →
    тот же instance; cookie_jar_key=None → legacy общая сессия.
(b) LRU-реестр: лимит 100, 101-й ключ вытесняет самый давно не
    использовавшийся; обращение к ключу защищает его от вытеснения.
(c) set_proxy() очищает legacy и per-account сессии, клиент остаётся рабочим.
(d) thread-safety конкурентного доступа к сессиям.

Без сетевых запросов: транспорт заменён fake-сессиями, curl_cffi-путь
принудительно выключен, чтобы тесты были детерминированы независимо от
того, установлен ли curl_cffi (в CI его нет → requests fallback).
"""
import threading
from types import SimpleNamespace

import pytest

import app.hh_http as hh_http
from app.hh_http import HHClient


@pytest.fixture
def fake_transport(monkeypatch):
    """Принудительный requests-fallback + fake-сессии вместо requests.Session.

    Возвращает список всех созданных fake-сессий (в порядке создания).
    """
    created = []

    class FakeSession:
        def __init__(self, *args, **kwargs):
            self.calls = []
            self.closed = False
            created.append(self)

        def request(self, method, url, **kwargs):
            self.calls.append({"method": method, "url": url, **kwargs})
            return SimpleNamespace(
                status_code=200,
                content=b'{"ok": true}',
                headers={},
                text='{"ok": true}',
                json=lambda: {"ok": True},
            )

        def close(self):
            self.closed = True

    monkeypatch.setattr(hh_http, "_HAS_CFFI", False)
    monkeypatch.setattr(hh_http, "_CffiSession", None)
    monkeypatch.setattr(hh_http._requests, "Session", FakeSession)
    return created


@pytest.fixture
def hh_singleton_restored():
    """set_proxy мутирует глобальный HH-singleton — восстанавливаем после теста."""
    old = (hh_http.HH._session_cffi, hh_http.HH._session_req, hh_http.HH._sessions)
    yield hh_http.HH
    hh_http.HH._session_cffi, hh_http.HH._session_req, hh_http.HH._sessions = old


# ---------------------------------------------------------------------------
# (a) Изоляция per-account сессий и legacy-режим
# ---------------------------------------------------------------------------

def test_distinct_accounts_get_distinct_sessions(fake_transport):
    client = HHClient()

    _, req_a = client._get_session("acc-A")
    _, req_b = client._get_session("acc-B")

    assert req_a is not req_b
    assert set(client._sessions) == {"acc-A", "acc-B"}


def test_same_key_returns_same_session_instance(fake_transport):
    client = HHClient()

    _, first = client._get_session("acc-A")
    _, second = client._get_session("acc-A")
    _, third = client._get_session("acc-A")

    assert first is second is third
    assert len(client._sessions) == 1


def test_none_key_returns_legacy_shared_sessions(fake_transport):
    client = HHClient()

    cffi_sess, req_sess = client._get_session(None)

    # legacy общие сессии из __init__, per-account реестр не тронут
    assert cffi_sess is client._session_cffi
    assert req_sess is client._session_req
    assert client._sessions == {}
    # повторный доступ — те же объекты
    assert client._get_session(None) == (client._session_cffi, client._session_req)


def test_request_routes_to_per_account_session_and_passes_cookies(fake_transport):
    client = HHClient()

    r_a = client.request("GET", "https://hh.ru/vacancy/1",
                         cookies={"hhtoken": "tok-A"}, cookie_jar_key="acc-A")
    r_b = client.request("GET", "https://hh.ru/vacancy/2",
                         cookies={"hhtoken": "tok-B"}, cookie_jar_key="acc-B")
    r_leg = client.request("GET", "https://hh.ru/vacancy/3")  # без ключа → legacy

    assert (r_a.status_code, r_b.status_code, r_leg.status_code) == (200, 200, 200)

    sess_a = client._sessions["acc-A"]["req"]
    sess_b = client._sessions["acc-B"]["req"]
    assert sess_a.calls and sess_b.calls
    # cookies прокинуты в сессию своего аккаунта, cookie_jar_key — нет
    assert sess_a.calls[0]["cookies"] == {"hhtoken": "tok-A"}
    assert sess_b.calls[0]["cookies"] == {"hhtoken": "tok-B"}
    assert "cookie_jar_key" not in sess_a.calls[0]
    # legacy-запрос ушёл в общую сессию, а не в per-account
    assert client._session_req.calls and len(client._session_req.calls) == 1


# ---------------------------------------------------------------------------
# (b) LRU: лимит 100, вытеснение самой давней, recency-защита
# ---------------------------------------------------------------------------

def test_max_sessions_default_is_100():
    assert HHClient._MAX_SESSIONS == 100


def test_lru_evicts_oldest_at_limit_and_recreates_on_reaccess(fake_transport):
    client = HHClient()
    limit = client._MAX_SESSIONS  # 100

    original = {}
    for i in range(limit):
        key = f"k{i:03d}"
        _, sess = client._get_session(key)
        original[key] = sess
    assert len(client._sessions) == limit

    # 101-й ключ вытесняет самую давно не использовавшуюся (k000)
    client._get_session("k100")
    assert len(client._sessions) == limit
    assert "k100" in client._sessions
    assert "k000" not in client._sessions
    # Аудит 2026-08-17 #17: раньше вытесненная сессия сразу .close() — если
    # другой поток держал её в live-request(), запрос падал SSL abort/broken
    # pipe. Теперь не закрываем явно, полагаемся на GC когда последняя
    # ссылка уйдёт. Тест проверяет только удаление из реестра.

    # Повторное обращение к вытесненному ключу создаёт НОВУЮ сессию
    _, recreated = client._get_session("k000")
    assert recreated is not original["k000"]
    assert len(client._sessions) == limit
    # при этом вытеснена теперь следующая по давности (k001)
    assert "k001" not in client._sessions


def test_lru_recency_touch_protects_from_eviction(fake_transport):
    client = HHClient()
    limit = client._MAX_SESSIONS

    for i in range(limit):
        client._get_session(f"k{i:03d}")

    # Обращение к k000 делает его недавно использованным
    _, touched = client._get_session("k000")

    # Новый ключ вытесняет k001 (теперь самую давнюю), а не k000
    client._get_session("k100")
    assert len(client._sessions) == limit
    assert "k000" in client._sessions
    assert client._sessions["k000"]["req"] is touched
    assert "k001" not in client._sessions


# ---------------------------------------------------------------------------
# (c) set_proxy: очистка сессий, клиент остаётся рабочим
# ---------------------------------------------------------------------------

def test_set_proxy_clears_sessions_and_client_stays_working(
        fake_transport, hh_singleton_restored, monkeypatch):
    monkeypatch.setattr(hh_http, "_PROXY", "")
    hh = hh_http.HH

    old_legacy_req = hh._session_req
    r1 = hh.request("GET", "https://hh.ru/vacancy/1",
                    cookies={"hhtoken": "tok"}, cookie_jar_key="acc-1")
    assert r1.status_code == 200
    old_sess = hh._sessions["acc-1"]["req"]

    new_url = hh_http.set_proxy("http://test-proxy:3128")
    assert new_url == "http://test-proxy:3128"
    # legacy и per-account сессии пересозданы/очищены
    assert hh._sessions == {}
    assert hh._session_req is not old_legacy_req
    assert old_sess.closed

    # После set_proxy клиент рабочий: новый запрос получает свежую сессию
    r2 = hh.request("GET", "https://hh.ru/vacancy/2",
                    cookies={"hhtoken": "tok"}, cookie_jar_key="acc-1",
                    _skip_diag=True)
    assert r2.status_code == 200
    new_sess = hh._sessions["acc-1"]["req"]
    assert new_sess is not old_sess
    assert new_sess.calls
    # прокси прокинут в транспорт
    assert new_sess.calls[0]["proxies"] == {
        "http": "http://test-proxy:3128", "https": "http://test-proxy:3128"}

    # legacy-путь тоже работает
    r3 = hh.request("GET", "https://hh.ru/vacancy/3", _skip_diag=True)
    assert r3.status_code == 200
    assert hh._session_req.calls


# ---------------------------------------------------------------------------
# (d) Thread-safety
# ---------------------------------------------------------------------------

def test_concurrent_requests_same_keys_single_session_per_key(fake_transport):
    client = HHClient()
    keys = [f"acc-{i}" for i in range(4)]
    n_threads, n_iters = 16, 25

    errors = []
    observed = {k: set() for k in keys}
    obs_lock = threading.Lock()
    barrier = threading.Barrier(n_threads)

    def worker(tid):
        try:
            barrier.wait(timeout=10)
            for i in range(n_iters):
                key = keys[(tid + i) % len(keys)]
                _, req_sess = client._get_session(key)
                with obs_lock:
                    observed[key].add(id(req_sess))
                r = client.request("GET", "https://hh.ru/api/test",
                                   cookies={"hhtoken": f"tok-{key}"},
                                   cookie_jar_key=key, _skip_diag=True)
                if r.status_code != 200:
                    raise AssertionError(f"bad status {r.status_code}")
        except Exception as e:  # noqa: BLE001 — собираем любые исключения
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"исключения в потоках: {errors}"
    # ровно один instance сессии на ключ, несмотря на конкуренцию
    for key in keys:
        assert len(observed[key]) == 1, f"key {key}: {len(observed[key])} instances"
    assert len(client._sessions) == len(keys) <= client._MAX_SESSIONS
    # все запросы дошли до per-account сессий
    total_calls = sum(len(e["req"].calls) for e in client._sessions.values())
    assert total_calls == n_threads * n_iters


def test_concurrent_lru_stress_registry_stays_bounded(fake_transport):
    client = HHClient()
    client._MAX_SESSIONS = 8  # instance attr, код читает self._MAX_SESSIONS
    keys = [f"k{i:03d}" for i in range(16)]  # в 2 раза больше лимита
    n_threads, n_iters = 16, 20

    errors = []
    barrier = threading.Barrier(n_threads)

    def worker(tid):
        try:
            barrier.wait(timeout=10)
            for i in range(n_iters):
                key = keys[(tid * 7 + i) % len(keys)]
                client.request("GET", "https://hh.ru/x",
                               cookie_jar_key=key, _skip_diag=True)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"исключения в потоках: {errors}"
    # LRU-инвариант под конкуренцией: реестр не превышает лимит
    assert len(client._sessions) <= 8
    # все ключи в реестре валидны и имеют живые сессии
    for key, entry in client._sessions.items():
        assert key in keys
        assert entry["req"] is not None
