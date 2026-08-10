import responses
import pytest

from app.hh_client_mobile import MobileHHClient
from app.hh_mobile_transport import MOBILE_BASE, MobileAPIError


ACC = {"id": "test"}


@pytest.fixture(autouse=True)
def oauth_token(monkeypatch):
    monkeypatch.setattr("app.oauth._obtain_oauth_token", lambda acc: "token")


@responses.activate
def test_auto_decline_discards_uses_apk_delete_contract():
    responses.get(
        MOBILE_BASE + "/negotiations",
        json={"items": [
            {"id": "n1", "state": {"id": "discard"}, "decline_allowed": True},
            {"id": "n2", "state": {"id": "discard"}, "decline_allowed": False},
        ]},
    )
    responses.delete(MOBILE_BASE + "/negotiations/active/n1", status=204)
    assert MobileHHClient(ACC).auto_decline_discards() == 1
    delete = responses.calls[1].request
    assert delete.method == "DELETE"
    assert "with_decline_message=true" in delete.url


@responses.activate
@pytest.mark.parametrize("status", [401, 403])
def test_auto_decline_auth_errors_are_preserved_for_fallback(status):
    responses.get(MOBILE_BASE + "/negotiations", status=status, json={"error": "auth"})
    with pytest.raises(MobileAPIError) as raised:
        MobileHHClient(ACC).auto_decline_discards()
    assert raised.value.status_code == status


@responses.activate
def test_fetch_account_diagnostics_compatible_envelope():
    responses.get(MOBILE_BASE + "/me", json={
        "uuid": "u1",
        "applicant_user_statuses": {"job_search_status": {"id": "active_search"}},
        "resumes": [{"id": "r1", "title": "Python", "can_touch": True}],
    })
    responses.get(MOBILE_BASE + "/counters/user", json={"unread": 3})
    responses.get(MOBILE_BASE + "/negotiations_statistic/mine", json={
        "applicant_statistic": {"invitations": 7}
    })
    result = MobileHHClient(ACC).fetch_account_diagnostics()
    assert result["status"] == "active_search"
    assert result["resumes"][0]["hash"] == "r1"
    assert result["stats"]["user_stats"] == {"unread": 3}
    assert result["stats"]["global_invitations"] == 7
    assert result["source"] == "mobile"
    assert "uuid=u1" in responses.calls[1].request.url


@responses.activate
def test_fetch_employer_rating_web_compatible_projection():
    responses.get(MOBILE_BASE + "/employers/42", json={
        "name": "ACME", "type": "company", "open": True,
        "employees_count": "100-500",
    })
    responses.get(MOBILE_BASE + "/employers/42/reviews", json={
        "total_rating": "4.26", "reviews_count": 12,
        "recommendations_percent": 88,
        "negative_reviews_count": 2,
        "ratings": [{"id": "TEAM", "value": 4.7}],
        "advantages": [{"name": "Команда", "count": 9}],
    })
    responses.get(MOBILE_BASE + "/employers/42/reviews/conditions", json={"allowed": True})
    result = MobileHHClient(ACC).fetch_employer_rating("42")
    assert result["id"] == 42
    assert result["name"] == "ACME"
    assert result["total"] == 4.3
    assert result["recommend_pct"] == 88
    assert result["ratings"]["team"] == 4.7
    assert result["reviews_count"] == 12


def test_fetch_employer_rating_invalid_id_does_not_hit_network():
    assert MobileHHClient(ACC).fetch_employer_rating("bad") is None
