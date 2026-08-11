"""Regression-тесты CRITICAL №3: per-account cookie sessions в app.hh_http.

Баг: все аккаунты ходили через ОДНУ requests/curl_cffi Session → общая
cookie jar. Set-Cookie / cookies аккаунта A подмешивались в запросы аккаунта
B (cross-account cookie confusion).

Контракт фиксации:
    HH.request(method, url, ..., cookies=<dict|None>, cookie_jar_key=<str|None>)
    - cookie_jar_key задан  → per-key сессия с изолированной cookie jar;
    - cookie_jar_key=None   → legacy общая сессия (запросы без аккаунтного
      контекста).

Сетевые проверки явно включают requests fallback через `_force_requests=True`,
поэтому `responses` перехватывает запросы независимо от наличия curl_cffi.
Тесты никогда не ходят во внешнюю сеть.
"""
from types import SimpleNamespace

import responses

import app.hh_http as hh_http
import app.hh_negotiations as hh_neg
from app.hh_http import HHClient

BASE = "https://hh.test"


def _cookie_header(call) -> dict:
    """Распарсить Cookie header записанного запроса в dict."""
    header = call.request.headers.get("Cookie", "") or ""
    out = {}
    for part in header.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


# ── 1. Cookies реально уходят в запрос ────────────────────────────────────────


@responses.activate
def test_cookies_kwarg_actually_sent_in_request():
    client = HHClient()
    responses.add(responses.GET, f"{BASE}/api/me", json={"ok": True}, status=200)

    r = client.get(
        f"{BASE}/api/me",
        cookies={"hhtoken": "AAA"},
        cookie_jar_key="accA",
        _force_requests=True,
    )

    assert r.status_code == 200
    assert len(responses.calls) == 1
    sent = _cookie_header(responses.calls[0])
    assert sent.get("hhtoken") == "AAA", f"hhtoken=AAA не ушёл в запрос: {sent}"


# ── 2. Изоляция cookies между аккаунтами (суть бага) ─────────────────────────


@responses.activate
def test_per_account_cookie_isolation_interleaved():
    """Перемежающиеся запросы двух аккаунтов: каждый несёт ТОЛЬКО свои cookies;
    Set-Cookie от сервера аккаунту A не всплывает в запросе аккаунта B."""
    client = HHClient()
    acc_a = {"cookies": {"hhtoken": "AAA"}}
    acc_b = {"cookies": {"hhtoken": "BBB"}}

    # /a отвечает Set-Cookie (имитация серверной-cookie, которую shared-jar
    # реализация разнесла бы по чужим аккаунтам); /b — чистый 200.
    for _ in range(2):
        responses.add(
            responses.GET, f"{BASE}/a", json={"ok": True}, status=200,
            headers={"Set-Cookie": "srvA=from_server; Path=/"},
        )
        responses.add(responses.GET, f"{BASE}/b", json={"ok": True}, status=200)

    # Последовательность A → B → A → B
    fallback = {"_force_requests": True}
    r_a1 = client.get(f"{BASE}/a", cookies=acc_a["cookies"], cookie_jar_key="accA", **fallback)
    r_b1 = client.get(f"{BASE}/b", cookies=acc_b["cookies"], cookie_jar_key="accB", **fallback)
    r_a2 = client.get(f"{BASE}/a", cookies=acc_a["cookies"], cookie_jar_key="accA", **fallback)
    r_b2 = client.get(f"{BASE}/b", cookies=acc_b["cookies"], cookie_jar_key="accB", **fallback)
    assert (r_a1.status_code, r_b1.status_code, r_a2.status_code, r_b2.status_code) == (200, 200, 200, 200)
    assert len(responses.calls) == 4

    c_a1 = _cookie_header(responses.calls[0])
    c_b1 = _cookie_header(responses.calls[1])
    c_a2 = _cookie_header(responses.calls[2])
    c_b2 = _cookie_header(responses.calls[3])

    # Каждый запрос несёт только свой hhtoken
    assert c_a1.get("hhtoken") == "AAA" and "hhtoken" in c_a1
    assert c_b1.get("hhtoken") == "BBB"
    assert c_a2.get("hhtoken") == "AAA"
    assert c_b2.get("hhtoken") == "BBB"
    for i, c in enumerate((c_a1, c_b1, c_a2, c_b2), 1):
        assert c.get("hhtoken") in ("AAA", "BBB"), f"запрос {i}: {c}"
    assert c_a1.get("hhtoken") != c_b1.get("hhtoken")

    # Ключевая проверка shared-jar бага: server-side cookie аккаунта A
    # НЕ должна появиться в запросах аккаунта B.
    assert "srvA" not in c_b1, f"Set-Cookie аккаунта A всплыл у B: {c_b1}"
    assert "srvA" not in c_b2, f"Set-Cookie аккаунта A всплыл у B (2-й запрос): {c_b2}"

    # При этом в рамках своего аккаунта jar живёт между запросами (это
    # легитимно: тот же аккаунт) — подтверждает, что изоляция не сделана
    # «выбрасыванием всех cookies вообще».
    assert c_a2.get("srvA") == "from_server", f"jar аккаунта A не сохранил Set-Cookie: {c_a2}"


def test_per_account_sessions_are_distinct_objects():
    """Whitebox: разные cookie_jar_key → разные сессии (разные jars);
    один ключ → та же сессия (jar живёт между запросами); None → legacy
    общая сессия."""
    client = HHClient()

    _, req_a = client._get_session("accA")
    _, req_a2 = client._get_session("accA")
    _, req_b = client._get_session("accB")
    legacy_cffi, legacy_req = client._get_session(None)

    assert req_a is req_a2, "один cookie_jar_key должен переиспользовать сессию"
    assert req_a is not req_b, "разные cookie_jar_key должны давать разные сессии"
    assert req_a is not legacy_req and req_b is not legacy_req
    # None → именно legacy общая сессия
    assert legacy_req is client._session_req
    assert legacy_cffi is client._session_cffi


# ── 3. Legacy: запрос без cookie_jar_key продолжает работать ─────────────────


@responses.activate
def test_legacy_request_without_cookie_jar_key_still_works():
    client = HHClient()
    responses.add(responses.GET, f"{BASE}/public", json={"ok": True}, status=200)

    # Ни cookie_jar_key, ни cookies — базовый запрос (probe-сценарий)
    r = client.get(f"{BASE}/public", _force_requests=True)
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    # С cookies, но без cookie_jar_key — тоже работает (legacy общая сессия)
    responses.add(responses.GET, f"{BASE}/public2", json={"ok": 2}, status=200)
    r2 = client.get(f"{BASE}/public2", cookies={"foo": "bar"}, _force_requests=True)
    assert r2.status_code == 200
    assert _cookie_header(responses.calls[1]).get("foo") == "bar"


# ── 4. Существующие флоу app.hh_negotiations не сломались ────────────────────


class _RecordingHHStub:
    """Стаб HH: записывает kwargs каждого вызова, отвечает через handler."""

    def __init__(self, handler):
        self.calls = []
        self._handler = handler

    def _record(self, method, url, kwargs):
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        return self._handler(method, url, kwargs)

    def request(self, method, url, **kwargs):
        return self._record(method, url, kwargs)

    def get(self, url, **kwargs):
        return self._record("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._record("POST", url, kwargs)


def _assert_per_account_http_kwargs(calls, acc):
    """Каждый HTTP-вызов флоу несёт cookies аккаунта и per-account jar key."""
    assert calls, "флоу не сделал ни одного HTTP-вызова"
    keys = set()
    for call in calls:
        kw = call["kwargs"]
        assert kw.get("cookies") == acc["cookies"], (
            f"{call['method']} {call['url']}: cookies аккаунта не переданы"
        )
        jar_key = kw.get("cookie_jar_key")
        assert isinstance(jar_key, str) and jar_key, (
            f"{call['method']} {call['url']}: cookie_jar_key не передан "
            f"(запрос уйдёт в legacy общую сессию — регресс cross-account бага)"
        )
        keys.add(jar_key)
    # Один аккаунт — один стабильный jar key в рамках флоу
    assert len(keys) == 1, f"jar key нестабилен в рамках одного аккаунта: {keys}"


def test_fetch_negotiations_stats_flow_passes_cookies_and_jar_key(monkeypatch):
    """fetch_hh_negotiations_stats: флоу работает на мокнутых данных и
    передаёт cookies + cookie_jar_key в каждый запрос."""
    acc = {"name": "accA", "resume_hash": "rh_a", "cookies": {"hhtoken": "AAA", "_xsrf": "XS"}}

    def handler(method, url, kwargs):
        # Пустая страница переговоров без items → оба цикла завершаются на page 0
        return SimpleNamespace(
            status_code=200,
            text="<html><body>переговоров нет</body></html>",
            json=lambda: {},
        )

    stub = _RecordingHHStub(handler)
    monkeypatch.setattr(hh_neg, "HH", stub)

    result = hh_neg.fetch_hh_negotiations_stats(acc, max_pages=3)

    # Флоу вернул валидный результат на мокнутых данных
    assert result["auth_error"] is False
    assert result["interview"] == 0
    assert result["neg_ids"] == []
    # Были и INTERVIEW-запрос, и общий
    assert any("state=INTERVIEW" in c["url"] for c in stub.calls)
    assert any("state=INTERVIEW" not in c["url"] for c in stub.calls)
    _assert_per_account_http_kwargs(stub.calls, acc)


_SSR_DISCARD_HTML = (
    '<html><body><template id="HH-Lux-InitialState">'
    '{"applicantNegotiations": {"topicList": [{"id": 12345, '
    '"actions": [{"id": "decline", "url": "/applicant/negotiations/decline"}]}]}}'
    '</template></body></html>'
)


def test_auto_decline_discards_flow_passes_cookies_and_jar_key(monkeypatch):
    """auto_decline_discards (GET списка + POST decline): флоу работает и
    передаёт cookies + cookie_jar_key и в GET, и в POST."""
    acc = {"name": "accA", "resume_hash": "rh_a", "cookies": {"hhtoken": "AAA", "_xsrf": "XS"}}
    state = {"gets": 0}

    def handler(method, url, kwargs):
        if method == "GET":
            state["gets"] += 1
            text = _SSR_DISCARD_HTML if state["gets"] == 1 else "<html></html>"
            return SimpleNamespace(status_code=200, text=text, json=lambda: {})
        # POST /applicant/negotiations/decline
        return SimpleNamespace(status_code=200, text='{"ok": true}',
                               json=lambda: {"ok": True})

    stub = _RecordingHHStub(handler)
    monkeypatch.setattr(hh_neg, "HH", stub)

    declined = hh_neg.auto_decline_discards(acc)

    assert declined == 1, "флоу не отклонил мок-дискард"
    posts = [c for c in stub.calls if c["method"] == "POST"]
    assert len(posts) == 1
    assert posts[0]["kwargs"]["data"]["topicId"] == "12345"
    assert posts[0]["kwargs"]["data"]["_xsrf"] == "XS"
    _assert_per_account_http_kwargs(stub.calls, acc)


# ── 5. set_proxy("") после серии per-account запросов ────────────────────────


@responses.activate
def test_set_proxy_empty_does_not_break_next_request(monkeypatch):
    """Серия per-account запросов через глобальный HH → set_proxy("") →
    следующий per-account запрос работает и несёт cookies."""
    monkeypatch.setattr(hh_http, "_PROXY", "")

    responses.add(responses.GET, f"{BASE}/p1", json={"ok": 1}, status=200)
    responses.add(responses.GET, f"{BASE}/p2", json={"ok": 2}, status=200)
    responses.add(responses.GET, f"{BASE}/p3", json={"ok": 3}, status=200)

    r1 = hh_http.HH.get(f"{BASE}/p1", cookies={"hhtoken": "AAA"}, cookie_jar_key="accA", _force_requests=True)
    r2 = hh_http.HH.get(f"{BASE}/p2", cookies={"hhtoken": "BBB"}, cookie_jar_key="accB", _force_requests=True)
    assert (r1.status_code, r2.status_code) == (200, 200)

    assert hh_http.set_proxy("") == ""

    r3 = hh_http.HH.get(f"{BASE}/p3", cookies={"hhtoken": "AAA"}, cookie_jar_key="accA", _force_requests=True)
    assert r3.status_code == 200, "запрос после set_proxy('') сломался"
    sent = _cookie_header(responses.calls[2])
    assert sent.get("hhtoken") == "AAA", f"после set_proxy cookies потерялись: {sent}"
