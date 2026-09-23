"""Pytest fixtures + sys.path setup."""
import sys
from pathlib import Path

# Чтобы `from app.* import ...` работало при `pytest` запуске из корня проекта.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


import pytest

# Install before test collection imports app singletons or creates log handlers.
import logging
from app import logging_utils as _test_logging
_test_logging._logger = logging.getLogger('hh_bot_tests')
_test_logging._logger.addHandler(logging.NullHandler())


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
    from app import message_quarantine, apply_quarantine
    from app import captcha
    monkeypatch.setattr(captcha, 'PATH', data_dir / 'hh_challenges.json')
    monkeypatch.setattr(message_quarantine, 'PATH', data_dir / 'message_quarantine.json')
    monkeypatch.setattr(apply_quarantine, 'PATH', data_dir / 'apply_quarantine.json')
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
    # routes/settings.py импортирует DATA_DIR по значению; без отдельного
    # патча destructive backup-wipe тест удалит настоящий data/*.json.
    try:
        from app.routes import settings as _settings
        monkeypatch.setattr(_settings, "DATA_DIR", data_dir, raising=False)
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
    # oauth.py держит СВОЮ Path-константу; без этого патча тесты OAuth-refresh
    # реально перезаписывают data/oauth_tokens.json (аудит 2026-08-17, critical).
    try:
        from app import oauth as _oauth
        if hasattr(_oauth, "_OAUTH_FILE"):
            orig = _oauth._OAUTH_FILE
            monkeypatch.setattr(_oauth, "_OAUTH_FILE",
                                data_dir / orig.name, raising=False)
    except ImportError:
        pass
    yield data_dir
    # Дождаться всех scheduled writes ДО того, как monkeypatch вернёт реальные
    # пути. Иначе callback следующего тика может попасть в production data/.
    try:
        from app.storage import _save_executor
        _save_executor.submit(lambda: None).result(timeout=10)
    except Exception:
        pass
