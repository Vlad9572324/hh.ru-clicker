"""Regression checks for the dynamically injected HH recommendations tab."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_recommendations_reads_top_level_state_binding():
    source = (ROOT / "static/js/features/feat5_recommendations.js").read_text(
        encoding="utf-8"
    )

    assert "typeof State !== 'undefined'" in source
    assert "var snap = appState && appState.lastSnapshot" in source


def test_recommendations_asset_cachebuster_is_current():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")

    assert 'features/feat5_recommendations.js?v=2' in html
