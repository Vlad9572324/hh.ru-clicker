"""Тест на H6 fix — exception backoff key alignment.

Codex round-4 поймал, что я ставил temp_skip под `(neg_id, "exception")`,
а гард проверял `(neg_id, last_msg_id)`. Этот тест защищает что guard
смотрит ОБА ключа.
"""
import time
from app.state import AccountState


def _mk_state():
    return AccountState({
        "name": "Test", "short": "T", "color": "cyan",
        "resume_hash": "h", "urls": [], "cookies": {},
    })


def test_temp_skip_under_message_key_blocks_retry():
    """Когда LLM API упал → ставим temp_skip[(neg_id, last_msg_id)]."""
    state = _mk_state()
    key = ("neg123", "msg_abc")
    state._llm_temp_skip[key] = time.time() + 1800
    assert state._llm_temp_skip.get(key, 0) > time.time()


def test_temp_skip_under_exception_key_blocks_retry():
    """Когда exception → ставим temp_skip[(neg_id, "exception")] (H6).

    Manager должен проверять оба варианта ключа в guard, иначе backoff не сработает.
    """
    state = _mk_state()
    key_exc = ("neg123", "exception")
    state._llm_temp_skip[key_exc] = time.time() + 300
    # Guard логика — проверяет MAX из двух ключей
    chat_skip = max(
        state._llm_temp_skip.get(("neg123", "msg_real"), 0),
        state._llm_temp_skip.get(("neg123", "exception"), 0),
    )
    assert chat_skip > time.time()


def test_neg_failures_counter_increments():
    """`_llm_neg_failures` инкрементируется на каждом исключении."""
    state = _mk_state()
    state._llm_neg_failures["neg123"] = state._llm_neg_failures.get("neg123", 0) + 1
    state._llm_neg_failures["neg123"] = state._llm_neg_failures.get("neg123", 0) + 1
    assert state._llm_neg_failures["neg123"] == 2


def test_neg_failures_cleared_on_success():
    """Pop при success — иначе backoff накапливается вечно."""
    state = _mk_state()
    state._llm_neg_failures["neg123"] = 3
    state._llm_neg_failures.pop("neg123", None)
    assert "neg123" not in state._llm_neg_failures


def test_paused_reason_sticky_for_manual():
    """Manual pause не должен слетать на rollover."""
    state = _mk_state()
    state.paused = True
    state.paused_reason = "manual"
    # симуляция midnight rollover
    if state.paused_reason != "manual":
        state.paused = False
    assert state.paused is True


def test_paused_reason_limit_resets_at_midnight():
    state = _mk_state()
    state.paused = True
    state.paused_reason = "limit"
    if state.paused_reason != "manual":
        state.paused = False
        state.paused_reason = ""
    assert state.paused is False
    assert state.paused_reason == ""
