"""Defense-in-depth tests for LLM detect URL encoding."""
from app.routes.llm import _detect_base_url, _is_safe_llm_base_url


def test_detect_empty_key_fallback_openai():
    url = _detect_base_url("")
    assert url == "https://api.openai.com/v1"
    assert _is_safe_llm_base_url(url) is True


def test_rejects_javascript_url():
    assert _is_safe_llm_base_url("javascript:alert(1)") is False


def test_rejects_file_url():
    assert _is_safe_llm_base_url("file:///etc/passwd") is False
