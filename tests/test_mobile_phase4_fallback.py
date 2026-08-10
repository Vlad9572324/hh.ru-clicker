"""Тесты Phase 4: auto-fallback mobile → web для методов группы C (резюме).

Проверяется:
1. Правила делегирования FallbackHHClient на фейках (стиль Phase 2,
   см. tests/test_mobile_phase2_integration.py):
   - MobileAPIError с fallback-статусом (401/403) → повтор через web;
   - mobile вернул значение → web НЕ трогается;
   - MobileAPIError(404) — НЕ fallback-статус → re-raise, web не вызывается;
   - NotImplementedError (mobile-заглушка fetch_account_diagnostics) → web.
2. Реальный end-to-end через `responses`: настоящий MobileHHClient идёт
   на api.hh.ru, получает 401 на ПЕРВИЧНОМ endpoint'е метода →
   FallbackHHClient прозрачно продолжает через web-клиент. Зависит от
   параллельной реализации app/mobile_resume*.py и
   app/mobile_job_search_status.py: пока метод там — заглушка
   NotImplementedError, mobile не доходит до сети и тест падает на
   assert'е responses.calls — это ОЖИДАЕМО и фиксируется в отчёте.
3. Фабрика get_client: mode="mobile" → FallbackHHClient(MobileHHClient,
   WebHHClient); mode="web"/"auto"/поле отсутствует → голый WebHHClient.

Никаких живых запросов: api.hh.ru замокан библиотекой `responses`,
Bearer-токен подменён через monkeypatch app.oauth._obtain_oauth_token.
"""
import pytest
import responses

from app import oauth
from app.config import CONFIG
from app.hh_client import HHClient
from app.hh_client_factory import get_client
from app.hh_client_fallback import FallbackHHClient
from app.hh_client_mobile import MobileHHClient
from app.hh_client_web import WebHHClient
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}


@pytest.fixture
def oauth_token(monkeypatch):
    """Bearer-токен добывается через app.oauth._obtain_oauth_token —
    подменяем, чтобы не идти в реальный OAuth-flow."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")


def _assert_bearer(req):
    assert req.headers["Authorization"] == "Bearer t"
    # мобильные заголовки транспорта (контракт APK)
    assert req.headers["x-force-app-access"] == "true"


# ---------------------------------------------------------------------------
# Группа C — 7 методов. Сигнатуры по контракту ABC:
#   fetch_resume(resume_id=None), fetch_stats(resume_id=None),
#   fetch_resume_view_history(limit=50, resume_id=None),
#   fetch_resume_views_aggregate(resume_id=None),
#   analyze_resume(extra_terms=None, resume_id=None),
#   edit_resume_field(resume_hash, fields), set_job_search_status(status).
# ---------------------------------------------------------------------------

EDIT_FIELDS = {"title": [{"string": "QA-инженер"}]}

GROUP_C_CALLS = [
    ("fetch_resume", ()),
    ("fetch_stats", ()),
    ("fetch_resume_view_history", ()),
    ("fetch_resume_views_aggregate", ()),
    ("analyze_resume", ()),
    ("edit_resume_field", ("rh1", EDIT_FIELDS)),
    ("set_job_search_status", ("active_search",)),
]
GROUP_C_NAMES = [name for name, _ in GROUP_C_CALLS]

# Узнаваемые результаты web-двойника (web-контракт: история просмотров — list).
WEB_RESULTS = {name: {"via": "web"} for name in GROUP_C_NAMES}
WEB_RESULTS["fetch_resume_view_history"] = [{"via": "web"}]
WEB_RESULTS["fetch_account_diagnostics"] = {"via": "web"}

# Узнаваемые результаты исправно работающего mobile-клиента.
MOBILE_RESULTS = {
    "fetch_resume": {"via": "mobile", "id": "rh1"},
    "fetch_stats": {"via": "mobile", "views": 42},
    "fetch_resume_view_history": {"via": "mobile", "items": [], "total": 0},
    "fetch_resume_views_aggregate": {"via": "mobile", "total": 5, "total_new": 2},
    "analyze_resume": {"via": "mobile", "ok": True},
    "edit_resume_field": {"via": "mobile", "ok": True, "updated_field": ["title"]},
    "set_job_search_status": {"via": "mobile", "ok": True, "status": "active_search"},
}


# ---------------------------------------------------------------------------
# Фейк-клиенты (по образцу Phase 2: наследники реальных клиентов — проходят
# любые isinstance-проверки, подменяя только тестируемые методы).
# ---------------------------------------------------------------------------

class _MobileC401(MobileHHClient):
    """Реальный MobileHHClient, но все 7 методов группы C кидают
    MobileAPIError(401) — как при протухшем OAuth-токене."""

    def fetch_resume(self, resume_id=None):
        raise MobileAPIError(401, payload="token_expired",
                             url=MOBILE_BASE + "/resumes")

    def fetch_stats(self, resume_id=None):
        raise MobileAPIError(401, payload="token_expired",
                             url=MOBILE_BASE + "/me")

    def fetch_resume_view_history(self, limit=50, resume_id=None):
        raise MobileAPIError(401, payload="token_expired",
                             url=MOBILE_BASE + "/resumes")

    def fetch_resume_views_aggregate(self, resume_id=None):
        raise MobileAPIError(401, payload="token_expired",
                             url=MOBILE_BASE + "/resumes")

    def analyze_resume(self, extra_terms=None, resume_id=None):
        raise MobileAPIError(401, payload="token_expired",
                             url=MOBILE_BASE + "/resumes")

    def edit_resume_field(self, resume_hash, fields):
        raise MobileAPIError(401, payload="token_expired",
                             url=MOBILE_BASE + "/resumes")

    def set_job_search_status(self, status):
        raise MobileAPIError(401, payload="token_expired",
                             url=MOBILE_BASE + "/user_statuses/job_search_statuses/mine")


class _MobileC403(MobileHHClient):
    """Все 7 методов группы C кидают MobileAPIError(403) — нет scope."""

    def fetch_resume(self, resume_id=None):
        raise MobileAPIError(403, payload="forbidden",
                             url=MOBILE_BASE + "/resumes")

    def fetch_stats(self, resume_id=None):
        raise MobileAPIError(403, payload="forbidden",
                             url=MOBILE_BASE + "/me")

    def fetch_resume_view_history(self, limit=50, resume_id=None):
        raise MobileAPIError(403, payload="forbidden",
                             url=MOBILE_BASE + "/resumes")

    def fetch_resume_views_aggregate(self, resume_id=None):
        raise MobileAPIError(403, payload="forbidden",
                             url=MOBILE_BASE + "/resumes")

    def analyze_resume(self, extra_terms=None, resume_id=None):
        raise MobileAPIError(403, payload="forbidden",
                             url=MOBILE_BASE + "/resumes")

    def edit_resume_field(self, resume_hash, fields):
        raise MobileAPIError(403, payload="forbidden",
                             url=MOBILE_BASE + "/resumes")

    def set_job_search_status(self, status):
        raise MobileAPIError(403, payload="forbidden",
                             url=MOBILE_BASE + "/user_statuses/job_search_statuses/mine")


class _MobileCOk(MobileHHClient):
    """Mobile-клиент, успешно отвечающий на все методы группы C."""

    def fetch_resume(self, resume_id=None):
        return MOBILE_RESULTS["fetch_resume"]

    def fetch_stats(self, resume_id=None):
        return MOBILE_RESULTS["fetch_stats"]

    def fetch_resume_view_history(self, limit=50, resume_id=None):
        return MOBILE_RESULTS["fetch_resume_view_history"]

    def fetch_resume_views_aggregate(self, resume_id=None):
        return MOBILE_RESULTS["fetch_resume_views_aggregate"]

    def analyze_resume(self, extra_terms=None, resume_id=None):
        return MOBILE_RESULTS["analyze_resume"]

    def edit_resume_field(self, resume_hash, fields):
        return MOBILE_RESULTS["edit_resume_field"]

    def set_job_search_status(self, status):
        return MOBILE_RESULTS["set_job_search_status"]


class _MobileC404(MobileHHClient):
    """404 — НЕ fallback-статус: повтор через web запрещён."""

    def fetch_resume(self, resume_id=None):
        raise MobileAPIError(404, payload={"errors": [{"value": "resume_not_found"}]},
                             url=MOBILE_BASE + "/resumes")

    def edit_resume_field(self, resume_hash, fields):
        raise MobileAPIError(404, payload={"errors": [{"value": "resume_not_found"}]},
                             url=MOBILE_BASE + f"/resumes/{resume_hash}/conditions")


class _MobileDiagStub(MobileHHClient):
    """Mobile-заглушка fetch_account_diagnostics: метод не реализован
    (составной web-SSR метод, mobile-аналога нет)."""

    def fetch_account_diagnostics(self):
        raise NotImplementedError("phase 4: TODO mobile fetch_account_diagnostics")


class _RecordingWebC(WebHHClient):
    """Web-двойник: записывает вызовы группы C (и диагностику) как
    (имя, args, kwargs) и возвращает узнаваемый результат WEB_RESULTS."""

    def __init__(self, acc):
        super().__init__(acc)
        self.calls = []

    def _rec(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        return WEB_RESULTS[name]

    def fetch_resume(self, *args, **kwargs):
        return self._rec("fetch_resume", *args, **kwargs)

    def fetch_stats(self, *args, **kwargs):
        return self._rec("fetch_stats", *args, **kwargs)

    def fetch_resume_view_history(self, *args, **kwargs):
        return self._rec("fetch_resume_view_history", *args, **kwargs)

    def fetch_resume_views_aggregate(self, *args, **kwargs):
        return self._rec("fetch_resume_views_aggregate", *args, **kwargs)

    def analyze_resume(self, *args, **kwargs):
        return self._rec("analyze_resume", *args, **kwargs)

    def edit_resume_field(self, *args, **kwargs):
        return self._rec("edit_resume_field", *args, **kwargs)

    def set_job_search_status(self, *args, **kwargs):
        return self._rec("set_job_search_status", *args, **kwargs)

    def fetch_account_diagnostics(self, *args, **kwargs):
        return self._rec("fetch_account_diagnostics", *args, **kwargs)


# ---------------------------------------------------------------------------
# 1-2. Fallback-статусы 401/403 → вызов повторяется через web (все 7 методов).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method_name,args", GROUP_C_CALLS, ids=GROUP_C_NAMES)
def test_fallback_c_401_switches_to_web(method_name, args):
    """MobileAPIError(401) — fallback-статус: результат отдаёт web-клиент."""
    web = _RecordingWebC(ACC)
    client = FallbackHHClient(_MobileC401(ACC), web)

    result = getattr(client, method_name)(*args)

    assert result == WEB_RESULTS[method_name]
    assert web.calls == [(method_name, args, {})]


@pytest.mark.parametrize("method_name,args", GROUP_C_CALLS, ids=GROUP_C_NAMES)
def test_fallback_c_403_switches_to_web(method_name, args):
    """MobileAPIError(403) — fallback-статус: результат отдаёт web-клиент."""
    web = _RecordingWebC(ACC)
    client = FallbackHHClient(_MobileC403(ACC), web)

    result = getattr(client, method_name)(*args)

    assert result == WEB_RESULTS[method_name]
    assert web.calls == [(method_name, args, {})]


# ---------------------------------------------------------------------------
# 3. Mobile справился сам → web НЕ трогается (все 7 методов).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method_name,args", GROUP_C_CALLS, ids=GROUP_C_NAMES)
def test_fallback_c_mobile_ok_web_untouched(method_name, args):
    web = _RecordingWebC(ACC)
    client = FallbackHHClient(_MobileCOk(ACC), web)

    result = getattr(client, method_name)(*args)

    assert result == MOBILE_RESULTS[method_name]
    assert web.calls == []  # mobile справился — web не трогаем


# ---------------------------------------------------------------------------
# 4. MobileAPIError(404) — НЕ fallback-статус: re-raise, web не вызывается.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method_name,args", [
    ("fetch_resume", ()),
    ("edit_resume_field", ("rh1", EDIT_FIELDS)),
], ids=["fetch_resume", "edit_resume_field"])
def test_fallback_c_404_reraises_no_web(method_name, args):
    web = _RecordingWebC(ACC)
    client = FallbackHHClient(_MobileC404(ACC), web)

    with pytest.raises(MobileAPIError) as ei:
        getattr(client, method_name)(*args)
    assert ei.value.status_code == 404
    assert web.calls == []


# ---------------------------------------------------------------------------
# 5. NotImplementedError из mobile (заглушка) → сразу web.
# ---------------------------------------------------------------------------

def test_fallback_c_fetch_account_diagnostics_not_implemented_goes_to_web():
    """fetch_account_diagnostics в mobile не реализован (составной web-SSR
    метод) — FallbackHHClient прозрачно вызывает web-версию."""
    web = _RecordingWebC(ACC)
    client = FallbackHHClient(_MobileDiagStub(ACC), web)

    result = client.fetch_account_diagnostics()

    assert result == WEB_RESULTS["fetch_account_diagnostics"]
    assert web.calls == [("fetch_account_diagnostics", (), {})]


# ---------------------------------------------------------------------------
# 6. Реальный end-to-end через responses: настоящий MobileHHClient получает
#    401 на ПЕРВИЧНОМ endpoint'е → FallbackHHClient уходит в web.
#    ЗАВИСИТ от параллельной реализации app/mobile_resume*.py и
#    app/mobile_job_search_status.py (см. докстринг модуля).
# ---------------------------------------------------------------------------

E2E_SPECS = [
    # (метод клиента, позиционные аргументы, HTTP-глагол, ПЕРВИЧНЫЙ endpoint)
    ("fetch_resume", (), "GET", "/resumes/rh1"),
    ("fetch_stats", (), "GET", "/me"),
    ("fetch_resume_view_history", (), "GET", "/resumes/rh1/views"),
    ("fetch_resume_views_aggregate", (), "GET", "/resumes/rh1/views"),
    ("analyze_resume", (), "GET", "/resumes/rh1"),
    ("edit_resume_field", ("rh1", EDIT_FIELDS), "GET", "/resumes/rh1/conditions"),
    ("set_job_search_status", ("active_search",), "PUT",
     "/user_statuses/job_search_statuses/mine"),
]


@responses.activate
@pytest.mark.parametrize("method_name,args,http_method,path", E2E_SPECS,
                         ids=GROUP_C_NAMES)
def test_fallback_c_e2e_mobile_401_falls_back_to_web(oauth_token, method_name,
                                                     args, http_method, path):
    """Мок ПЕРВИЧНОГО endpoint'а на 401: mobile реально сходил в сеть,
    получил fallback-статус → результат вернул web-клиент."""
    responses.add(http_method, MOBILE_BASE + path,
                  json={"errors": [{"type": "authorization",
                                    "value": "token_expired"}]},
                  status=401)

    web = _RecordingWebC(ACC)
    client = FallbackHHClient(MobileHHClient(ACC), web)

    result = getattr(client, method_name)(*args)

    assert result == WEB_RESULTS[method_name]
    assert web.calls == [(method_name, args, {})]
    assert responses.calls, (
        f"MobileHHClient.{method_name} не сделал реального HTTP-запроса — "
        f"модуль app/mobile_*.py ещё заглушка NotImplementedError?"
    )
    req = responses.calls[0].request
    assert req.method == http_method
    assert req.url.split("?")[0] == MOBILE_BASE + path
    _assert_bearer(req)


# ---------------------------------------------------------------------------
# 7. Фабрика get_client: mobile → FallbackHHClient; web/auto/нет поля → web.
# ---------------------------------------------------------------------------

def test_factory_mobile_mode_returns_fallback(monkeypatch):
    monkeypatch.setattr(CONFIG, "default_client_mode", "web")
    client = get_client({"name": "a1", "cookies": {},
                         "resume_hash": "rh1", "mode": "mobile"})

    assert isinstance(client, FallbackHHClient)
    assert isinstance(client, HHClient)
    assert client.mode == "mobile"
    assert isinstance(client.mobile, MobileHHClient)
    assert isinstance(client.web, WebHHClient)


@pytest.mark.parametrize("account_extra", [
    {"mode": "web"},
    {"mode": "auto"},
    {},  # поле mode отсутствует → CONFIG.default_client_mode ("web")
], ids=["web", "auto", "mode-missing"])
def test_factory_web_auto_default_return_plain_web(monkeypatch, account_extra):
    """mode="web"/"auto"/нет поля → голый WebHHClient без fallback-обёртки."""
    monkeypatch.setattr(CONFIG, "default_client_mode", "web")
    client = get_client({"name": "a1", "cookies": {}, **account_extra})

    assert isinstance(client, WebHHClient)
    assert not isinstance(client, FallbackHHClient)
