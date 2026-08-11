"""Тесты mobile-модуля: работодатели, которых можно оценить.

Проверяется полный путь: app.mobile_employer_reviews.fetch_employers_to_rate
→ app.hh_mobile_transport.mobile_request → реальный HTTP, перехваченный
библиотекой `responses` (никаких живых запросов: все URL api.hh.ru
замоканы, Bearer-токен подменён через monkeypatch
app.oauth._obtain_oauth_token).

Контракт (проверен live-пробой):

    GET https://api.hh.ru/employer_reviews/employers_to_rate
    -> {"status": "EMPLOYERS_CAN_BE_REVIEWED", "items": [{employer_id,
       employer_name, position, target, logo_urls, ...}, ...]}

Конвенция тестов — tests/test_mobile_job_search_status.py.
"""
import pytest
import responses

from app import oauth
from app.hh_mobile_transport import MOBILE_BASE, MOBILE_UA, MobileAPIError
from app.user_agent import mobile_user_agent

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}

TO_RATE_URL = MOBILE_BASE + "/employer_reviews/employers_to_rate"

# Live-форма ответа (обрезана до значимых полей).
LIVE_SAMPLE = {
    "status": "EMPLOYERS_CAN_BE_REVIEWED",
    "items": [
        {
            "employer_id": 118368,
            "is_employer_mapped": False,
            "target": "PREVIOUS_EMPLOYER",
            "employer_name": "НПА Вира Реалтайм",
            "logo_urls": {"90": "https://img.hh.ru/90.png",
                          "240": "https://img.hh.ru/240.png"},
            "position": "Инженер-программист",
            "employment_duration_id": "1",
            "area_id": 1,
            "country_id": 1,
        },
        {
            "employer_id": 999,
            "is_employer_mapped": True,
            "target": "CURRENT_EMPLOYER",
            "employer_name": "ООО Ромашка",
            "logo_urls": {},
            "position": "Курьер",
            "employment_duration_id": "2",
            "area_id": 2,
            "country_id": 1,
        },
    ],
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
    assert req.headers["User-Agent"] == (mobile_user_agent() or MOBILE_UA)


# ---------------------------------------------------------------------------
# 1. Happy-path: 2xx → {ok, count, status, items} + нормализация полей
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_employers_to_rate_happy_path(oauth_token):
    from app.mobile_employer_reviews import fetch_employers_to_rate

    responses.add(responses.GET, TO_RATE_URL, json=LIVE_SAMPLE, status=200)

    result = fetch_employers_to_rate(ACC)

    assert result["ok"] is True
    assert result["count"] == 2
    assert result["status"] == "EMPLOYERS_CAN_BE_REVIEWED"
    assert result["items"] == [
        {"employer_id": 118368, "employer_name": "НПА Вира Реалтайм",
         "position": "Инженер-программист", "target": "PREVIOUS_EMPLOYER"},
        {"employer_id": 999, "employer_name": "ООО Ромашка",
         "position": "Курьер", "target": "CURRENT_EMPLOYER"},
    ]

    req = _last_request()
    assert req.method == "GET"
    assert req.url.split("?")[0] == TO_RATE_URL
    _assert_bearer(req)


@responses.activate
def test_fetch_employers_to_rate_only_normalized_fields(oauth_token):
    """В UI уходят ТОЛЬКО 4 нормализованных поля — logo_urls, area_id и пр.
    не пробрасываются."""
    from app.mobile_employer_reviews import fetch_employers_to_rate

    responses.add(responses.GET, TO_RATE_URL, json=LIVE_SAMPLE, status=200)

    result = fetch_employers_to_rate(ACC)
    for item in result["items"]:
        assert set(item.keys()) == {"employer_id", "employer_name",
                                    "position", "target"}


# ---------------------------------------------------------------------------
# 2. Пустой items / другой status — тоже успех (count=0)
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_employers_to_rate_empty_items(oauth_token):
    from app.mobile_employer_reviews import fetch_employers_to_rate

    responses.add(responses.GET, TO_RATE_URL,
                  json={"status": "", "items": []}, status=200)

    result = fetch_employers_to_rate(ACC)
    assert result == {"ok": True, "count": 0, "items": [], "status": ""}


@responses.activate
def test_fetch_employers_to_rate_empty_body_204(oauth_token):
    """Пустое тело на 2xx (mobile_request вернёт None) → пустой результат,
    не падая."""
    from app.mobile_employer_reviews import fetch_employers_to_rate

    responses.add(responses.GET, TO_RATE_URL, status=204)

    result = fetch_employers_to_rate(ACC)
    assert result == {"ok": True, "count": 0, "items": [], "status": ""}


# ---------------------------------------------------------------------------
# 3. Неожиданная форма ответа — пустой результат без исключения
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    [1, 2, 3],                       # не-dict
    {"status": "X"},                 # items отсутствует
    {"status": "X", "items": None},  # items не список
    {"status": "X", "items": {"a": 1}},
])
@responses.activate
def test_fetch_employers_to_rate_unexpected_shape(oauth_token, body):
    from app.mobile_employer_reviews import fetch_employers_to_rate

    responses.add(responses.GET, TO_RATE_URL, json=body, status=200)

    result = fetch_employers_to_rate(ACC)
    assert result == {"ok": True, "count": 0, "items": [], "status": ""}


@responses.activate
def test_fetch_employers_to_rate_skips_bad_items(oauth_token):
    """Битые элементы (не-dict) пропускаются; у dict без полей — дефолты."""
    from app.mobile_employer_reviews import fetch_employers_to_rate

    responses.add(responses.GET, TO_RATE_URL, json={
        "status": "EMPLOYERS_CAN_BE_REVIEWED",
        "items": [
            LIVE_SAMPLE["items"][0],
            "мусор",
            42,
            {"employer_name": "Без остальных полей"},
        ],
    }, status=200)

    result = fetch_employers_to_rate(ACC)
    assert result["ok"] is True
    assert result["count"] == 2
    assert result["items"][0]["employer_id"] == 118368
    assert result["items"][1] == {"employer_id": None,
                                  "employer_name": "Без остальных полей",
                                  "position": "", "target": ""}


# ---------------------------------------------------------------------------
# 4. Ошибки HTTP: не-fallback → {ok: False, error}; fallback → MobileAPIError
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_employers_to_rate_http_404_error_dict(oauth_token):
    from app.mobile_employer_reviews import fetch_employers_to_rate

    responses.add(responses.GET, TO_RATE_URL,
                  json={"errors": [{"value": "not_found"}]}, status=404)

    result = fetch_employers_to_rate(ACC)
    assert result == {"ok": False, "error": "HTTP 404"}


@pytest.mark.parametrize("code", [401, 403, 500, 503])
@responses.activate
def test_fetch_employers_to_rate_fallback_raises(oauth_token, code):
    """401/403/5xx — fallback-статусы: проглатывать нельзя, кидает
    MobileAPIError (фабрика повторит через web-flow)."""
    from app.mobile_employer_reviews import fetch_employers_to_rate

    responses.add(responses.GET, TO_RATE_URL,
                  json={"errors": [{"value": "token_expired"}]}, status=code)

    with pytest.raises(MobileAPIError) as ei:
        fetch_employers_to_rate(ACC)
    assert ei.value.status_code == code


@responses.activate
def test_fetch_employers_to_rate_network_error_raises(oauth_token):
    """Сетевая ошибка — статус 0, тоже fallback → MobileAPIError наружу."""
    import requests as _requests
    from app.mobile_employer_reviews import fetch_employers_to_rate

    responses.add(responses.GET, TO_RATE_URL,
                  body=_requests.exceptions.ConnectionError("boom"))

    with pytest.raises(MobileAPIError) as ei:
        fetch_employers_to_rate(ACC)
    assert ei.value.status_code == 0
