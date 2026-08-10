"""Integration-тесты feat3: POST /api/account/{idx}/skills_recommend.

Мини-app только с роутером skills_recommend + responses для внешнего HH API.
bot.account_states monkeypatch'ится фейковым state (.acc={"resume_hash": ...}),
_obtain_oauth_token — фейковым токеном, чтобы не ходить в реальный OAuth-flow.
"""

import json
import types

import pytest
import responses
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.instances import bot
from app.routes import skills_recommend
from app.routes.skills_recommend import router as skills_router

PREDICT_URL = "https://api.hh.ru/skills_profile/predictions/recommended_skills/resume"
PROFILE_URL = "https://api.hh.ru/career_platform/profile"
RESUME_HASH = "abc123"


@pytest.fixture
def client(monkeypatch):
    """Мини-app с одним аккаунтом: resume_hash есть, OAuth-токен доступен."""
    app = FastAPI()
    app.include_router(skills_router)
    fake_state = types.SimpleNamespace(acc={"resume_hash": RESUME_HASH})
    monkeypatch.setattr(bot, "account_states", [fake_state])
    monkeypatch.setattr(skills_recommend, "_obtain_oauth_token", lambda acc: "test-token")
    return TestClient(app)


@responses.activate
def test_skills_recommend_success_gap(client):
    """Predict вернул 3 skills, в профиле уже есть SQL → gap без SQL."""
    responses.add(
        responses.POST, PREDICT_URL,
        json={"skills": [{"name": "Java"}, {"name": "SQL"}, {"name": "English"}]},
        status=200,
    )
    responses.add(
        responses.GET, PROFILE_URL,
        json={"skills": [{"name": "SQL"}]},
        status=200,
    )

    resp = client.post("/api/account/0/skills_recommend")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["recommended"] == ["Java", "SQL", "English"]
    assert data["have"] == ["SQL"]
    assert data["gap"] == ["Java", "English"]
    assert RESUME_HASH in data["editor_url"]
    assert data["editor_url"] == f"https://hh.ru/resume/{RESUME_HASH}"
    assert data["resume_hash"] == RESUME_HASH

    # Заголовки mobile-клиента + Bearer на predict-запросе.
    predict_call = responses.calls[0]
    assert predict_call.request.headers["Authorization"] == "Bearer test-token"
    assert predict_call.request.headers["User-Agent"] == "ru.hh.android/26.28.1"
    assert predict_call.request.headers["x-force-app-access"] == "true"


@responses.activate
def test_skills_recommend_retries_second_body_on_400(client):
    """Первый body {"resume_id"} → 400; retry с {"resumeId"} → 200. Ровно 2 вызова."""
    responses.add(responses.POST, PREDICT_URL, json={"error": "invalid field"}, status=400)
    responses.add(
        responses.POST, PREDICT_URL,
        json={"skills": [{"name": "Docker"}, {"name": "Kubernetes"}]},
        status=200,
    )
    responses.add(responses.GET, PROFILE_URL, json={"skills": []}, status=200)

    resp = client.post("/api/account/0/skills_recommend")
    assert resp.status_code == 200
    data = resp.json()
    assert data["recommended"] == ["Docker", "Kubernetes"]
    assert data["gap"] == ["Docker", "Kubernetes"]

    predict_calls = [c for c in responses.calls if PREDICT_URL in c.request.url]
    assert len(predict_calls) == 2
    first_body = json.loads(predict_calls[0].request.body)
    second_body = json.loads(predict_calls[1].request.body)
    assert first_body == {"resume_id": RESUME_HASH}
    assert second_body == {"resumeId": RESUME_HASH}


@responses.activate
def test_skills_recommend_profile_down_gap_equals_recommended(client):
    """Profile упал (500) → допустимый сбой: have=[], gap=recommended."""
    responses.add(
        responses.POST, PREDICT_URL,
        json={"skills": [{"name": "Kotlin"}, {"name": "Git"}]},
        status=200,
    )
    responses.add(responses.GET, PROFILE_URL, json={"error": "boom"}, status=500)

    resp = client.post("/api/account/0/skills_recommend")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["have"] == []
    assert data["gap"] == data["recommended"] == ["Kotlin", "Git"]


@responses.activate
def test_skills_recommend_no_resume_hash_400(client, monkeypatch):
    """У аккаунта нет resume_hash → 400 no_resume, без внешних вызовов."""
    fake_state = types.SimpleNamespace(acc={})
    monkeypatch.setattr(bot, "account_states", [fake_state])

    resp = client.post("/api/account/0/skills_recommend")
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "no_resume"
    assert len(responses.calls) == 0


@responses.activate
def test_skills_recommend_no_oauth_token_400(client, monkeypatch):
    """OAuth-токен получить не удалось → 400 no_oauth_token, без внешних вызовов."""
    monkeypatch.setattr(skills_recommend, "_obtain_oauth_token", lambda acc: "")

    resp = client.post("/api/account/0/skills_recommend")
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "no_oauth_token"
    assert len(responses.calls) == 0
