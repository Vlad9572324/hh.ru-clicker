"""Guard + функциональные тесты против прямых requests.* вызовов к hh.ru.

Security finding HIGH #5: весь hh.ru egress обязан идти через HH-клиент
(app/hh_http.py) — он инжектит HH_PROXY и cookies аккаунта. Прямые
`requests.get(hh_base() + ...)` обходят HH_PROXY и светят реальный IP.

Часть 1 (guard): AST-скан app/**/*.py — никаких прямых requests.* вызовов
с hh.ru/hh.kz/hh_base() URL вне app/hh_http.py. Ловит однострочные и
многострочные вызовы, f-string с hh_base(), requests.Session().get() и
`s = requests.Session(); s.get(...)`.

Часть 2 (функциональные): исправленные call-sites реально уходят с
proxies=HH_PROXY и cookies аккаунта.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"

# Единственная легитимная точка hh.ru egressа.
_ALLOWED_FILES = {
    APP_DIR / "hh_http.py",
    # Phase 0 skeleton: MobileHHClient.fetch_counters использует requests напрямую
    # для mock'абельности через responses lib (осознанное решение). Bearer,
    # a не cookies → HH_PROXY singleton не оптимален. Мигрируем в Phase 2+.
    APP_DIR / "hh_client_mobile.py",
}

_HTTP_METHODS = {"request", "get", "post", "put", "delete", "head", "patch"}
_HH_URL_MARKERS = ("hh_base", "hh.ru", "hh.kz")

PROXY_URL = "socks5h://singbox:1080"


# ============================================================
# Часть 1: repository-wide AST guard
# ============================================================

def _is_requests_module_ref(node) -> bool:
    return isinstance(node, ast.Name) and node.id == "requests"


def _is_session_ctor(node) -> bool:
    """requests.Session(...)"""
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Session"
            and _is_requests_module_ref(node.func.value))


def _extract_url_arg(call: ast.Call, method_attr: str):
    """URL — positional аргумент или keyword `url=`.
    У requests.request(method, url, ...) URL на второй позиции."""
    pos = 1 if method_attr == "request" else 0
    if len(call.args) > pos:
        return call.args[pos]
    for kw in call.keywords:
        if kw.arg == "url":
            return kw.value
    return None


def _url_refs_hh(url_node) -> bool:
    """Ссылается ли URL-выражение на hh.ru/hh.kz/hh_base().

    ast.unparse покрывает многострочные вызовы и f-string любой вложенности.
    Голый идентификатор (url без hh-маркеров) не флажится — статически
    не-hh URL отличить нельзя, это осознанное ограничение.
    """
    if url_node is None:
        return False
    try:
        dump = ast.unparse(url_node)
    except Exception:
        dump = ast.dump(url_node)
    return any(m in dump for m in _HH_URL_MARKERS)


def _find_direct_hh_calls(tree: ast.AST) -> list:
    """Список нарушений: прямые requests.* вызовы к hh.ru URL."""
    # Имена, которым присвоили requests.Session() — ловим паттерн
    # s = requests.Session(); s.get(hh_base() + ...) (старый _edit_resume_field).
    session_vars = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_session_ctor(node.value):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    session_vars.add(t.id)

    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in _HTTP_METHODS:
            continue
        if _is_requests_module_ref(func.value):
            kind = f"requests.{func.attr}()"
        elif _is_session_ctor(func.value):
            kind = f"requests.Session().{func.attr}()"
        elif isinstance(func.value, ast.Name) and func.value.id in session_vars:
            kind = f"{func.value.id}.{func.attr}() (s = requests.Session())"
        else:
            continue
        if _url_refs_hh(_extract_url_arg(node, func.attr)):
            violations.append(f"line {node.lineno}: {kind} с hh.ru URL")
    return violations


def test_no_direct_requests_calls_to_hh_in_app():
    """Repository-wide guard: в app/ нет прямых requests.* к hh.ru вне hh_http.py."""
    offenders = []
    for path in sorted(APP_DIR.rglob("*.py")):
        if path in _ALLOWED_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for v in _find_direct_hh_calls(tree):
            offenders.append(f"{path.relative_to(ROOT)}:{v}")
    assert not offenders, (
        "Найдены прямые requests.* вызовы к hh.ru в обход HH_PROXY. "
        "Замените на HH-клиент (from app.hh_http import HH):\n"
        + "\n".join(offenders)
    )


# --- Самопроверки детектора (чтобы guard не был пустым) ---

def test_guard_detects_multiline_fstring_violation():
    sample = '''
from app.config import hh_base
import requests

def bad(acc):
    r = requests.get(
        f"{hh_base()}/applicant/resumes",
        cookies=acc.get("cookies", {}),
        timeout=15,
    )
    return r
'''
    assert _find_direct_hh_calls(ast.parse(sample)), \
        "guard обязан ловить многострочный вызов с f-string hh_base()"


def test_guard_detects_session_variable_violation():
    sample = '''
import requests
from app.config import hh_base

def bad():
    s = requests.Session()
    s.get(hh_base() + "/applicant/resumes", timeout=10)
'''
    assert _find_direct_hh_calls(ast.parse(sample)), \
        "guard обязан ловить s = requests.Session(); s.get(hh...)"


def test_guard_detects_inline_session_violation():
    sample = 'import requests\nrequests.Session().post("https://hh.ru/x", timeout=5)\n'
    assert _find_direct_hh_calls(ast.parse(sample))


def test_guard_detects_url_keyword_violation():
    sample = 'import requests\nrequests.request("GET", url="https://api.hh.ru/x")\n'
    assert _find_direct_hh_calls(ast.parse(sample))


def test_guard_ignores_non_hh_urls():
    sample = 'import requests\nrequests.get("https://example.com/search", timeout=5)\n'
    assert not _find_direct_hh_calls(ast.parse(sample))


def test_guard_ignores_exception_types():
    """requests.RequestException в except — не вызов, не флажится."""
    sample = '''
import requests
try:
    pass
except requests.RequestException:
    pass
'''
    assert not _find_direct_hh_calls(ast.parse(sample))


# ============================================================
# Часть 2: функциональные тесты исправленных call-sites
# ============================================================

class _StubResponse:
    def __init__(self, status_code=200, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8") if isinstance(text, str) else b""
        self.headers = {}
        self._payload = payload or {}

    def json(self):
        return self._payload


class _RecordingSession:
    """Стаб транспорта: пишет все вызовы в .calls, отдаёт готовый ответ."""

    def __init__(self, response=None):
        self.calls = []
        self.response = response or _StubResponse()

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response


@pytest.fixture
def hh_proxy():
    """Runtime выставляет HH_PROXY через set_proxy(); возвращает как было."""
    from app import hh_http
    old = hh_http.proxy_url()
    hh_http.set_proxy(PROXY_URL)
    yield PROXY_URL
    hh_http.set_proxy(old or "")


def _patch_hh_transport(monkeypatch, response=None) -> _RecordingSession:
    """Подменяет ОБА транспорта HH-клиента (curl_cffi и requests-fallback)
    на рекордер. Патчить надо после set_proxy() — тот пересоздаёт сессии."""
    from app.hh_http import HH
    rec = _RecordingSession(response=response)
    monkeypatch.setattr(HH, "_session_cffi", rec)
    monkeypatch.setattr(HH, "_session_req", rec)
    return rec


def test_url_preview_hh_url_goes_via_proxy_with_cookies(tmp_data_dir, hh_proxy, monkeypatch):
    """_url_preview_compute для hh.ru URL → HH-клиент c HH_PROXY и cookies."""
    from app.routes import accounts

    rec = _patch_hh_transport(monkeypatch)
    cookies = {"hhtoken": "tok-123", "_xsrf": "xs-1"}

    result = accounts._url_preview_compute(
        "https://hh.ru/search/vacancy?text=python&area=1", cookies)

    assert isinstance(result, dict)
    assert rec.calls, "hh.ru URL обязан идти через HH-клиент, а не прям requests"
    call = rec.calls[0]
    assert call["url"].startswith("https://hh.ru/search/vacancy")
    assert call["proxies"] == {"http": PROXY_URL, "https": PROXY_URL}
    assert call["cookies"] == cookies


def test_url_preview_non_hh_url_not_routed_via_hh_proxy(tmp_data_dir, hh_proxy, monkeypatch):
    """Не-hh URL (произвольный пользовательский) — напрямую, без HH-прокси."""
    from app.routes import accounts

    rec_hh = _patch_hh_transport(monkeypatch)

    plain_calls = []

    def _fake_get(url, **kwargs):
        plain_calls.append({"url": url, **kwargs})
        return _StubResponse(text="<html></html>")

    monkeypatch.setattr("requests.get", _fake_get)

    accounts._url_preview_compute("https://example.com/search/vacancy?text=x", {})

    assert not rec_hh.calls, "не-hh URL нельзя гнать через HH-прокси"
    assert plain_calls and plain_calls[0]["url"].startswith("https://example.com/")
    assert "proxies" not in plain_calls[0], \
        "прямой запрос к не-hh URL не должен получать HH-прокси"


def test_edit_resume_field_goes_via_proxy_with_cookies(tmp_data_dir, hh_proxy, monkeypatch):
    """_edit_resume_field (warmup GET + POST edit) → HH c HH_PROXY и cookies."""
    from app.hh_resume import _edit_resume_field

    rec = _patch_hh_transport(monkeypatch)
    acc = {"cookies": {"hhtoken": "tok-1", "_xsrf": "xs-1"}, "resume_hash": "deadbeef"}

    res = _edit_resume_field(acc, "deadbeef", {"title": [{"string": "Инженер"}]})

    assert res == {"ok": True}
    assert [c["method"] for c in rec.calls] == ["GET", "POST"]
    for c in rec.calls:
        assert c["proxies"] == {"http": PROXY_URL, "https": PROXY_URL}, \
            f"{c['method']} ушёл без HH_PROXY"
        assert c["cookies"] == acc["cookies"]
    assert "resume=deadbeef" in rec.calls[1]["url"]
    assert rec.calls[1]["json"] == {"title": [{"string": "Инженер"}]}


def test_hot_leads_route_goes_via_proxy_with_cookies(tmp_data_dir, hh_proxy, monkeypatch):
    """Роут /api/account/{idx}/hot_leads → HH c HH_PROXY и cookies аккаунта."""
    import asyncio
    from app.routes import accounts

    rec = _patch_hh_transport(monkeypatch, response=_StubResponse(
        payload={"possibleJobOffers": []}))
    acc = {"cookies": {"hhtoken": "tok-2", "_xsrf": "xs-2"}, "resume_hash": "rh2"}
    monkeypatch.setattr(accounts.bot, "_get_apply_acc", lambda idx: acc)

    out = asyncio.run(accounts.api_hot_leads(0))

    assert out == {"offers": [], "total": 0}
    assert rec.calls, "hot_leads обязан идти через HH-клиент"
    c = rec.calls[0]
    assert "/shards/applicant/negotiations/possible_job_offers" in c["url"]
    assert c["proxies"] == {"http": PROXY_URL, "https": PROXY_URL}
    assert c["cookies"] == acc["cookies"]
