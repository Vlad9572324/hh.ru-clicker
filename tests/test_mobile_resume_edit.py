"""Тесты Phase 4: mobile edit_resume_field (app/mobile_resume_edit.py).

WRITE-операция: все запросы к api.hh.ru перехвачены библиотекой
`responses`, никаких живых запросов. Bearer-токен подменён через
monkeypatch app.oauth._obtain_oauth_token.

Проверяемый flow: GET /resumes/{hash}/conditions (валидация строк по
regexp/длинам) → PUT /resume_profile/{hash} (diff-save тело
{resume, creds, additional_properties}, контракт APK
EditResumeProfileRequestNetwork). Политика ошибок: fallback-статусы
(0/401/403/5xx) — MobileAPIError наверх; не-fallback сбой conditions —
валидация пропускается; не-fallback не-2xx на PUT — {"ok": False,
"error": "HTTP ..."}.

Конвенция — tests/test_mobile_phase2_integration.py.
"""
import json

import pytest
import responses

from app import oauth
from app.hh_client_mobile import MobileHHClient
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}

CONDITIONS_URL = MOBILE_BASE + "/resumes/rh1/conditions"
PUT_URL = MOBILE_BASE + "/resume_profile/rh1"


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


def _body_as_dict(req):
    """Тело запроса как dict (PUT /resume_profile всегда JSON)."""
    raw = req.body or ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _mock_conditions(rules: dict, status: int = 200):
    responses.add(responses.GET, CONDITIONS_URL, json=rules, status=status)


def _mock_put(status: int = 200):
    responses.add(responses.PUT, PUT_URL, json={}, status=status)


# ---------------------------------------------------------------------------
# 1. Happy-path: conditions пропущены, PUT выполнен с diff-save телом.
# ---------------------------------------------------------------------------

@responses.activate
def test_edit_resume_field_happy_path(oauth_token):
    from app.mobile_resume_edit import edit_resume_field

    _mock_conditions({"title": {"required": True, "min_length": 2,
                                "max_length": 100}})
    _mock_put(200)

    fields = {"title": [{"string": "QA Engineer"}]}
    result = edit_resume_field(ACC, "rh1", fields)

    assert result == {"ok": True, "updated_field": ["title"]}
    # два запроса: conditions + PUT
    assert len(responses.calls) == 2
    req = _last_request()
    assert req.method == "PUT"
    assert req.url.split("?")[0] == PUT_URL
    _assert_bearer(req)
    body = _body_as_dict(req)
    assert body["resume"] == fields
    assert body["creds"] == {}
    assert body["additional_properties"] == {}


# ---------------------------------------------------------------------------
# 2-3. Валидация по conditions: нарушение → отказ БЕЗ PUT-запроса.
# ---------------------------------------------------------------------------

# regexp с кириллическими диапазонами: "Мария" проходит, "мария" — нет.
NAME_RULE = {"first_name": {"required": True,
                            "regexp": "^[A-ZА-ЯЁ][a-zа-яё]*$",
                            "min_length": 1, "max_length": 100}}


@responses.activate
def test_edit_resume_field_regexp_violation_no_put(oauth_token):
    from app.mobile_resume_edit import edit_resume_field

    _mock_conditions(NAME_RULE)
    _mock_put(200)  # зарегистрирован, но выполнен быть НЕ должен

    result = edit_resume_field(ACC, "rh1", {"first_name": "мария"})

    assert result["ok"] is False
    assert "validation_failed: first_name" in result["error"]
    # только GET conditions — PUT не выполнялся
    assert len(responses.calls) == 1
    assert responses.calls[0].request.method == "GET"


@responses.activate
def test_edit_resume_field_max_length_violation_no_put(oauth_token):
    from app.mobile_resume_edit import edit_resume_field

    _mock_conditions({"title": {"required": True, "min_length": 2,
                                "max_length": 10}})
    _mock_put(200)

    # 20 символов при max_length=10
    result = edit_resume_field(ACC, "rh1", {"title": "X" * 20})

    assert result["ok"] is False
    assert "validation_failed: title" in result["error"]
    assert len(responses.calls) == 1  # только conditions, PUT не выполнен


@responses.activate
def test_edit_resume_field_dict_value_name_violation_no_put(oauth_token):
    """dict-значение: кандидат берётся из "string"/"name" (area-формат)."""
    from app.mobile_resume_edit import edit_resume_field

    _mock_conditions({"area": {"required": False, "max_length": 3}})
    _mock_put(200)

    result = edit_resume_field(ACC, "rh1", {"area": {"id": "1", "name": "Москва"}})

    assert result["ok"] is False
    assert "validation_failed: area" in result["error"]
    assert len(responses.calls) == 1


# ---------------------------------------------------------------------------
# 4. Значение проходит regexp → PUT выполняется.
# ---------------------------------------------------------------------------

@responses.activate
def test_edit_resume_field_regexp_pass_put_executed(oauth_token):
    from app.mobile_resume_edit import edit_resume_field

    _mock_conditions(NAME_RULE)
    _mock_put(200)

    result = edit_resume_field(ACC, "rh1", {"first_name": "Мария"})

    assert result == {"ok": True, "updated_field": ["first_name"]}
    assert len(responses.calls) == 2
    assert _last_request().method == "PUT"
    assert _last_request().url.split("?")[0] == PUT_URL


# ---------------------------------------------------------------------------
# 5. Conditions недоступны (не-fallback 404) → валидация пропущена,
#    запись продолжается.
# ---------------------------------------------------------------------------

@responses.activate
def test_edit_resume_field_conditions_404_skips_validation(oauth_token):
    from app.mobile_resume_edit import edit_resume_field

    _mock_conditions({"errors": [{"value": "resume_conditions_not_found"}]},
                     status=404)
    _mock_put(200)

    result = edit_resume_field(ACC, "rh1", {"title": "QA Engineer"})

    assert result["ok"] is True
    assert result["updated_field"] == ["title"]
    assert len(responses.calls) == 2
    assert responses.calls[0].request.method == "GET"
    assert _last_request().method == "PUT"


# ---------------------------------------------------------------------------
# 6. Ошибки PUT: не-fallback 400 → {"ok": False, error "HTTP 400..."};
#    fallback 401/500 → MobileAPIError наверх.
# ---------------------------------------------------------------------------

@responses.activate
def test_edit_resume_field_put_400_returns_error(oauth_token):
    from app.mobile_resume_edit import edit_resume_field

    _mock_conditions({})  # правил нет — валидация пропускается
    responses.add(responses.PUT, PUT_URL,
                  json={"errors": [{"value": "bad_request"}]}, status=400)

    result = edit_resume_field(ACC, "rh1", {"title": "X"})

    assert result["ok"] is False
    assert "HTTP 400" in result["error"]
    assert len(responses.calls) == 2


@pytest.mark.parametrize("status", [401, 500])
@responses.activate
def test_edit_resume_field_put_fallback_status_raises(oauth_token, status):
    """401/5xx — fallback-статусы: проглатывать нельзя, кидает MobileAPIError."""
    from app.mobile_resume_edit import edit_resume_field

    _mock_conditions({})
    responses.add(responses.PUT, PUT_URL,
                  json={"errors": [{"value": "token_expired"}]}, status=status)

    with pytest.raises(MobileAPIError) as ei:
        edit_resume_field(ACC, "rh1", {"title": "X"})
    assert ei.value.status_code == status


# ---------------------------------------------------------------------------
# 7. Входной контроль без сети: пустые fields / не-dict / пустой hash.
# ---------------------------------------------------------------------------

@responses.activate
def test_edit_resume_field_empty_fields_no_network(oauth_token):
    from app.mobile_resume_edit import edit_resume_field

    result = edit_resume_field(ACC, "rh1", {})

    assert result["ok"] is False
    assert result.get("error")
    assert len(responses.calls) == 0  # ни одного запроса


@responses.activate
def test_edit_resume_field_non_dict_fields_no_network(oauth_token):
    from app.mobile_resume_edit import edit_resume_field

    result = edit_resume_field(ACC, "rh1", ["title"])

    assert result["ok"] is False
    assert len(responses.calls) == 0


@responses.activate
def test_edit_resume_field_empty_resume_hash_no_network(oauth_token):
    from app.mobile_resume_edit import edit_resume_field

    result = edit_resume_field(ACC, "", {"title": "X"})

    assert result["ok"] is False
    assert len(responses.calls) == 0


# ---------------------------------------------------------------------------
# 8. Делегат MobileHHClient.edit_resume_field (happy-path end-to-end).
# ---------------------------------------------------------------------------

@responses.activate
def test_edit_resume_field_via_mobile_client_delegate(oauth_token):
    _mock_conditions({"title": {"required": True, "min_length": 2,
                                "max_length": 100}})
    _mock_put(200)

    result = MobileHHClient(ACC).edit_resume_field(
        "rh1", {"title": [{"string": "QA Engineer"}]})

    assert result == {"ok": True, "updated_field": ["title"]}
    assert len(responses.calls) == 2
    req = _last_request()
    assert req.method == "PUT"
    assert req.url.split("?")[0] == PUT_URL
    _assert_bearer(req)
    body = _body_as_dict(req)
    assert body["resume"] == {"title": [{"string": "QA Engineer"}]}
