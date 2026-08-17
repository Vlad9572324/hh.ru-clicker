import uuid

from app.hh_mobile_transport import mobile_headers
from app.state import AccountState
from app.user_agent import mobile_user_agent


def _account(name):
    return {"name": name, "short": name, "color": "cyan", "urls": []}


def test_two_accounts_get_distinct_stable_device_identities():
    first = _account("first")
    second = _account("second")

    first_headers = mobile_headers(first, "token")
    second_headers = mobile_headers(second, "token")

    assert first_headers["X-Device-Uuid"] != second_headers["X-Device-Uuid"]
    assert first_headers["User-Agent"] != second_headers["User-Agent"]
    assert mobile_headers(first, "token")["X-Device-Uuid"] == first_headers["X-Device-Uuid"]
    assert mobile_user_agent(first) == first_headers["User-Agent"]
    uuid.UUID(first["device_identity"]["device_uuid"])


def test_account_state_exposes_same_persistable_identity():
    acc = _account("state")
    state = AccountState(acc)

    assert state.device_identity is acc["device_identity"]
    assert state.device_identity["app_version_name"] == "26.28.1"
