"""Regression-тесты Phase 4: web-legacy app/hh_resume.py не сломан.

Мобильные модули Phase 4 (app/mobile_resume*.py, app/mobile_job_search_status.py)
не трогают web-legacy — проверяем поведение чистых функций hh_resume.py
БЕЗ сети: парсинг SSR, дефолтные результаты при отсутствующих данных,
защита от неизвестных статусов. Сетевые входы (HH.get/HH.put) подменены
monkeypatch'ем на падающие заглушки — любой реальный запрос уронит тест.

Плюс guard контракта: список делегирования FallbackHHClient._METHODS
содержит все 7 методов группы C и точно совпадает с абстрактным
контрактом HHClient.
"""
import json

from app import hh_client_fallback, hh_resume
from app.hh_client import HHClient

ACC_NO_HASH = {"name": "a1", "cookies": {}}  # аккаунт без resume_hash


def _no_network(*args, **kwargs):
    raise AssertionError("сетевой запрос запрещён в этом тесте")


# ---------------------------------------------------------------------------
# 1. parse_hh_lux_ssr: HTML-entity encoded JSON внутри <template>.
#    HH перевёл содержимое на &#34;-entities — функция обязана делать unescape.
# ---------------------------------------------------------------------------

def test_parse_hh_lux_ssr_entity_encoded_json():
    payload = {"applicantResume": {"title": {"string": "Тестировщик ПО"},
                                   "hash": "rh1"}}
    encoded = json.dumps(payload, ensure_ascii=False).replace('"', "&#34;")
    html = ('<html><body>'
            f'<template id="HH-Lux-InitialState">{encoded}</template>'
            '</body></html>')

    ssr = hh_resume.parse_hh_lux_ssr(html)

    assert isinstance(ssr, dict) and ssr
    assert ssr["applicantResume"]["title"]["string"] == "Тестировщик ПО"
    assert ssr["applicantResume"]["hash"] == "rh1"


# ---------------------------------------------------------------------------
# 2. _parse_resume_ssr: текст резюме из SSR-фикстуры.
# ---------------------------------------------------------------------------

RESUME_SSR = {
    "applicantResume": {
        "title": {"string": "Тестировщик ПО"},
        "firstName": {"string": "Мария"},
        "lastName": {"string": "Выучейская"},
        "keySkills": [{"string": "Python"}],
        "experience": [
            {"companyName": "Ромашка", "position": "QA",
             "startDate": "2023-01", "endDate": None},
        ],
    }
}


def test_parse_resume_ssr_fixture_text():
    text = hh_resume._parse_resume_ssr(RESUME_SSR)

    assert "Желаемая должность: Тестировщик ПО" in text
    assert "Ключевые навыки" in text
    assert "Python" in text
    assert "Опыт работы" in text
    assert "Ромашка" in text


# ---------------------------------------------------------------------------
# 3. web set_job_search_status: неизвестный статус → отказ БЕЗ сети.
# ---------------------------------------------------------------------------

def test_web_set_job_search_status_unknown_status_no_network(monkeypatch):
    monkeypatch.setattr(hh_resume.HH, "put", _no_network)

    result = hh_resume.set_job_search_status(ACC_NO_HASH, "teleport_mode")

    assert result["ok"] is False
    assert "Неизвестный статус" in result["error"]


# ---------------------------------------------------------------------------
# 4. fetch_resume_text: аккаунт без resume_hash → "" без сети.
# ---------------------------------------------------------------------------

def test_web_fetch_resume_text_no_hash_returns_empty(monkeypatch):
    monkeypatch.setattr(hh_resume.HH, "get", _no_network)

    assert hh_resume.fetch_resume_text(ACC_NO_HASH) == ""


# ---------------------------------------------------------------------------
# 5. fetch_resume_views_aggregate: без resume_hash → нулевая структура.
# ---------------------------------------------------------------------------

def test_web_fetch_resume_views_aggregate_no_hash_returns_zero(monkeypatch):
    monkeypatch.setattr(hh_resume.HH, "get", _no_network)

    result = hh_resume.fetch_resume_views_aggregate(ACC_NO_HASH)

    assert result == {"total_all_time": 0, "total_new": 0, "graph_30d": []}


# ---------------------------------------------------------------------------
# 6. fetch_resume_stats: сетевая ошибка → dict с дефолтными нулями
#    (все 9 ключей web-контракта).
# ---------------------------------------------------------------------------

EXPECTED_STATS_KEYS = {
    "views", "views_new", "shows", "invitations", "invitations_new",
    "next_touch_seconds", "free_touches", "global_invitations",
    "new_invitations_total",
}


def test_web_fetch_resume_stats_network_error_returns_defaults(monkeypatch):
    def _boom(*args, **kwargs):
        raise Exception("сеть недоступна")

    monkeypatch.setattr(hh_resume.HH, "get", _boom)

    result = hh_resume.fetch_resume_stats(ACC_NO_HASH)

    assert isinstance(result, dict)
    assert set(result.keys()) == EXPECTED_STATS_KEYS  # ровно 9 ключей
    assert all(value == 0 for value in result.values())


# ---------------------------------------------------------------------------
# 7. Guard контракта: FallbackHHClient делегирует всю группу C,
#    _METHODS синхронизирован с абстрактным контрактом HHClient.
# ---------------------------------------------------------------------------

GROUP_C_METHOD_NAMES = {
    "fetch_stats",
    "fetch_resume",
    "fetch_resume_view_history",
    "fetch_resume_views_aggregate",
    "analyze_resume",
    "edit_resume_field",
    "set_job_search_status",
}


def test_fallback_methods_include_group_c():
    assert GROUP_C_METHOD_NAMES <= set(hh_client_fallback._METHODS)


def test_fallback_methods_synced_with_hhclient_contract():
    assert set(hh_client_fallback._METHODS) == set(HHClient.__abstractmethods__)
