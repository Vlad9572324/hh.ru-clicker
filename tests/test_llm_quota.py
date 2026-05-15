"""Tests for app.llm questionnaire quota."""
import app.llm as llm_mod


def test_first_call_under_quota(monkeypatch):
    monkeypatch.setattr(llm_mod, "_questionnaire_counters", {})
    assert llm_mod._check_questionnaire_quota("acc1") is True


def test_after_100_increments_over_quota(monkeypatch):
    monkeypatch.setattr(llm_mod, "_questionnaire_counters", {})
    llm_mod._check_questionnaire_quota("acc1")  # init entry
    for _ in range(100):
        llm_mod._increment_questionnaire_quota("acc1")
    assert llm_mod._check_questionnaire_quota("acc1") is False


def test_independent_counters(monkeypatch):
    monkeypatch.setattr(llm_mod, "_questionnaire_counters", {})
    llm_mod._check_questionnaire_quota("acc1")  # init entry
    for _ in range(100):
        llm_mod._increment_questionnaire_quota("acc1")
    assert llm_mod._check_questionnaire_quota("acc2") is True
