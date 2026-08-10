from datetime import datetime, timedelta, timezone

from app.hh_resume import _merge_oauth_publishability


def test_available_publish_sets_one_free_touch():
    result = {"free_touches": 0, "next_touch_seconds": 0}

    _merge_oauth_publishability(result, {"can_publish_or_update": True})

    assert result == {"free_touches": 1, "next_touch_seconds": 0}


def test_next_publish_at_sets_countdown():
    result = {"free_touches": 0, "next_touch_seconds": 0}
    next_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    _merge_oauth_publishability(
        result,
        {"can_publish_or_update": False, "next_publish_at": next_at.isoformat()},
    )

    assert 1700 <= result["next_touch_seconds"] <= 1800
