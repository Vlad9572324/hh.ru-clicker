"""Тесты на _safe_cast (H0b/M0a) и _truthy (M-R2a).

_safe_cast: предотвращает type-confusion в /api/raw/config — раньше
type(old)(value) падал/конвертил в неожиданное (list, dict).
_truthy: bool("false") = True раньше — сейчас строгая проверка.
"""
import pytest

from app.config import CONFIG
from app.routes.settings import _safe_cast


# ===== _safe_cast =====


def test_safe_cast_bool_from_bool():
    # llm_enabled — bool
    assert _safe_cast("llm_enabled", True) is True
    assert _safe_cast("llm_enabled", False) is False


def test_safe_cast_bool_from_string_true():
    assert _safe_cast("llm_enabled", "true") is True
    assert _safe_cast("llm_enabled", "yes") is True
    assert _safe_cast("llm_enabled", "1") is True


def test_safe_cast_bool_from_string_false():
    """Регресс: bool('false') в Python = True (непустая строка)."""
    assert _safe_cast("llm_enabled", "false") is False
    assert _safe_cast("llm_enabled", "no") is False
    assert _safe_cast("llm_enabled", "0") is False


def test_safe_cast_bool_rejects_garbage():
    with pytest.raises(ValueError):
        _safe_cast("llm_enabled", {"foo": "bar"})


def test_safe_cast_int_from_int():
    # pages_per_url — int
    assert _safe_cast("pages_per_url", 30) == 30


def test_safe_cast_int_from_string():
    assert _safe_cast("pages_per_url", "30") == 30


def test_safe_cast_int_rejects_bool():
    """bool — это int в Python, но мы хотим строгое разделение."""
    with pytest.raises(ValueError):
        _safe_cast("pages_per_url", True)


def test_safe_cast_str_from_str():
    assert _safe_cast("questionnaire_default_answer", "yes") == "yes"


def test_safe_cast_str_coerces_int():
    assert _safe_cast("questionnaire_default_answer", 42) == "42"
