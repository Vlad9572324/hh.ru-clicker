import inspect

from app.routes import mobile_auth


def test_sync_http_handlers_use_threadpool():
    assert "run_in_threadpool" in inspect.getsource(mobile_auth.request_code)
    assert "run_in_threadpool" in inspect.getsource(mobile_auth.verify_code)
