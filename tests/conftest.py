"""Pytest fixtures + sys.path setup."""
import sys
from pathlib import Path

# Чтобы `from app.* import ...` работало при `pytest` запуске из корня проекта.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


import pytest


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Перенаправляет DATA_DIR / log файл в tmp dir чтобы тесты не писали в реальный data/."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # Хитрость: монки-патчим Path("data") где он используется,
    # чтобы load/save шли в tmp вместо /home/user/clicker/hh.ru-clicker/data
    monkeypatch.chdir(tmp_path)
    yield data_dir
