#!/usr/bin/env python3
"""Deduplicate data/browser_sessions.json (dry-run unless --apply)."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from app.session_migration import backup_file, deduplicate_sessions, write_json_atomic

def migrate(path: Path, *, apply: bool = False) -> dict:
    sessions = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(sessions, list):
        raise ValueError("browser_sessions.json must contain a JSON list")
    merged, removed = deduplicate_sessions(sessions)
    backup = None
    if apply and removed:
        backup = backup_file(path)
        write_json_atomic(path, merged)
    return {"before": len(sessions), "after": len(merged), "removed": removed,
            "applied": bool(apply and removed), "backup": str(backup) if backup else None}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--file", type=Path, default=REPO_ROOT / "data/browser_sessions.json")
    args = parser.parse_args()
    try:
        result = migrate(args.file, apply=args.apply)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr); return 1
    mode = "applied" if result["applied"] else "dry-run"
    print(f"{mode}: {result['before']} -> {result['after']} sessions; removed={result['removed']}")
    if result["backup"]:
        print(f"backup: {result['backup']}")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
