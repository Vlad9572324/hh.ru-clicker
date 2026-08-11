import json

from scripts.migrate_sessions_dedup_by_user import migrate


def test_four_duplicates_become_one_and_backup(tmp_path):
    path = tmp_path / "data" / "browser_sessions.json"
    path.parent.mkdir()
    rows = []
    all_resumes = [{"hash": f"r{i}", "title": f"Title {i}"} for i in range(4)]
    for i in range(4):
        rows.append({"name": "Same User", "resume_hash": f"r{i}", "all_resumes": all_resumes,
                     "cookies": {"hhtoken": "secret"}})
    path.write_text(json.dumps(rows), encoding="utf-8")
    dry = migrate(path)
    assert dry["after"] == 1
    assert len(json.loads(path.read_text())) == 4
    result = migrate(path, apply=True)
    merged = json.loads(path.read_text())
    assert result["removed"] == 3
    assert len(merged) == 1
    assert {r["hash"] for r in merged[0]["all_resumes"]} == {"r0", "r1", "r2", "r3"}
    assert result["backup"]
