"""Regression: api_llm_profiles должна сохранять api_key когда юзер меняет
модель/base_url. type=password в форме не подставляет ключ из snap, autosave
шлёт api_key=''; backend должен подтянуть старый по name/index fallback,
иначе смена модели стирает ключ (описано в жалобе юзера)."""
import asyncio
from types import SimpleNamespace

from fastapi import Request
from app.routes import llm as llm_route
from app.config import CONFIG


class _FakeRequest:
    def __init__(self, body):
        self._body = body
    async def json(self):
        return self._body


def _save(profiles, mode="fallback"):
    return asyncio.run(llm_route.api_llm_profiles(_FakeRequest({"profiles": profiles, "mode": mode})))


def test_key_preserved_on_model_change(monkeypatch):
    """Юзер поменял model gpt-4o-mini → gpt-4o. UI шлёт api_key=''.
    Backend должен подтянуть старый ключ по name."""
    monkeypatch.setattr(CONFIG, "llm_profiles", [
        {"name": "OpenAI", "api_key": "sk-old",
         "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "enabled": True}
    ])
    monkeypatch.setattr(llm_route, "save_config", lambda: None)

    _save([{"name": "OpenAI", "api_key": "",
            "base_url": "https://api.openai.com/v1", "model": "gpt-4o", "enabled": True}])

    assert CONFIG.llm_profiles[0]["api_key"] == "sk-old"
    assert CONFIG.llm_profiles[0]["model"] == "gpt-4o"


def test_key_preserved_on_base_url_change(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_profiles", [
        {"name": "OpenAI", "api_key": "sk-old",
         "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "enabled": True}
    ])
    monkeypatch.setattr(llm_route, "save_config", lambda: None)

    _save([{"name": "OpenAI", "api_key": "",
            "base_url": "https://api.deepseek.com", "model": "gpt-4o-mini", "enabled": True}])

    assert CONFIG.llm_profiles[0]["api_key"] == "sk-old"


def test_key_can_be_explicitly_cleared_via_new_key(monkeypatch):
    """Если юзер СПЕЦИАЛЬНО ввёл новый ключ — старый заменяется."""
    monkeypatch.setattr(CONFIG, "llm_profiles", [
        {"name": "OpenAI", "api_key": "sk-old",
         "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "enabled": True}
    ])
    monkeypatch.setattr(llm_route, "save_config", lambda: None)

    _save([{"name": "OpenAI", "api_key": "sk-NEW",
            "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "enabled": True}])

    assert CONFIG.llm_profiles[0]["api_key"] == "sk-NEW"


def test_index_fallback_when_name_empty(monkeypatch):
    """Профиль без имени (легаси / пустое поле) — берём по индексу."""
    monkeypatch.setattr(CONFIG, "llm_profiles", [
        {"name": "", "api_key": "sk-idx",
         "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "enabled": True}
    ])
    monkeypatch.setattr(llm_route, "save_config", lambda: None)

    _save([{"name": "", "api_key": "",
            "base_url": "https://api.openai.com/v1", "model": "gpt-4o", "enabled": True}])

    assert CONFIG.llm_profiles[0]["api_key"] == "sk-idx"
