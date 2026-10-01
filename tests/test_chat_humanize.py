from app import chat_humanize as ch


class FakeClient:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def mark_chat_read(self, chat_id, msg_id):
        self.calls.append(("read", msg_id))
        if self.fail:
            raise RuntimeError("boom")

    def send_participant_action(self, chat_id, action):
        self.calls.append((action,))


def run(reply_len, employer_len=50, can_continue=lambda: True, fail=False):
    slept, client = [], FakeClient(fail)
    ok = ch.simulate(client, "1", 7, "x" * employer_len, "y" * reply_len,
                     sleep=slept.append, can_continue=can_continue)
    return ok, client.calls, slept


def test_order_read_before_typing_and_pulses():
    ok, calls, slept = run(200)
    assert ok
    assert calls[0] == ("read", 7)
    assert calls[1] == ("TYPING",)
    assert calls.count(("TYPING",)) >= 2  # indicator refreshed on long reply


def test_total_time_capped():
    for _ in range(50):
        _, _, slept = run(5000, 5000)
        assert sum(slept) <= ch.MAX_TOTAL_SEC + 3.0  # +mid-typing pause


def test_durations_vary():
    assert len({round(sum(run(100)[2]), 2) for _ in range(20)}) > 5


def test_abort_clears_typing_and_returns_false():
    n = {"i": 0}

    def cc():
        n["i"] += 1
        return n["i"] < 3
    ok, calls, _ = run(300, can_continue=cc)
    assert not ok
    assert calls[-1] == ("NONE",)


def test_api_errors_do_not_abort():
    ok, _, _ = run(100, fail=True)
    assert ok


class RejectingClient(FakeClient):
    def mark_chat_read(self, chat_id, msg_id):
        self.calls.append(("read", msg_id))
        return False

    def send_participant_action(self, chat_id, action):
        self.calls.append((action,))
        return False


def test_rejected_read_stops_typing_requests():
    client, slept = RejectingClient(), []
    ok = ch.simulate(client, "1", 7, "x" * 50, "y" * 300, sleep=slept.append)
    assert ok
    assert client.calls == [("read", 7)]
    assert sum(slept) > 5


def test_rejected_typing_is_sent_only_once():
    class C(FakeClient):
        def send_participant_action(self, chat_id, action):
            self.calls.append((action,))
            return False
    client = C()
    ch.simulate(client, "1", 7, "x" * 50, "y" * 300, sleep=lambda s: None)
    assert client.calls.count(("TYPING",)) == 1
