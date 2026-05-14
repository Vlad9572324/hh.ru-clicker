"""Тесты на classify_apply_response — главный фикс C5.

Этот баг (200 без проверки тела = "sent") молча помечал бы тесты/лимиты/already
как успешные отклики. Покрытие — критично.
"""
import json

from app.hh_apply import classify_apply_response


def test_401_is_auth_error():
    result, info = classify_apply_response(401, "")
    assert result == "auth_error"


def test_403_is_auth_error():
    result, info = classify_apply_response(403, "")
    assert result == "auth_error"


def test_200_login_page_is_auth_error():
    # HH иногда отдаёт 200 + HTML страницы логина (DDoS guard)
    html = '<html>...<a href="/account/login">Войти в аккаунт</a></html>'
    result, info = classify_apply_response(200, html)
    assert result == "auth_error"


def test_200_with_test_required_returns_test_not_sent():
    """Регресс из аудита C5: HH отдаёт test-required с status=200.
    До фикса возвращалось 'sent' (lethal — тест в апплайд)."""
    body = json.dumps({"test-required": True, "responseStatus": {"shortVacancy": {"name": "Dev"}}})
    result, info = classify_apply_response(200, body)
    assert result == "test"
    assert info["title"] == "Dev"


def test_200_with_already_applied_returns_already():
    body = '{"alreadyApplied": true}'
    result, info = classify_apply_response(200, body)
    assert result == "already"


def test_200_with_limit_exceeded_returns_limit():
    body = '{"negotiations-limit-exceeded": true}'
    result, info = classify_apply_response(200, body)
    assert result == "limit"


def test_200_with_success_true_returns_sent():
    body = '{"success":true}'
    result, info = classify_apply_response(200, body)
    assert result == "sent"


def test_200_with_short_vacancy_returns_sent():
    body = json.dumps({"responseStatus": {"shortVacancy": {"name": "Backend Dev", "company": {"name": "Yandex"}}}})
    result, info = classify_apply_response(200, body)
    assert result == "sent"
    assert info["title"] == "Backend Dev"
    assert info["company"] == "Yandex"


def test_200_no_markers_is_error_not_sent():
    """До фикса возвращалось 'sent' для любого 200, теперь без маркеров → error."""
    result, info = classify_apply_response(200, '{"random": "garbage"}')
    assert result == "error"


def test_500_is_error():
    result, info = classify_apply_response(500, "Internal Server Error")
    assert result == "error"


def test_short_vacancy_extracts_contact_info():
    body = json.dumps({
        "responseStatus": {
            "shortVacancy": {
                "name": "X",
                "company": {"name": "Y"},
                "contactInfo": {
                    "fio": "Иванов И.И.",
                    "email": "hr@example.com",
                    "phones": {"phones": [{"country": "7", "city": "999", "number": "1234567"}]},
                },
            },
        },
    })
    result, info = classify_apply_response(200, body)
    assert result == "sent"
    assert info["contact"]["fio"] == "Иванов И.И."
    assert info["contact"]["email"] == "hr@example.com"
    assert info["contact"]["phone"] == "+79991234567"


def test_priority_test_required_beats_success_marker():
    """Если в теле есть и test-required, и success:true — выигрывает test (не отправили реально)."""
    body = '{"test-required": true, "success":true}'
    result, _ = classify_apply_response(200, body)
    assert result == "test"
