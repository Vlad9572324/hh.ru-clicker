"""Helpers for collapsing legacy browser sessions to one row per HH user."""
from __future__ import annotations
import copy
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

def _resumes(session: dict) -> list[dict]:
    result, seen = [], set()
    for item in session.get("all_resumes") or []:
        if not isinstance(item, dict):
            continue
        value = str(item.get("hash") or item.get("id") or "").strip()
        if value and value not in seen:
            result.append({"hash": value, "title": item.get("title", "")})
            seen.add(value)
    active = str(session.get("resume_hash") or "").strip()
    if active and active not in seen:
        result.append({"hash": active, "title": ""})
    return result

def deduplicate_sessions(sessions: list) -> tuple[list, int]:
    """Merge connected rows by user_id, resume overlap, or legacy account name."""
    rows = [copy.deepcopy(row) for row in sessions if isinstance(row, dict)]
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[b] = a
    sets = [{r["hash"] for r in _resumes(row)} for row in rows]
    for i, left in enumerate(rows):
        luid = str(left.get("user_id") or "").strip()
        lname = str(left.get("name") or "").strip().casefold()
        for j in range(i):
            right = rows[j]
            ruid = str(right.get("user_id") or "").strip()
            same_user = bool(luid and ruid and luid == ruid)
            overlap = bool(sets[i] & sets[j])
            same_legacy_name = bool(not luid and not ruid and lname and lname == str(right.get("name") or "").strip().casefold())
            if same_user or overlap or same_legacy_name:
                union(i, j)
    groups = {}
    for i in range(len(rows)):
        groups.setdefault(find(i), []).append(i)
    merged = []
    for indices in groups.values():
        target, all_resumes, seen = rows[indices[0]], [], set()
        for index in indices:
            row = rows[index]
            for resume in _resumes(row):
                if resume["hash"] not in seen:
                    all_resumes.append(resume); seen.add(resume["hash"])
            if not target.get("user_id") and row.get("user_id"):
                target["user_id"] = row["user_id"]
        target["all_resumes"] = all_resumes
        active = str(target.get("resume_hash") or "").strip()
        target["resume_hash"] = active if active in seen else (all_resumes[0]["hash"] if all_resumes else "")
        merged.append(target)
    return merged, len(rows) - len(merged)

def backup_file(path: Path, *, now: datetime | None = None) -> Path:
    now = now or datetime.now()
    directory = path.parent / "backup" / now.strftime("%Y-%m-%d")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / path.name
    if destination.exists():
        destination = directory / f"{path.stem}_{now.strftime('%H%M%S%f')}{path.suffix}"
    shutil.copy2(path, destination)
    os.chmod(destination, 0o600)
    return destination

def write_json_atomic(path: Path, value: list) -> None:
    tmp = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
