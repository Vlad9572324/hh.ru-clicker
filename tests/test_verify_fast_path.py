import inspect

from app.routes import mobile_auth


def test_collect_vacancies_is_not_in_verify_hot_path():
    source = inspect.getsource(mobile_auth._verify_code)
    assert "collect_vacancies(" not in source
    assert "vacancies_deferred" in source
