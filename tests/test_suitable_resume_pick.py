from app.config import CONFIG
from app import mobile_apply


def test_pick_published_resume_with_min_mismatches(monkeypatch):
    acc = {
        "resume_hash": "default",
        "all_resumes": [{"hash": "r1"}, {"hash": "r2"}, {"hash": "r3"}],
    }
    monkeypatch.setattr(CONFIG, "auto_pick_resume", True)
    monkeypatch.setattr(mobile_apply, "get_suitable_resumes", lambda acc, vacancy_id: {
        "counters": {"suitable": 3},
        "suitable": [
            {"id": "r1", "published": True, "mismatches": ["A", "B"]},
            {"id": "r2", "published": True, "mismatches": ["A"]},
            {"id": "r3", "published": False, "mismatches": []},
        ],
    })

    assert mobile_apply.pick_suitable_resume(acc, "v1") == "r2"


def test_submit_skips_when_suitable_is_empty(monkeypatch):
    acc = {"resume_hash": "r1", "all_resumes": [{"hash": "r1"}, {"hash": "r2"}]}
    monkeypatch.setattr(CONFIG, "auto_pick_resume", True)
    monkeypatch.setattr(mobile_apply, "get_suitable_resumes",
                        lambda acc, vacancy_id: {"suitable": []})
    monkeypatch.setattr(mobile_apply, "mobile_request",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("POST must not be sent")))

    result = mobile_apply.submit_response(acc, "v1", "r1")

    assert result["error_type"] == "no_suitable_resume"
