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


@responses.activate
def test_search_stops_after_twenty_pages(monkeypatch):
    monkeypatch.setattr("app.oauth._obtain_oauth_token", lambda acc: "token")
    for page in range(20):
        responses.get("https://api.hh.ru/vacancies", json={
            "pages": 99, "items": [{"id": str(page)}],
        })
    assert len(search_vacancies(ACC, "x")) == 20
    assert len(responses.calls) == 20
