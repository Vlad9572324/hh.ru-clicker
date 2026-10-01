import threading
import time

from app import hh_client_mobile as m


def make(calls):
    c = m.MobileHHClient.__new__(m.MobileHHClient)
    c.acc = {"user_id": "u1"}

    def fake(max_pages=5, unread_pages=20):
        calls.append((max_pages, unread_pages))
        time.sleep(0.05)
        return ({"1": {"x": 1}}, {}, "cur")
    c._fetch_chat_list_uncached = fake
    return c


def reset():
    m._CHAT_CACHE.clear()
    m._CHAT_FULL_SWEEP_AT.clear()


def test_concurrent_callers_share_one_fetch():
    reset()
    calls = []
    c = make(calls)
    out = []
    ts = [threading.Thread(target=lambda: out.append(c.fetch_chat_list(3))) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(calls) == 1 and len(out) == 4


def test_full_sweep_then_light():
    reset()
    calls = []
    c = make(calls)
    c.fetch_chat_list(3)
    m._CHAT_CACHE.clear()          # expire cache, sweep timer stays
    c.fetch_chat_list(3)
    assert calls[0][1] == 20 and calls[1][1] == 3
    m._CHAT_FULL_SWEEP_AT["u1"] -= m.CHAT_FULL_SWEEP_SEC + 1
    m._CHAT_CACHE.clear()
    c.fetch_chat_list(3)
    assert calls[2][1] == 20


def test_cached_result_is_isolated_copy():
    reset()
    c = make([])
    a = c.fetch_chat_list(3)
    a[0]["1"]["x"] = 99
    assert c.fetch_chat_list(3)[0]["1"]["x"] == 1


def test_larger_request_bypasses_smaller_cache():
    reset()
    calls = []
    c = make(calls)
    c.fetch_chat_list(3)
    c.fetch_chat_list(5)
    assert len(calls) == 2
