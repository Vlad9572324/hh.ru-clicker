"""Tests for app.hh_api.parse_search_page single-pass extractor."""

import pytest

try:
    from app.hh_api import (
        parse_search_page,
        parse_ids,
        parse_vacancy_meta,
        parse_salaries,
        parse_work_schedules,
    )
except ImportError as exc:
    pytest.skip(f"parse_search_page not available: {exc}", allow_module_level=True)

from app.config import CONFIG


def _reset_cache(monkeypatch):
    import app.hh_api as hh_api

    monkeypatch.setattr(hh_api, "_last_html_ref", None)
    monkeypatch.setattr(hh_api, "_last_parsed_result", None)


def test_empty_html_returns_empty_dict(monkeypatch):
    _reset_cache(monkeypatch)
    result = parse_search_page("")
    assert result == {"ids": set(), "meta": {}, "salaries": {}, "schedules": {}}


def test_html_with_two_vacancies_returns_two_ids(monkeypatch):
    _reset_cache(monkeypatch)
    html = """
    <div>
        <a href="/vacancy/11111">Job One</a>
        <a href="/vacancy/22222">Job Two</a>
    </div>
    """
    result = parse_search_page(html)
    assert result["ids"] == {"11111", "22222"}


def test_identity_cache_single_beautifulsoup_call(monkeypatch):
    import app.hh_api as hh_api
    from bs4 import BeautifulSoup

    _reset_cache(monkeypatch)

    call_count = 0
    orig_bs = BeautifulSoup

    def counting_bs(html, parser=None):
        nonlocal call_count
        call_count += 1
        return orig_bs(html, parser)

    monkeypatch.setattr(hh_api, "BeautifulSoup", counting_bs)
    monkeypatch.setattr(CONFIG, "min_salary", 1)
    monkeypatch.setattr(CONFIG, "allowed_schedules", ["remote"])

    html = """
    <a href="/vacancy/11111">Developer</a>
    <span data-qa="vacancy-serp__vacancy-employer">Corp</span>
    """
    ids = parse_ids(html)
    meta = parse_vacancy_meta(html)
    salaries = parse_salaries(html, ids)
    schedules = parse_work_schedules(html, ids)

    # Cache should ensure only one BeautifulSoup instantiation
    assert call_count == 1
    assert ids == {"11111"}
    assert "11111" in meta


def test_parse_salaries_accepts_compensation_key(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(CONFIG, "min_salary", 1)

    html = """
    <a href="/vacancy/99999">Developer</a>
    <script>
    "compensation": {"from": 150000, "currencyCode": "RUR"}
    </script>
    """
    result = parse_search_page(html)
    assert result["salaries"].get("99999") == 150000


def test_parse_salaries_accepts_salary_key(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(CONFIG, "min_salary", 1)

    html = """
    <a href="/vacancy/88888">Developer</a>
    <script>
    "salary": {"from": 200000, "currencyCode": "RUR"}
    </script>
    """
    result = parse_search_page(html)
    assert result["salaries"].get("88888") == 200000
