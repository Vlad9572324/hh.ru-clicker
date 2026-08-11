from pathlib import Path


def test_all_collection_paths_log_the_page_sent_for_processing():
    manager = Path("app/manager.py").read_text(encoding="utf-8")
    mobile = Path("app/mobile_search.py").read_text(encoding="utf-8")
    fallback = Path("app/hh_api.py").read_text(encoding="utf-8")

    assert "COLLECT_PAGE start" in manager and "url={page_url}" in manager
    assert "COLLECT_PAGE start" in mobile and "page_index={current}" in mobile
    assert "COLLECT_PAGE start" in fallback and "page_index={current}" in fallback
