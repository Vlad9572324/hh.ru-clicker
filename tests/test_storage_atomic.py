"""Storage writes remain usable on platforms without POSIX directory fsync."""

import json

from app import storage


def test_atomic_write_skips_directory_fsync_without_posix_flag(tmp_data_dir, monkeypatch):
    monkeypatch.delattr(storage.os, "O_DIRECTORY", raising=False)
    target = tmp_data_dir / "portable.json"

    storage._atomic_write_json(target, {"ok": True})

    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
