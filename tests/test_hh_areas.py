from app import hh_areas


def test_area_directory_maps_nested_areas_to_country(monkeypatch):
    payload = [{"id": "155", "name": "Serbia", "areas": [
        {"id": "1", "name": "Belgrade", "areas": []},
    ]}]

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    monkeypatch.setattr(hh_areas.requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(hh_areas, "_CACHE", {"expires": 0.0, "countries": [], "country_by_area": {}})

    countries, mapping = hh_areas.area_directory()

    assert countries == [{"id": "155", "name": "Serbia"}]
    assert mapping["1"] == "155"
