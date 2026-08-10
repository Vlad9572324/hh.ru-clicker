"""Route-тесты навыков и верификаций (UI full coverage).

Подход — tests/test_route_hedi.py: TestClient на общем приложении
app.routes.app, аккаунт подменяется через bot._get_apply_acc,
mobile-функции подменяются в пространстве имён роут-модуля (сам роут
тонкий: acc → executor → функция → MobileAPIError в {"ok": False}).
Никаких живых запросов: транспорт сюда даже не вызывается.
"""
import pytest
from fastapi.testclient import TestClient

import app.routes.ui_skills as route
from app.hh_mobile_transport import MobileAPIError
from app.instances import bot
from app.routes import app


def _setup(monkeypatch, acc):
    monkeypatch.setattr(bot, "_get_apply_acc",
                        lambda idx: acc if idx == 0 else None)
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Happy-path: все три эндпоинта
# ---------------------------------------------------------------------------

def test_methods_ok(monkeypatch):
    client = _setup(monkeypatch, {"mode": "mobile", "name": "test"})
    monkeypatch.setattr(route, "fetch_skill_verification_methods",
                        lambda a: {"ok": True, "found": 1,
                                   "items": [{"id": 295, "name": "Python"}]})
    response = client.get("/api/account/0/skill_verifications/methods")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["found"] == 1
    assert body["items"][0]["id"] == 295


def test_skills_ok(monkeypatch):
    client = _setup(monkeypatch, {"mode": "mobile", "name": "test"})
    monkeypatch.setattr(route, "fetch_skill_verification_skills",
                        lambda a: {"ok": True, "found": 1,
                                   "items": [{"id": 730, "name": "Linux",
                                              "verified": False}]})
    response = client.get("/api/account/0/skill_verifications/skills")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["items"][0]["name"] == "Linux"


def test_syllabus_ok_passes_skill_id(monkeypatch):
    client = _setup(monkeypatch, {"mode": "mobile", "name": "test"})
    seen = {}

    def fake_syllabus(acc, skill_id):
        seen["skill_id"] = skill_id
        return {"ok": True, "id": 1114, "name": "Python", "levels": []}

    monkeypatch.setattr(route, "fetch_verification_syllabus", fake_syllabus)

    response = client.get("/api/account/0/skill_verification/1114")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["id"] == 1114
    # skill_id из URL дошёл до mobile-функции как int
    assert seen["skill_id"] == 1114


# ---------------------------------------------------------------------------
# 2. Аккаунт не найден — все три эндпоинта
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/api/account/99/skill_verifications/methods",
    "/api/account/99/skill_verifications/skills",
    "/api/account/99/skill_verification/1114",
])
def test_account_not_found(monkeypatch, path):
    client = _setup(monkeypatch, {"mode": "mobile", "name": "test"})
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == {"ok": False, "error": "Аккаунт не найден"}


# ---------------------------------------------------------------------------
# 3. Транспорт: MobileAPIError (fallback-статус) и dict-ошибка (не-fallback)
# ---------------------------------------------------------------------------

def test_mobile_api_error_caught(monkeypatch):
    """MobileAPIError (fallback-статус) не роняет роут — {"ok": False}."""
    client = _setup(monkeypatch, {"mode": "mobile", "name": "test"})

    def boom(acc):
        raise MobileAPIError(401, payload="token_expired",
                             url="https://api.hh.ru/skill_verifications/methods")

    monkeypatch.setattr(route, "fetch_skill_verification_methods", boom)

    response = client.get("/api/account/0/skill_verifications/methods")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "HTTP 401" in body["error"]


def test_syllabus_mobile_api_error_caught(monkeypatch):
    client = _setup(monkeypatch, {"mode": "mobile", "name": "test"})

    def boom(acc, skill_id):
        raise MobileAPIError(500, payload="down",
                             url="https://api.hh.ru/verification_methods/skills/1114")

    monkeypatch.setattr(route, "fetch_verification_syllabus", boom)

    response = client.get("/api/account/0/skill_verification/1114")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "HTTP 500" in body["error"]


def test_transport_error_dict_passthrough(monkeypatch):
    """Не-fallback ошибка транспорта уже пришла dict'ом из модуля —
    роут просто транслирует её фронту."""
    client = _setup(monkeypatch, {"mode": "mobile", "name": "test"})
    monkeypatch.setattr(route, "fetch_skill_verification_skills",
                        lambda a: {"ok": False, "error": "HTTP 404"})
    response = client.get("/api/account/0/skill_verifications/skills")
    assert response.status_code == 200
    assert response.json() == {"ok": False, "error": "HTTP 404"}
