"""Tests for _truthy behaviour via api_llm_config endpoint."""
from fastapi.testclient import TestClient
from app.routes import app
from app.config import CONFIG

client = TestClient(app)


def test_truthy_rejects_false_values():
    for v in ("false", "0", "no", "", None):
        client.post("/api/llm_config", json={"enabled": v})
        assert CONFIG.llm_enabled is False


def test_truthy_accepts_true_values():
    for v in ("true", "1", "yes", "on", True, 1, 0.5):
        client.post("/api/llm_config", json={"enabled": v})
        assert CONFIG.llm_enabled is True


def test_truthy_ignores_garbage():
    for v in ({"a": 1}, [1, 2]):
        client.post("/api/llm_config", json={"enabled": v})
        assert CONFIG.llm_enabled is False
