import responses

from app.mobile_search import search_vacancies


ACC = {"resume_hash": "rh"}


@responses.activate
def test_search_paginates_normalises_and_sends_mobile_headers(monkeypatch):
    monkeypatch.setattr("app.oauth._obtain_oauth_token", lambda acc: "token")
    responses.get("https://api.hh.ru/vacancies", json={
        "pages": 2,
        "items": [{"id": 10, "name": "Python", "employer": {"name": "ACME"},
                   "area": {"id": "1"}, "salary": None,
                   "alternate_url": "https://hh.ru/vacancy/10"}],
    })
    responses.get("https://api.hh.ru/vacancies", json={
        "pages": 2, "items": [{"id": "11", "name": "Backend"}],
    })

    found = search_vacancies(ACC, "python", filters={"experience": "between1And3"})

    assert [v["id"] for v in found] == ["10", "11"]
    assert found[1]["url"] == "https://hh.ru/vacancy/11"
    assert len(responses.calls) == 2
    assert responses.calls[0].request.headers["Authorization"] == "Bearer token"
    assert responses.calls[0].request.headers["x-force-app-access"] == "true"
    assert "page=0" in responses.calls[0].request.url
    assert "page=1" in responses.calls[1].request.url
    assert "experience=between1And3" in responses.calls[0].request.url
    assert "area=113" in responses.calls[0].request.url


@responses.activate
def test_search_stops_after_twenty_pages(monkeypatch):
    monkeypatch.setattr("app.oauth._obtain_oauth_token", lambda acc: "token")
    for page in range(20):
        responses.get("https://api.hh.ru/vacancies", json={
            "pages": 99, "items": [{"id": str(page)}],
        })
    assert len(search_vacancies(ACC, "x")) == 20
    assert len(responses.calls) == 20


@responses.activate
def test_search_respects_configured_single_page_before_requesting_next(monkeypatch):
    monkeypatch.setattr("app.oauth._obtain_oauth_token", lambda acc: "token")
    responses.get("https://api.hh.ru/vacancies", json={
        "pages": 20, "items": [{"id": "first"}],
    })

    found = search_vacancies(ACC, "x", per_page=50, max_pages=1)

    assert [item["id"] for item in found] == ["first"]
    assert len(responses.calls) == 1
    assert "page=0" in responses.calls[0].request.url


@responses.activate
def test_resume_search_uses_android_similar_vacancies_endpoint(monkeypatch):
    monkeypatch.setattr("app.oauth._obtain_oauth_token", lambda acc: "token")
    endpoint = "https://api.hh.ru/resumes/resume%2Fid/similar_vacancies"
    responses.get(endpoint, json={
        "pages": 5,
        "items": [{"id": "136135317", "name": "Data Engineer"}],
    })

    found = search_vacancies(
        ACC, "", area_id=113, per_page=50,
        filters={"resume": "resume/id", "order_by": "publication_time"},
        max_pages=1,
    )

    assert [item["id"] for item in found] == ["136135317"]
    assert len(responses.calls) == 1
    request = responses.calls[0].request
    assert request.url.startswith(endpoint)
    assert "per_page=20" in request.url
    assert "area=113" in request.url
    assert "responses_count_enabled=true" in request.url
    assert "with_chat_info=true" in request.url
    assert "check_misleading_vacancy_alert=true" in request.url
    assert "with_skills_match=false" in request.url
    assert request.headers["x-hh-app-active"] == "true"
