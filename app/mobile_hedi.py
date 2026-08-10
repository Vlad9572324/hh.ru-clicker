"""Mobile-only integration with HH AI vacancy search assistant (Hedi)."""

from app.hh_mobile_transport import mobile_request


def start_hedi(acc: dict) -> str:
    """Create or resume the account's vacancy-search assistant chat."""
    data = mobile_request(
        acc,
        "POST",
        "/applicant/ai/assistant",
        json_body={"assistantType": "vacancy_search"},
    )
    reference_id = data.get("reference_id") if isinstance(data, dict) else None
    if not reference_id:
        raise ValueError("HH AI did not return reference_id")
    return str(reference_id)
