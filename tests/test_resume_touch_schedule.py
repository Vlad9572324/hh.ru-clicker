from datetime import datetime

from app.manager import _server_next_publish_datetime


def test_server_next_publish_datetime_converts_offset_to_local_naive():
    result = _server_next_publish_datetime(
        {"next_publish_at": "2026-08-09T14:30:00+03:00"}
    )

    assert isinstance(result, datetime)
    assert result.tzinfo is None


def test_server_next_publish_datetime_handles_missing_value():
    assert _server_next_publish_datetime({}) is None
