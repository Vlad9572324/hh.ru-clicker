from app.hh_client_factory import get_client
from app.hh_mobile_transport import MobileAPIError


def test_search_401_falls_back_to_web(monkeypatch):
    client = get_client({"mode": "mobile", "cookies": {}})
    monkeypatch.setattr(client.mobile, "search_vacancies", lambda *a, **k: (
        (_ for _ in ()).throw(MobileAPIError(401))))
    expected = [{"id": "web"}]
    monkeypatch.setattr(client.web, "search_vacancies", lambda *a, **k: expected)
    assert client.search_vacancies("python") is expected
