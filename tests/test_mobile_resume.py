"""Тесты Phase 4: mobile-версия fetch_resume (app/mobile_resume.py).

Полный путь: app.mobile_resume.fetch_resume →
app.mobile_resume_common.resolve_resume_id →
app.hh_mobile_transport.mobile_request → реальный HTTP (перехваченный
библиотекой `responses`) → разбор ответа. Никаких живых запросов: все URL
api.hh.ru замокан, Bearer-токен подменён через monkeypatch
app.oauth._obtain_oauth_token.

Контракт (см. докстринг app/mobile_resume.py):
- GET https://api.hh.ru/resumes/{id}?with_professional_roles=true&with_creds=true
  (БЕЗ /mobile-префикса — официальный OAuth-endpoint);
- resume_id=None → acc["resume_hash"] → первое резюме из
  GET /mobile/resumes/mine (запасной путь GET /resumes/mine);
- fallback-статусы (0/401/403/5xx) — MobileAPIError наверх;
- прочие не-2xx (404 и т.п.) и пустой резолв hash'а → {} без исключения.

ИМПОРТ модуля реализации выполняется ВНУТРИ тест-функций (конвенция
tests/test_mobile_phase2_integration.py).
"""
import pytest
import responses

from app import oauth
from app.hh_client_mobile import MobileHHClient
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}

# Форма — по live-пробе GET /resumes/{id} (legacy-формат api.hh.ru,
# scratchpad/apidocs/apidocs_group_2.yaml).
RESUME_RESPONSE = {"id": "rhash1", "title": "Тестировщик ПО", "first_name": "Мария"}


@pytest.fixture
def oauth_token(monkeypatch):
    """Bearer-токен добывается через app.oauth._obtain_oauth_token —
    подменяем, чтобы не идти в реальный OAuth-flow."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")


def _last_request():
    assert responses.calls, "ни одного реального HTTP-запроса не было"
    return responses.calls[-1].request


def _assert_bearer(req):
    assert req.headers["Authorization"] == "Bearer t"
    # мобильные заголовки транспорта (контракт APK)
    assert req.headers["x-force-app-access"] == "true"


def _request_paths():
    """Пути всех сделанных запросов (без query-строки)."""
    return [c.request.url.split("?")[0] for c in responses.calls]


# ---------------------------------------------------------------------------
# 1. End-to-end: явный resume_id → GET /resumes/{id} с флагами
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_fetch_resume_end_to_end(oauth_token):
    from app.mobile_resume import fetch_resume

    responses.add(responses.GET, MOBILE_BASE + "/resumes/rhash1",
                  json=RESUME_RESPONSE, status=200)

    result = fetch_resume(ACC, "rhash1")

    # полный JSON резюме возвращается как есть
    assert result == RESUME_RESPONSE

    assert len(responses.calls) == 1  # явный hash — резолв без списков
    req = _last_request()
    assert req.method == "GET"
    # официальный OAuth-endpoint: БЕЗ /mobile-префикса
    assert req.url.split("?")[0] == MOBILE_BASE + "/resumes/rhash1"
    assert "/mobile" not in req.url.split("?")[0]
    # флаги полного резюме (professional roles + контакты/креды)
    assert "with_professional_roles=true" in req.url
    assert "with_creds=true" in req.url
    _assert_bearer(req)


# ---------------------------------------------------------------------------
# 2. resume_id=None → acc["resume_hash"], список резюме НЕ запрашивается
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_fetch_resume_none_takes_acc_resume_hash(oauth_token):
    from app.mobile_resume import fetch_resume

    responses.add(responses.GET, MOBILE_BASE + "/resumes/rh1",
                  json=RESUME_RESPONSE, status=200)

    result = fetch_resume(ACC)  # resume_id=None

    assert result == RESUME_RESPONSE
    # hash взят из acc["resume_hash"] — GET /mobile/resumes/mine не нужен
    assert MOBILE_BASE + "/mobile/resumes/mine" not in _request_paths()
    assert MOBILE_BASE + "/resumes/mine" not in _request_paths()
    assert _request_paths() == [MOBILE_BASE + "/resumes/rh1"]


# ---------------------------------------------------------------------------
# 3. acc без resume_hash → GET /mobile/resumes/mine → GET /resumes/{id}
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_fetch_resume_resolves_via_mine_list(oauth_token):
    from app.mobile_resume import fetch_resume

    responses.add(responses.GET, MOBILE_BASE + "/mobile/resumes/mine",
                  json={"items": [{"id": "abc123", "title": "X"}]}, status=200)
    responses.add(responses.GET, MOBILE_BASE + "/resumes/abc123",
                  json={"id": "abc123", "title": "X"}, status=200)

    result = fetch_resume({"name": "a1", "cookies": {}})  # без resume_hash

    assert isinstance(result, dict) and result.get("id") == "abc123"
    # сначала список резюме, потом само резюме — именно в таком порядке
    assert _request_paths() == [
        MOBILE_BASE + "/mobile/resumes/mine",
        MOBILE_BASE + "/resumes/abc123",
    ]


# ---------------------------------------------------------------------------
# 4. /mobile/resumes/mine вернул 404 → запасной GET /resumes/mine
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_fetch_resume_mine_404_falls_back_to_resumes_mine(oauth_token):
    from app.mobile_resume import fetch_resume

    responses.add(responses.GET, MOBILE_BASE + "/mobile/resumes/mine",
                  json={"errors": [{"value": "not_found"}]}, status=404)
    responses.add(responses.GET, MOBILE_BASE + "/resumes/mine",
                  json={"items": [{"hash": "h2"}]}, status=200)
    responses.add(responses.GET, MOBILE_BASE + "/resumes/h2",
                  json={"id": "h2", "title": "Y"}, status=200)

    result = fetch_resume({"name": "a1", "cookies": {}})

    assert result.get("id") == "h2"
    assert _request_paths() == [
        MOBILE_BASE + "/mobile/resumes/mine",
        MOBILE_BASE + "/resumes/mine",
        MOBILE_BASE + "/resumes/h2",
    ]


# ---------------------------------------------------------------------------
# 5. У аккаунта нет резюме (оба списка пусты) → {} без запроса /resumes/{id}
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_fetch_resume_no_resumes_returns_empty(oauth_token):
    from app.mobile_resume import fetch_resume

    responses.add(responses.GET, MOBILE_BASE + "/mobile/resumes/mine",
                  json={"items": []}, status=200)
    responses.add(responses.GET, MOBILE_BASE + "/resumes/mine",
                  json={"items": []}, status=200)

    result = fetch_resume({"name": "a1", "cookies": {}})

    assert result == {}
    # только два запроса списков — ни одного GET /resumes/{id}
    assert _request_paths() == [
        MOBILE_BASE + "/mobile/resumes/mine",
        MOBILE_BASE + "/resumes/mine",
    ]


# ---------------------------------------------------------------------------
# 6. GET /resumes/{id} → 404: не fallback-статус → {} без исключения
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_fetch_resume_404_returns_empty(oauth_token):
    from app.mobile_resume import fetch_resume

    responses.add(responses.GET, MOBILE_BASE + "/resumes/rhash1",
                  json={"errors": [{"value": "resume_not_found"}]}, status=404)

    assert fetch_resume(ACC, "rhash1") == {}


# ---------------------------------------------------------------------------
# 7. Fallback-статусы (401/500) — MobileAPIError поднимается наверх
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [401, 500])
@responses.activate
def test_mobile_fetch_resume_fallback_status_raises(oauth_token, status):
    """401/5xx — fallback-статусы: проглатывать нельзя, кидает MobileAPIError
    (FallbackHHClient повторит через web-flow)."""
    from app.mobile_resume import fetch_resume

    responses.add(responses.GET, MOBILE_BASE + "/resumes/rhash1",
                  json={"errors": [{"value": "token_expired"}]}, status=status)

    with pytest.raises(MobileAPIError) as ei:
        fetch_resume(ACC, "rhash1")
    assert ei.value.status_code == status


# ---------------------------------------------------------------------------
# 8. Делегат клиента: MobileHHClient.fetch_resume → app.mobile_resume
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_client_fetch_resume_delegates(oauth_token):
    responses.add(responses.GET, MOBILE_BASE + "/resumes/rhash1",
                  json=RESUME_RESPONSE, status=200)

    result = MobileHHClient(ACC).fetch_resume("rhash1")

    assert result == RESUME_RESPONSE
    req = _last_request()
    assert req.url.split("?")[0] == MOBILE_BASE + "/resumes/rhash1"
    _assert_bearer(req)
