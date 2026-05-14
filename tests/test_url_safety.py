"""Тесты на _is_safe_llm_base_url (SSRF-фикс из R3) и _detect_base_url.

SSRF: /api/llm_detect раньше дёргал любой user-controlled URL → можно было
сканировать LAN/AWS metadata. Allowlist + private-IP reject.
"""
from app.routes.llm import _is_safe_llm_base_url, _detect_base_url


# ===== SSRF allowlist =====


def test_openai_https_allowed():
    assert _is_safe_llm_base_url("https://api.openai.com/v1") is True


def test_anthropic_allowed():
    assert _is_safe_llm_base_url("https://api.anthropic.com/v1") is True


def test_gemini_allowed():
    assert _is_safe_llm_base_url("https://generativelanguage.googleapis.com/v1beta/openai") is True


def test_http_rejected():
    """http (no s) — отвергаем (downgrade)"""
    assert _is_safe_llm_base_url("http://api.openai.com/v1") is False


def test_localhost_rejected():
    assert _is_safe_llm_base_url("https://localhost:8000/v1") is False
    assert _is_safe_llm_base_url("https://127.0.0.1/v1") is False


def test_aws_metadata_rejected():
    """SSRF к AWS IMDS — классика."""
    assert _is_safe_llm_base_url("https://169.254.169.254/latest/meta-data/") is False


def test_private_ip_ranges_rejected():
    assert _is_safe_llm_base_url("https://10.0.0.1/v1") is False
    assert _is_safe_llm_base_url("https://192.168.1.1/v1") is False
    assert _is_safe_llm_base_url("https://172.16.0.1/v1") is False


def test_random_external_host_rejected():
    """Даже если HTTPS — если хост не в allowlist, отвергаем."""
    assert _is_safe_llm_base_url("https://attacker.com/v1") is False


def test_malformed_url_rejected():
    assert _is_safe_llm_base_url("not a url") is False
    assert _is_safe_llm_base_url("") is False


# ===== _detect_base_url =====


def test_detect_groq():
    assert _detect_base_url("gsk_abc123") == "https://api.groq.com/openai/v1"


def test_detect_openrouter():
    assert _detect_base_url("sk-or-xyz") == "https://openrouter.ai/api/v1"


def test_detect_openai_project():
    assert _detect_base_url("sk-proj-abc") == "https://api.openai.com/v1"


def test_detect_gemini():
    """Issue #6 fix: AIza... → Google AI Studio OpenAI-compat endpoint."""
    url = _detect_base_url("AIzaSy_some_google_key")
    assert "generativelanguage.googleapis.com" in url


def test_detect_anthropic():
    assert _detect_base_url("sk-ant-abc123") == "https://api.anthropic.com/v1"


def test_detect_deepseek_short_sk():
    # sk-... < 45 chars → deepseek (eu, до openai-проектных)
    assert _detect_base_url("sk-short") == "https://api.deepseek.com"


def test_detect_fallback_openai():
    assert _detect_base_url("unknown-format-key-1234567890123456789012345678901234567890") == "https://api.openai.com/v1"
