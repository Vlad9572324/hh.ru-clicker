"""Тесты mobile-поднятия резюме (app/mobile_touch_resume.py).

Контракт APK: POST api.hh.ru/resumes/{resume_id}/publish
?with_professional_roles=true (тела нет, 2xx = резюме поднято).
Все запросы через мок-библиотеку responses — живого HTTP нет.
"""
import pytest
import responses

from app import oauth
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError
from app.mobile_touch_resume import touch_resume

ACC = {"name": "a1", "cookies": {}, "resume_hash": "rh1"}
URL = MOBILE_BASE + "/resumes/rh1/publish"


@pytest.fixture(autouse=True)
def _clear_touch_cooldown():
    ACC.pop("_touch_retry_after_ts", None)


@responses.activate
def test_200_returns_true_and_request_contract(monkeypatch):
    """200 → (True, ...); URL /resumes/rh1/publish и query-параметр."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={}, status=200)

    ok, msg = touch_resume(ACC, "rh1")
    assert ok is True
    assert msg == "Резюме поднято (mobile)"

    req = responses.calls[0].request
    assert req.method == "POST"
    assert "/resumes/rh1/publish" in req.url
    assert "with_professional_roles=true" in req.url
    assert req.headers["Authorization"] == "Bearer t"


@responses.activate
def test_special_chars_in_resume_hash_are_encoded(monkeypatch):
    """Спецсимволы в resume_hash кодируются в URL (quote, safe="")."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, MOBILE_BASE + "/resumes/a%2Fb%20c/publish",
                  json={}, status=200)

    ok, _ = touch_resume(ACC, "a/b c")
    assert ok is True
    req = responses.calls[0].request
    assert "a%2Fb%20c" in req.url
    assert "a/b c" not in req.url


def test_empty_resume_id_returns_false_without_http():
    """Пустой resume_id → (False, ...) без HTTP-вызовов."""
    with responses.RequestsMock() as rsps:
        ok, msg = touch_resume(ACC, "")
        assert ok is False
        assert msg == "Нет resume_hash"
        assert len(rsps.calls) == 0


@responses.activate
def test_204_returns_true(monkeypatch):
    """204 (пустое тело) — тоже успех."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, status=204)

    ok, msg = touch_resume(ACC, "rh1")
    assert ok is True
    assert msg == "Резюме поднято (mobile)"


@responses.activate
def test_429_returns_false_with_cooldown_message(monkeypatch):
    """429 → (False, сообщение содержит "429") — паритет с web."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"errors": []}, status=429)

    result = touch_resume(ACC, "rh1")
    assert result["ok"] is False
    assert result["error"] == "touch_limit_active"
    assert result["next_at"] > 0


@responses.activate
def test_400_raises_not_implemented_for_web_fallback(monkeypatch):
    """400 (publish требует HHPro/заполненные поля) → NotImplementedError:
    FallbackHHClient повторит через web hh_apply.touch_resume."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"errors": []}, status=400)

    with pytest.raises(NotImplementedError):
        touch_resume(ACC, "rh1")


@responses.activate
def test_401_raises_mobile_api_error_for_fallback(monkeypatch):
    """401 — fallback-статус: MobileAPIError поднимается (не глотается)."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={"errors": []}, status=401)

    with pytest.raises(MobileAPIError) as ei:
        touch_resume(ACC, "rh1")
    assert ei.value.status_code == 401


@responses.activate
def test_500_raises_mobile_api_error_for_fallback(monkeypatch):
    """500 — fallback-статус: MobileAPIError поднимается (не глотается)."""
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, body="internal error", status=500)

    with pytest.raises(MobileAPIError) as ei:
        touch_resume(ACC, "rh1")
    assert ei.value.status_code == 500


# ── MobileHHClient.touch_resume ───────────────────────────────────────


@responses.activate
def test_client_method_uses_resume_hash_from_acc(monkeypatch):
    """Метод клиента берёт resume_hash из acc: 200 → (True, ...)."""
    from app.hh_client_mobile import MobileHHClient
    monkeypatch.setattr(oauth, "_obtain_oauth_token", lambda a: "t")
    responses.add(responses.POST, URL, json={}, status=200)

    ok, msg = MobileHHClient(ACC).touch_resume()
    assert ok is True
    assert msg == "Резюме поднято (mobile)"
    assert "/resumes/rh1/publish" in responses.calls[0].request.url


def test_client_method_without_resume_hash():
    """acc без resume_hash → (False, ...) без HTTP-вызовов."""
    from app.hh_client_mobile import MobileHHClient
    with responses.RequestsMock() as rsps:
        ok, msg = MobileHHClient({"name": "a1", "cookies": {}}).touch_resume()
        assert ok is False
        assert msg == "Нет resume_hash"
        assert len(rsps.calls) == 0
