from pathlib import Path


APP_JS = Path("static/js/app.js")


def test_settings_sliders_keep_local_draft_until_snapshot_confirms():
    source = APP_JS.read_text(encoding="utf-8")

    assert "oninput=\"settingsInput('${s.key}', this)\"" in source
    assert "State.settingsDrafts.set(key, value)" in source
    assert "if (Number(snap.config[s.key]) !== draft) return" in source
    assert "State.settingsDrafts.delete(s.key)" in source
