"""Тесты mobile-модуля переговоров (app/mobile_negotiations.py).

Все HTTP через `responses` (конвенция test_hh_mobile_transport.py),
OAuth-токен — monkeypatch oauth._obtain_oauth_token. Никаких живых запросов.
"""
from datetime import datetime, timedelta

import pytest
import responses

from app import oauth
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError
from app.mobile_negotiations import fetch_negotiations

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
URL = MOBILE_BASE + "/negotiations"

# Ключи web-аналога fetch_hh_negotiations_stats — mobile обязан совпадать
WEB_KEYS = {
    "interview", "recent_interview", "viewed", "not_viewed", "discard",
    "interviews_list", "neg_ids", "discard_neg_ids", "auth_error",
    "unread_by_employer",
}


def _hh_ts(dt: datetime) -> str:
    """Формат created_at живого API hh.ru: смещение без двоеточия (+0300)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S+0300")


def _item(nid: str, state_id: str, created_at: str, **extra) -> dict:
    """Правдоподобный item официального GET /negotiations."""
    item = {
        "id": nid,
        "state": {"id": state_id, "name": state_id},
        "created_at": created_at,
        "updated_at": created_at,
        "messages_url": f"https://api.hh.ru/negotiations/{nid}/messages",
        "url": f"https://api.hh.ru/negotiations/{nid}",
        "vacancy": {"id": "134210190", "name": "Python-разработчик"},
    }
    item.update(extra)
    return item


@responses.activate
def test_single_page_counts_and_mapping(monkeypatch):
    """200, одна страница: interview/discard/response → счётчики и списки."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    now = datetime.now().astimezone()
    items = [
        _item("111", "interview", _hh_ts(now),
              viewed_by_opponent=True, has_new_messages=True),
        _item("222", "discard", _hh_ts(now - timedelta(days=5)),
              viewed_by_opponent=False, has_new_messages=False),
        # обычный отклик без viewed_by_opponent → не влияет на viewed/not_viewed
        _item("333", "response", _hh_ts(now - timedelta(days=5))),
    ]
    responses.add(responses.GET, URL, json={
        "items": items, "found": 3, "pages": 1, "page": 0,
        "per_page": 100, "has_next_page": False,
    }, status=200)

    res = fetch_negotiations(ACC)

    assert set(res.keys()) == WEB_KEYS  # совместимость с web-аналогом
    assert res["auth_error"] is False
    assert res["interview"] == 1
    assert res["recent_interview"] == 1
    assert res["discard"] == 1
    assert res["neg_ids"] == ["111", "222", "333"]
    assert res["discard_neg_ids"] == ["222"]
    assert res["viewed"] == 1
    assert res["not_viewed"] == 1
    assert res["unread_by_employer"] == 1
    assert len(res["interviews_list"]) == 1
    entry = res["interviews_list"][0]
    assert entry["neg_id"] == "111"
    assert entry["recent"] is True
    assert entry["text"] == "Python-разработчик"
    assert entry["date"] == now.strftime("%d.%m")
    # один запрос: found=3 достигнут за одну страницу
    assert len(responses.calls) == 1
    assert "per_page=100" in responses.calls[0].request.url
    assert "page=0" in responses.calls[0].request.url


@responses.activate
def test_pagination_full_then_empty_page(monkeypatch):
    """Первая страница полная (has_next), вторая пустая → остановка, склейка."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    ts = _hh_ts(datetime.now().astimezone() - timedelta(days=1))
    page0 = {
        "items": [_item("1", "response", ts), _item("2", "response", ts)],
        "found": 3, "pages": 2, "page": 0, "per_page": 2, "has_next_page": True,
    }
    page1 = {"items": [], "found": 3, "pages": 2, "page": 1,
             "per_page": 2, "has_next_page": False}
    responses.add(responses.GET, URL, json=page0, status=200)
    responses.add(responses.GET, URL, json=page1, status=200)

    res = fetch_negotiations(ACC, per_page=2)

    assert res["neg_ids"] == ["1", "2"]  # items склеены между страницами
    assert res["auth_error"] is False
    assert len(responses.calls) == 2
    assert "page=0" in responses.calls[0].request.url
    assert "page=1" in responses.calls[1].request.url


@pytest.mark.parametrize("status", [401, 403])
@responses.activate
def test_auth_error_raises_for_fallback(monkeypatch, status):
    """401/403 → MobileAPIError наружу: FallbackHHClient прозрачно
    повторяет запрос через web-flow (там и формируется auth_error)."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, URL,
                  json={"errors": [{"value": "unauthorized"}]}, status=status)

    with pytest.raises(MobileAPIError) as ei:
        fetch_negotiations(ACC)

    assert ei.value.status_code == status


@responses.activate
def test_500_raises_mobile_api_error_for_fallback(monkeypatch):
    """5xx → MobileAPIError наружу (fallback на web-flow выше по стеку)."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.GET, URL, body="server died", status=500)

    with pytest.raises(MobileAPIError) as ei:
        fetch_negotiations(ACC)
    assert ei.value.status_code == 500


@responses.activate
def test_recent_interview_60_day_window(monkeypatch):
    """created_at сегодня → recent; старше 60 дней → не в recent_interview."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    now = datetime.now().astimezone()
    items = [
        _item("10", "interview", _hh_ts(now - timedelta(days=1))),
        _item("20", "interview", _hh_ts(now - timedelta(days=90))),
    ]
    responses.add(responses.GET, URL, json={
        "items": items, "found": 2, "pages": 1, "page": 0,
        "per_page": 100, "has_next_page": False,
    }, status=200)

    res = fetch_negotiations(ACC)

    assert res["interview"] == 2
    assert res["recent_interview"] == 1  # только свежий
    flags = {e["neg_id"]: e["recent"] for e in res["interviews_list"]}
    assert flags == {"10": True, "20": False}


@responses.activate
def test_other_4xx_returns_partial_result(monkeypatch):
    """Прочие 4xx (не 401/403) → не кидает, возвращает что успел собрать."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    ts = _hh_ts(datetime.now().astimezone())
    responses.add(responses.GET, URL, json={
        "items": [_item("1", "response", ts)],
        "found": 5, "pages": 5, "page": 0, "per_page": 1, "has_next_page": True,
    }, status=200)
    responses.add(responses.GET, URL, json={"errors": [{"value": "not_found"}]},
                  status=404)

    res = fetch_negotiations(ACC, per_page=1)

    assert res["auth_error"] is False
    assert res["neg_ids"] == ["1"]  # собрано со страницы до сбоя
    assert len(responses.calls) == 2
