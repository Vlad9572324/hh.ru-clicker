import json
from datetime import datetime, timedelta, timezone

from app import captcha_journal, storage


def test_journal_records_and_summarizes(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(captcha_journal, "_applies_around", lambda name, now: (2, 14))
    acc = {"short": "A", "name": "A"}
    captcha_journal.record("challenge", acc, id="c1")
    captcha_journal.save_sample(b"png-bytes", "Ab 12!")
    assert [p.name.split("_", 1)[1] for p in (tmp_path / "captcha_samples").glob("*.png")] == ["Ab-12.png"]
    captcha_journal.record("solve", acc, path="telegram", ok=True, id="c1")
    captcha_journal.record("solve", acc, path="llm", ok=False, reason="isBot", id="c1")
    lines = [json.loads(l) for l in (tmp_path / "captcha_events.jsonl").read_text().splitlines()]
    assert lines[0]["event"] == "challenge" and lines[0]["applies_1h"] == 2 and "msk_hour" in lines[0]
    s = captcha_journal.summary(7)
    assert s["challenges"] == 1 and s["median_applies_24h"] == 14
    assert s["solves_by_path"] == {"llm": {"attempts": 1, "ok": 0}, "telegram": {"attempts": 1, "ok": 1}}
    assert "Капчи за 7 дн.: 1" in captcha_journal.summary_text(7)


def test_quick_return_after_ok_solve_is_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    now = datetime.now(timezone.utc)
    rows = [("challenge", now - timedelta(minutes=30), {}), ("solve", now - timedelta(minutes=20), {"ok": True}),
            ("challenge", now - timedelta(minutes=15), {})]
    with open(tmp_path / "captcha_events.jsonl", "w") as f:
        for event, t, extra in rows:
            f.write(json.dumps({"t": t.isoformat(), "event": event, "acc": "A", **extra}) + "\n")
    assert captcha_journal.summary(7)["ok_solves_followed_by_challenge_within_10min"] == 1


def test_record_never_raises(monkeypatch):
    monkeypatch.setattr(captcha_journal, "_path", lambda: "/nonexistent-dir/x.jsonl")
    captcha_journal.record("challenge", {"short": "A"})


def test_llm_week_counts_llm_path_only(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(captcha_journal, "_week_cache", {"at": 0.0, "value": None})
    monkeypatch.setattr(captcha_journal, "_applies_around", lambda name, now: (0, 0))
    acc = {"short": "A"}
    captcha_journal.record("challenge", acc)
    captcha_journal.record("solve", acc, path="llm", ok=True)
    captcha_journal.record("challenge", acc)
    captcha_journal.record("solve", acc, path="llm", ok=False)
    captcha_journal.record("solve", acc, path="telegram", ok=True)
    assert captcha_journal.llm_week() == {"challenges": 2, "llm_attempts": 2, "llm_solved": 1}


def test_samples_keep_image_and_exact_answer_and_never_purge(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    for i in range(520):  # больше прежнего лимита 500 — ничего не удаляется
        captcha_journal.save_sample(b"png-%d" % i, "Слово Два", source="llm")
    captcha_journal.save_sample(b"bad", "кикс проклевала", kind="llm-rejected")
    folder = tmp_path / "captcha_samples"
    assert len(list(folder.glob("*.png"))) == 521      # одинаковые секунда+ответ не затирают друг друга
    labels = [json.loads(l) for l in (folder / "labels.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(labels) == 520                          # в эталон попадают только принятые
    assert labels[0]["answer"] == "Слово Два" and labels[0]["source"] == "llm"
    assert all((folder / l["file"]).exists() for l in labels)


def test_no_label_for_empty_answer_or_image(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    captcha_journal.save_sample(b"", "x")
    captcha_journal.save_sample(b"png", "   ")
    assert not (tmp_path / "captcha_samples").exists() or not list((tmp_path / "captcha_samples").iterdir())
