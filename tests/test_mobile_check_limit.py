"""Тесты mobile-версии проверки дневного лимита откликов
(app/mobile_check_limit.py) и MobileHHClient.check_limit."""
import pytest
import responses

from app import oauth
from app.hh_client_mobile import MobileHHClient
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError
from app.mobile_check_limit import check_limit

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
URL = MOBILE_BASE + "/negotiations_statistic/mine"


def _streak(count, required):
    """Payload /negotiations_statistic/mine со streak-статистикой."""
    return {"applicant_statistic": {
        "responses_streak": {"responses_count": count,
                             "responses_required": required},
    }}


def _mock(body=None, status=200, times=1, **kwargs):
    for _ in range(times):
        if body is None and status == 200 and "json" not in kwargs:
            responses.add(responses.GET, URL, body="", status=status)
        else:
            responses.add(responses.GET, URL, json=body, status=status,
                          **kwargs)


# ── app/mobile_check_limit.check_limit ─────────────────────────────────


@responses.activate
def test_200_under_limit_can_apply(monkeypatch):
    # count < required → лимит не активен; клиент возвращает False.
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    _mock(_streak(3, 5), times=2)

    assert check_limit(ACC) == {"applied_today": 3, "limit": 5,
                                "can_apply": True}
    assert MobileHHClient(ACC).check_limit() is False


@responses.activate
def test_200_over_limit_blocks(monkeypatch):
    # count > required → лимит активен; клиент возвращает True.
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    _mock(_streak(7, 5), times=2)

    assert check_limit(ACC) == {"applied_today": 7, "limit": 5,
                                "can_apply": False}
    assert MobileHHClient(ACC).check_limit() is True


@responses.activate
def test_200_count_equals_required_blocks(monkeypatch):
    # Граница: count == required → лимит уже активен.
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    _mock(_streak(5, 5))

    assert check_limit(ACC) == {"applied_today": 5, "limit": 5,
                                "can_apply": False}


@responses.activate
def test_200_zero_required_does_not_block(monkeypatch):
    # limit == 0 → не блокируем (limit > 0 обязателен для can_apply=False).
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    _mock(_streak(10, 0))

    assert check_limit(ACC) == {"applied_today": 10, "limit": 0,
                                "can_apply": True}


@responses.activate
def test_200_no_streak_all_none(monkeypatch):
    # 2xx без responses_streak → все None, не блокируем; клиент False.
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    _mock({"applicant_statistic": {}}, times=2)

    assert check_limit(ACC) == {"applied_today": None, "limit": None,
                                "can_apply": True}
    assert MobileHHClient(ACC).check_limit() is False


@responses.activate
def test_200_empty_body_can_apply(monkeypatch):
    # 2xx с пустым телом (mobile_request вернёт None) → не блокируем.
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    _mock()

    assert check_limit(ACC) == {"applied_today": None, "limit": None,
                                "can_apply": True}


@pytest.mark.parametrize("bad", ["abc", None, True])
@responses.activate
def test_garbage_values_all_none(bad, monkeypatch):
    # Мусорные значения (строки/None/bool) → None, не блокируем.
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    _mock(_streak(bad, bad))

    assert check_limit(ACC) == {"applied_today": None, "limit": None,
                                "can_apply": True}


@pytest.mark.parametrize("status", [401, 500])
@responses.activate
def test_fallback_statuses_raise(status, monkeypatch):
    # 401/5xx — fallback-статусы: MobileAPIError поднимается наверх,
    # обёртка повторит проверку через web-flow.
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    _mock({"errors": [{"value": "unauthorized"}]}, status=status)

    with pytest.raises(MobileAPIError) as ei:
        check_limit(ACC)
    assert ei.value.status_code == status


@responses.activate
def test_404_does_not_block(monkeypatch):
    # Прочие не-2xx (404) → не блокируем отклики.
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    _mock({"errors": [{"value": "not_found"}]}, status=404)

    assert check_limit(ACC) == {"applied_today": None, "limit": None,
                                "can_apply": True}


# ── MobileHHClient.check_limit ─────────────────────────────────────────


@pytest.mark.parametrize("count,required,expected", [
    (6, 5, True),    # count > required → лимит активен
    (5, 5, True),    # граница → лимит активен
    (2, 5, False),   # под лимитом → не активен
])
@responses.activate
def test_client_check_limit(count, required, expected, monkeypatch):
    # Семантика ABC: True если лимит активен (web hh_apply.check_limit).
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    _mock(_streak(count, required))

    assert MobileHHClient(ACC).check_limit() is expected
