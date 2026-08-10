"""Тесты Phase 4: mobile-версия fetch_stats (app/mobile_resume_stats.py).

Проверяется полный путь: fetch_stats(acc) → app.hh_mobile_transport.mobile_request
→ реальный HTTP (перехваченный библиотекой `responses`) → разбор ответов
трёх источников (GET /me, GET /resumes/{id}, GET /negotiations_statistic/mine).
Никаких живых запросов: все URL api.hh.ru замокан, Bearer-токен подменён
через monkeypatch app.oauth._obtain_oauth_token (конвенция
tests/test_mobile_phase2_integration.py).

Контракт результата: web-ключи hh_resume.fetch_resume_stats (views,
views_new, shows, invitations, invitations_new, next_touch_seconds,
free_touches, global_invitations, new_invitations_total — int, дефолт 0)
+ mobile-добавки (resumes_count, unread_negotiations, streak).
shows/invitations/next_touch_seconds/free_touches/global_invitations/
new_invitations_total в mobile-API недоступны (web-SSR данные) — нули.

ИМПОРТ модуля реализации — ВНУТРИ тест-функций (конвенция phase 2):
пока Phase 4 пишется параллельно, отсутствующий модуль должен ронять
только свои тесты, а не коллекционирование всего файла.
"""
import pytest
import responses

from app import oauth
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}

# Ключи, совместимые с web hh_resume.fetch_resume_stats.
WEB_KEYS = (
    "views", "views_new", "shows", "invitations", "invitations_new",
    "next_touch_seconds", "free_touches", "global_invitations",
    "new_invitations_total",
)

# ---------------------------------------------------------------------------
# Мок-ответы. Форма — по live-пробам api.hh.ru (apidocs_group_5/2.yaml).
# ---------------------------------------------------------------------------

ME_RESPONSE = {
    "id": "176187251",
    "counters": {
        "new_resume_views": 3,
        "unread_negotiations": 428,
        "resumes_count": 1,
    },
}

RESUME_RESPONSE = {
    "id": "rh1",
    "total_views": 18000,
    "new_views": 5,
}

STREAK_RESPONSE = {
    "applicant_statistic": {
        "responses_streak": {
            "responses_count": 12,
            "responses_required": 15,
        },
    },
}


@pytest.fixture
def oauth_token(monkeypatch):
    """Bearer-токен добывается через app.oauth._obtain_oauth_token —
    подменяем, чтобы не идти в реальный OAuth-flow."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")


def _called_urls():
    """Список URL запросов (без query-строки) в порядке вызовов."""
    return [c.request.url.split("?")[0] for c in responses.calls]


def _assert_bearer(req):
    assert req.headers["Authorization"] == "Bearer t"
    # мобильные заголовки транспорта (контракт APK)
    assert req.headers["x-force-app-access"] == "true"


def _add_happy_path_mocks():
    """Стандартный набор успешных ответов всех трёх источников."""
    responses.add(responses.GET, MOBILE_BASE + "/me",
                  json=ME_RESPONSE, status=200)
    responses.add(responses.GET, MOBILE_BASE + "/resumes/rh1",
                  json=RESUME_RESPONSE, status=200)
    responses.add(responses.GET, MOBILE_BASE + "/negotiations_statistic/mine",
                  json=STREAK_RESPONSE, status=200)


# ---------------------------------------------------------------------------
# 1. Happy-path: все три источника отвечают 2xx.
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_fetch_stats_happy_path(oauth_token):
    from app.mobile_resume_stats import fetch_stats

    _add_happy_path_mocks()

    result = fetch_stats(ACC)

    # counters профиля (/me)
    assert result["unread_negotiations"] == 428
    assert result["resumes_count"] == 1
    # статистика резюме (/resumes/rh1): total_views и max(3, 5)
    assert result["views"] == 18000
    assert result["views_new"] == 5
    # streak (/negotiations_statistic/mine)
    assert result["streak"] == {"responses_count": 12, "responses_required": 15}
    # web-SSR данные в mobile-API недоступны — нули
    assert result["shows"] == 0
    assert result["invitations"] == 0
    assert result["invitations_new"] == 0
    assert result["next_touch_seconds"] == 0
    assert result["free_touches"] == 0
    assert result["global_invitations"] == 0
    assert result["new_invitations_total"] == 0
    # все web-ключи присутствуют и int
    for key in WEB_KEYS:
        assert key in result, f"нет web-ключа {key}"
        assert isinstance(result[key], int)

    # три источника, порядок: /me → /resumes/rh1 → streak
    assert _called_urls() == [
        MOBILE_BASE + "/me",
        MOBILE_BASE + "/resumes/rh1",
        MOBILE_BASE + "/negotiations_statistic/mine",
    ]
    # основной запрос (/me): Bearer + контракт APK + параметр
    req_me = responses.calls[0].request
    assert req_me.method == "GET"
    assert "with_user_statuses=true" in req_me.url
    _assert_bearer(req_me)


# ---------------------------------------------------------------------------
# 2. /resumes/{id} → 404: источник пропускается, БЕЗ исключения.
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_fetch_stats_resume_404_skipped(oauth_token):
    from app.mobile_resume_stats import fetch_stats

    responses.add(responses.GET, MOBILE_BASE + "/me",
                  json=ME_RESPONSE, status=200)
    responses.add(responses.GET, MOBILE_BASE + "/resumes/rh1",
                  json={"errors": [{"value": "resume_not_found"}]}, status=404)
    responses.add(responses.GET, MOBILE_BASE + "/negotiations_statistic/mine",
                  json=STREAK_RESPONSE, status=200)

    result = fetch_stats(ACC)  # НЕ кидает

    # 404 не fallback: stats из /me остаются, views резюме — 0
    assert result["views"] == 0
    assert result["views_new"] == 3  # new_resume_views из /me, без max
    assert result["unread_negotiations"] == 428
    assert result["resumes_count"] == 1
    # streak-источник отработал независимо
    assert result["streak"] == {"responses_count": 12, "responses_required": 15}


# ---------------------------------------------------------------------------
# 3. /negotiations_statistic/mine → 404: streak пустой, остальное заполнено.
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_fetch_stats_negotiations_stat_404(oauth_token):
    from app.mobile_resume_stats import fetch_stats

    responses.add(responses.GET, MOBILE_BASE + "/me",
                  json=ME_RESPONSE, status=200)
    responses.add(responses.GET, MOBILE_BASE + "/resumes/rh1",
                  json=RESUME_RESPONSE, status=200)
    responses.add(responses.GET, MOBILE_BASE + "/negotiations_statistic/mine",
                  json={"errors": [{"value": "not_found"}]}, status=404)

    result = fetch_stats(ACC)  # НЕ кидает

    assert result["streak"] == {}
    assert result["views"] == 18000
    assert result["views_new"] == 5
    assert result["unread_negotiations"] == 428
    assert result["resumes_count"] == 1


# ---------------------------------------------------------------------------
# 4. /me → fallback-статус (401/500): MobileAPIError наверх,
#    вспомогательные источники НЕ запрашиваются.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [401, 500])
@responses.activate
def test_mobile_fetch_stats_me_fallback_status_raises(oauth_token, status):
    from app.mobile_resume_stats import fetch_stats

    responses.add(responses.GET, MOBILE_BASE + "/me",
                  json={"errors": [{"value": "token_expired"}]}, status=status)

    with pytest.raises(MobileAPIError) as ei:
        fetch_stats(ACC)
    assert ei.value.status_code == status

    # дальше /me дело не пошло — вызов целиком повторится через web-flow
    assert _called_urls() == [MOBILE_BASE + "/me"]


# ---------------------------------------------------------------------------
# 5. acc без resume_hash: hash берётся из GET /mobile/resumes/mine,
#    запрос /resumes/{id} идёт по найденному id.
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_fetch_stats_resolves_resume_via_mine(oauth_token):
    from app.mobile_resume_stats import fetch_stats

    acc_no_hash = {"name": "a1", "cookies": {}}  # без resume_hash

    responses.add(responses.GET, MOBILE_BASE + "/me",
                  json=ME_RESPONSE, status=200)
    responses.add(responses.GET, MOBILE_BASE + "/mobile/resumes/mine",
                  json={"items": [{"id": "r9"}]}, status=200)
    responses.add(responses.GET, MOBILE_BASE + "/resumes/r9",
                  json={"id": "r9", "total_views": 77, "new_views": 2},
                  status=200)
    responses.add(responses.GET, MOBILE_BASE + "/negotiations_statistic/mine",
                  json=STREAK_RESPONSE, status=200)

    result = fetch_stats(acc_no_hash)

    assert result["views"] == 77
    assert result["views_new"] == 3  # max(3 из /me, 2 из резюме)

    urls = _called_urls()
    # rh1 (чужой hash из теста) нигде не запрашивается
    assert MOBILE_BASE + "/resumes/rh1" not in urls
    # вместо него — резюме из списка аккаунта
    assert MOBILE_BASE + "/resumes/r9" in urls
    # резолв шёл через live-контракт Android-приложения
    assert MOBILE_BASE + "/mobile/resumes/mine" in urls


# ---------------------------------------------------------------------------
# 6. Делегат: MobileHHClient(ACC).fetch_stats() → тот же результат.
# ---------------------------------------------------------------------------

@responses.activate
def test_mobile_client_fetch_stats_delegate(oauth_token):
    from app.hh_client_mobile import MobileHHClient

    _add_happy_path_mocks()

    result = MobileHHClient(ACC).fetch_stats()

    assert result["views"] == 18000
    assert result["views_new"] == 5
    assert result["resumes_count"] == 1
    assert result["unread_negotiations"] == 428
    assert result["streak"] == {"responses_count": 12, "responses_required": 15}
    assert result["shows"] == 0 and result["invitations"] == 0
    for key in WEB_KEYS:
        assert key in result
