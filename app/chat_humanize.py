"""Human-like read/typing behaviour before an automatic chat reply.

Sequence: «reading» pause -> read receipt -> «thinking» pause -> typing
indicator pulses (refreshed, with occasional short stops) -> caller sends.
All durations scale with message lengths and carry jitter, so replies never
share one fixed delay. Total time is capped to keep the account cycle moving.
"""

import random

from app.logging_utils import log_debug

_rng = random.Random()

MAX_TOTAL_SEC = 35.0
PULSE_SEC = 3.0          # app config chat_config.participant_action_send_timeout = 3000 ms


def read_delay(employer_msg_len: int) -> float:
    """Time to «read» the incoming message before the read receipt."""
    return min(12.0, _rng.uniform(1.5, 4.0) + max(0, employer_msg_len) * 0.02)


def think_delay() -> float:
    return _rng.uniform(0.8, 2.5)


def typing_duration(reply_len: int) -> float:
    """Typing time at ~4-7 chars/sec (phone), at least 2 s."""
    cps = _rng.uniform(4.0, 7.0)
    return max(2.0, min(25.0, max(0, reply_len) / cps))


def plan(employer_msg_len: int, reply_len: int) -> tuple[float, float, float]:
    """(read, think, typing) seconds, scaled down together to fit MAX_TOTAL_SEC."""
    read, think, typing = read_delay(employer_msg_len), think_delay(), typing_duration(reply_len)
    total = read + think + typing
    if total > MAX_TOTAL_SEC:
        k = MAX_TOTAL_SEC / total
        read, think, typing = read * k, think * k, typing * k
    return read, think, typing


def simulate(client, chat_id: str, last_msg_id, employer_msg: str, reply_text: str,
             sleep, can_continue=lambda: True) -> bool:
    """Run the read/typing sequence. `sleep(sec)` is injected (interruptible).

    Returns False if `can_continue()` turned false midway (typing is cleared);
    the caller must then not send. API errors never abort the reply.
    """
    read, think, typing = plan(len(employer_msg or ""), len(reply_text or ""))

    def call(fn, *args):
        try:
            return fn(*args)
        except Exception as exc:
            log_debug(f"chat_humanize [{chat_id}]: {getattr(fn, '__name__', 'call')} failed: {exc}")
            return False

    sleep(read)
    if not can_continue():
        return False
    read_ok = call(client.mark_chat_read, chat_id, last_msg_id)
    sleep(think)
    # HH отвергает read/typing (400) в чатах, где писать нельзя: тогда не шлём
    # заведомо проваленные «печатает…», только выдерживаем паузу.
    typing_ok = read_ok is not False

    left = typing
    # Long replies: one short stop mid-way, like a person re-reading what they wrote.
    pause_at = typing * _rng.uniform(0.4, 0.7) if typing > 10 else None
    while left > 0:
        if not can_continue():
            call(client.send_participant_action, chat_id, "NONE")
            return False
        if typing_ok and call(client.send_participant_action, chat_id, "TYPING") is False:
            typing_ok = False
        step = min(left, PULSE_SEC)
        sleep(step)
        left -= step
        if pause_at is not None and typing - left >= pause_at:
            pause_at = None
            if typing_ok:
                call(client.send_participant_action, chat_id, "NONE")
            sleep(_rng.uniform(0.8, 2.0))
    return can_continue()
