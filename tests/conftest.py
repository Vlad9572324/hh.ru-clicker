"""Pytest fixtures + sys.path setup."""
import sys
from pathlib import Path

# Чтобы `from app.* import ...` работало при `pytest` запуске из корня проекта.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


import pytest


@pytest.fixture(autouse=True)
def tmp_data_dir(tmp_path, monkeypatch):
    """Автоматически перенаправляет DATA_DIR / log в tmp — тесты НЕ пишут в реальный data/.

    Инцидент 2026-08-11: тесты без этой fixture перезаписали реальный
    data/interviews.json и data/config.json (сбросив llm_profiles/llm_api_key/
    questionnaire_templates). autouse=True гарантирует что впредь никакой тест
    не может дотянуться до реального data/ независимо от того, помнил ли автор
    добавить fixture в аргументы.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)  # тесты могут пересоздать сами — не падаем
    # НЕ chdir: сломало бы тесты, читающие исходники по относительным путям
    # (test_collect_page_debug_logging и др.). Патчим DATA_DIR + FILE-константы
    # in-place — этого достаточно чтобы load/save шли в tmp.
    try:
        from app import storage as _storage
        for name in ("DATA_DIR", "APPLIED_FILE", "TESTS_FILE", "INTERVIEWS_FILE",
                     "SESSIONS_FILE", "EVENTS_FILE"):
            if hasattr(_storage, name):
                orig = getattr(_storage, name)
                if name == "DATA_DIR":
                    monkeypatch.setattr(_storage, name, data_dir, raising=False)
                else:
                    monkeypatch.setattr(_storage, name, data_dir / orig.name, raising=False)
    except ImportError:
        pass
    # config.py и logging_utils тоже используют Path("data") напрямую.
    try:
        from app import config as _config
        for name in ("ACCOUNTS_FILE", "CONFIG_FILE"):
            if hasattr(_config, name):
                orig = getattr(_config, name)
                monkeypatch.setattr(_config, name, data_dir / orig.name, raising=False)
    except ImportError:
        pass
    yield data_dir
