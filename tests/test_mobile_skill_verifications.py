"""Тесты навыков и верификаций: methods / skills / syllabus (read-only GET).

Проверяется полный путь: app.mobile_skill_verifications.* →
app.hh_mobile_transport.mobile_request → реальный HTTP, перехваченный
библиотекой `responses` (никаких живых запросов: все URL api.hh.ru
замоканы, Bearer-токен подменён через monkeypatch
app.oauth._obtain_oauth_token).

Проверенные формы ответов — live-пробы (см. scratchpad deepdive
report_kimi.md / probe_qwen_r2_final.json). Конвенция тестов —
tests/test_mobile_job_search_status.py.
"""
import pytest
import responses

from app import oauth
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}

METHODS_URL = MOBILE_BASE + "/skill_verifications/methods"
SKILLS_URL = MOBILE_BASE + "/skill_verifications/skills"


def _syllabus_url(skill_id):
    return f"{MOBILE_BASE}/verification_methods/skills/{skill_id}"


# Формы — как в live-пробах (урезаны до значимых полей).
METHODS_PAYLOAD = {
    "found": 1, "page": 0, "pages": 1, "per_page": 100,
    "items": [{
        "id": 295, "group_id": 7,
        "name": "Python — средний уровень", "description": "...",
        "platform": "KAK_DELA_QUIZ",
        "kak_dela_quiz": {
            "quiz_id": "q-1", "url_template": "https://hh.ru/quiz/{quiz_id}",
            "estimated_time": 1200,
            "content": "• Функции\n• Модули\n• Классы и ООП",
            "task_number": 13,
        },
        "verification_objects": [{
            "id": 1114, "name": "Python", "category": "SKILL",
            "level": {"id": 9, "internal_id": "middle",
                      "name": "Средний", "rank": 2},
        }],
        "availability": {"available_at": None, "status": "AVAILABLE"},
    }],
}

SKILLS_PAYLOAD = {
    "found": 1,
    "items": [{
        "id": 730, "name": "Linux", "category": "SKILL",
        "level": None, "verified": False, "verified_by": "NONE",
        "has_report": False,
    }],
}

SYLLABUS_PAYLOAD = {
    "id": 1114, "name": "Python", "category": "SKILL",
    "result": {"state": "NONE", "theory": "AVAILABLE", "practice": "NOT_EXIST"},
    "levels": [{
        "id": 9, "internal_id": "middle", "name": "Средний", "rank": 2,
        "theory": {
            "id": 295, "name": "Python — средний уровень",
            "content": "• Функции\n• Модули", "task_number": 13,
            "estimated_time": 1200,
        },
    }],
}


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


# ---------------------------------------------------------------------------
# 1. Happy-path: GET → {"ok": True, "found": N, "items": [...]}
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_skill_verification_methods_ok(oauth_token):
    from app.mobile_skill_verifications import fetch_skill_verification_methods

    responses.add(responses.GET, METHODS_URL, json=METHODS_PAYLOAD, status=200)

    result = fetch_skill_verification_methods(ACC)

    assert result["ok"] is True
    assert result["found"] == 1
    assert result["items"] == METHODS_PAYLOAD["items"]

    req = _last_request()
    assert req.method == "GET"
    assert req.url.split("?")[0] == METHODS_URL
    _assert_bearer(req)


@responses.activate
def test_fetch_skill_verification_skills_ok(oauth_token):
    from app.mobile_skill_verifications import fetch_skill_verification_skills

    responses.add(responses.GET, SKILLS_URL, json=SKILLS_PAYLOAD, status=200)

    result = fetch_skill_verification_skills(ACC)

    assert result["ok"] is True
    assert result["found"] == 1
    assert result["items"] == SKILLS_PAYLOAD["items"]

    req = _last_request()
    assert req.method == "GET"
    assert req.url.split("?")[0] == SKILLS_URL
    _assert_bearer(req)


@responses.activate
def test_fetch_verification_syllabus_ok(oauth_token):
    from app.mobile_skill_verifications import fetch_verification_syllabus

    responses.add(responses.GET, _syllabus_url(1114),
                  json=SYLLABUS_PAYLOAD, status=200)

    result = fetch_verification_syllabus(ACC, 1114)

    assert result["ok"] is True
    assert result["id"] == 1114
    assert result["name"] == "Python"
    assert result["levels"] == SYLLABUS_PAYLOAD["levels"]
    assert result["result"] == SYLLABUS_PAYLOAD["result"]

    req = _last_request()
    assert req.method == "GET"
    # skill_id — из verification_objects (1114), попадает прямо в URL
    assert req.url.split("?")[0] == _syllabus_url(1114)
    _assert_bearer(req)


# ---------------------------------------------------------------------------
# 2. Защитная нормализация: нет found / пустое тело
# ---------------------------------------------------------------------------

@responses.activate
def test_methods_no_found_defaults_to_len(oauth_token):
    """Ответ без "found" — found = len(items)."""
    from app.mobile_skill_verifications import fetch_skill_verification_methods

    responses.add(responses.GET, METHODS_URL,
                  json={"items": [{"id": 1}, {"id": 2}]}, status=200)

    result = fetch_skill_verification_methods(ACC)
    assert result["ok"] is True
    assert result["found"] == 2
    assert len(result["items"]) == 2


@pytest.mark.parametrize("fetch_name,url", [
    ("fetch_skill_verification_methods", METHODS_URL),
    ("fetch_skill_verification_skills", SKILLS_URL),
])
@responses.activate
def test_list_empty_body_204(oauth_token, fetch_name, url):
    """204 без тела (mobile_request вернёт None) — пустой список, не падение."""
    import app.mobile_skill_verifications as mod

    responses.add(responses.GET, url, status=204)

    result = getattr(mod, fetch_name)(ACC)
    assert result == {"ok": True, "found": 0, "items": []}


@responses.activate
def test_syllabus_empty_body_204(oauth_token):
    import app.mobile_skill_verifications as mod

    responses.add(responses.GET, _syllabus_url(1114), status=204)

    result = mod.fetch_verification_syllabus(ACC, 1114)
    assert result == {"ok": True}


# ---------------------------------------------------------------------------
# 3. Ошибки HTTP: не-fallback → {ok: False, error}; fallback → MobileAPIError
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fetch_name,url", [
    ("fetch_skill_verification_methods", METHODS_URL),
    ("fetch_skill_verification_skills", SKILLS_URL),
])
@responses.activate
def test_http_400_error_dict(oauth_token, fetch_name, url):
    import app.mobile_skill_verifications as mod

    responses.add(responses.GET, url,
                  json={"errors": [{"value": "bad"}]}, status=400)

    result = getattr(mod, fetch_name)(ACC)
    assert result["ok"] is False
    assert "HTTP 400" in result["error"]


@responses.activate
def test_syllabus_http_404_error_dict(oauth_token):
    from app.mobile_skill_verifications import fetch_verification_syllabus

    responses.add(responses.GET, _syllabus_url(999),
                  json={"errors": [{"value": "not_found"}]}, status=404)

    result = fetch_verification_syllabus(ACC, 999)
    assert result["ok"] is False
    assert "HTTP 404" in result["error"]


@pytest.mark.parametrize("code", [401, 403, 500])
@responses.activate
def test_methods_fallback_raises(oauth_token, code):
    """401/403/5xx — fallback-статусы: проглатывать нельзя, кидает
    MobileAPIError (фабрика повторит через web-flow)."""
    from app.mobile_skill_verifications import fetch_skill_verification_methods

    responses.add(responses.GET, METHODS_URL,
                  json={"errors": [{"value": "token_expired"}]}, status=code)

    with pytest.raises(MobileAPIError) as ei:
        fetch_skill_verification_methods(ACC)
    assert ei.value.status_code == code


@pytest.mark.parametrize("code", [401, 500])
@responses.activate
def test_skills_fallback_raises(oauth_token, code):
    from app.mobile_skill_verifications import fetch_skill_verification_skills

    responses.add(responses.GET, SKILLS_URL, json={}, status=code)

    with pytest.raises(MobileAPIError) as ei:
        fetch_skill_verification_skills(ACC)
    assert ei.value.status_code == code


@pytest.mark.parametrize("code", [401, 500])
@responses.activate
def test_syllabus_fallback_raises(oauth_token, code):
    from app.mobile_skill_verifications import fetch_verification_syllabus

    responses.add(responses.GET, _syllabus_url(1114), json={}, status=code)

    with pytest.raises(MobileAPIError) as ei:
        fetch_verification_syllabus(ACC, 1114)
    assert ei.value.status_code == code
