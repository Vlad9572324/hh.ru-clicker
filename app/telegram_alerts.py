"""Important HH alerts, with account-scoped deduplication and delivery budget."""
from collections import defaultdict, deque
from datetime import datetime
from enum import Enum
import hashlib
import re
import threading
import time

from app.config import CONFIG
from app import telegram_notify


class AlertCategory(str, Enum):
    interview_invitation = "interview_invitation"
    job_offer = "job_offer"
    hr_question = "hr_question"
    account_blocked = "account_blocked"
    daily_limit_reached = "daily_limit_reached"


TOGGLES = {
    AlertCategory.interview_invitation: "tg_alert_interview_enabled",
    AlertCategory.job_offer: "tg_alert_offer_enabled",
    AlertCategory.hr_question: "tg_alert_hr_question_enabled",
    AlertCategory.account_blocked: "tg_alert_account_blocked_enabled",
    AlertCategory.daily_limit_reached: "tg_alert_daily_limit_enabled",
}
_LABELS = dict(zip(AlertCategory, (
    "приглашение на интервью", "предложение работы", "вопрос HR",
    "аккаунт требует авторизации", "дневной лимит откликов достигнут",
)))
_windows = defaultdict(deque)
_lock = threading.Lock()


def classify_chat_message(neg_id, message_body, workflow, is_bot, employer_last_msg_history):
    """Return category, local event key and text; caller adds account to the key.

    History supplies the latest employer message ID, never old classification text.
    """
    body = message_body or ""
    if isinstance(body, dict):
        body = body.get("text", "")
        if isinstance(body, dict):
            body = body.get("content", "")
    body = str(body).strip()
    wf_id = workflow.get("id") if isinstance(workflow, dict) else workflow
    wf_id = str(wf_id or "").strip().upper()
    category = None
    if wf_id in {"INTERVIEW", "INVITATION", "PHONE_INTERVIEW", "VIDEO_INTERVIEW"} or re.search(r"приглаш|собеседовани|интервью|созвон|встреч", body, re.I):
        category = AlertCategory.interview_invitation
    elif wf_id in {"OFFER", "JOB_OFFER"} or re.search(r"оффер|предложение работы|job offer|готовы предложить|предлагаем позицию", body, re.I):
        category = AlertCategory.job_offer
    elif not wf_id and is_bot is False and not re.search(r"спасибо за отклик|получили ваш отклик", body, re.I) and re.search(r"\?|какая зарплата|какие ожидания|когда сможете|когда удобно|готовы|рассмотрите|уточните|расскажите|опыт|стаж", body, re.I):
        category = AlertCategory.hr_question
    history = employer_last_msg_history or []
    if isinstance(history, dict):
        history = [history]
    latest = next((m for m in reversed(history) if isinstance(m, dict) and m.get("sender", "employer") == "employer"), {})
    message_id = latest.get("msg_id") or latest.get("id") or hashlib.sha256(body.encode()).hexdigest()[:24]
    key = f"interview:{neg_id}" if category == AlertCategory.interview_invitation else f"message:{neg_id}:{message_id}"
    text = f"HH: {_LABELS[category]}\nДиалог: {neg_id}\n\n{body[:2500]}" if category else ""
    return category, key, text


def account_key(state):
    return str(state.acc.get("user_id") or state.short)


def scope_key(account, key):
    kind, rest = key.split(":", 1)
    # Keep the existing persisted event IDs, including interview IDs.
    return f"{kind}:{account}:{rest}"


def send_alert(category, dedup_key, text, *, sender=None):
    """Send an account-scoped key (kind:account:event) using existing transport."""
    category = AlertCategory(category)
    if getattr(CONFIG, TOGGLES[category]) is not True:
        return False
    account = dedup_key.split(":", 2)[1]
    with _lock:
        window = _windows[account]
        now = time.monotonic()
        while window and window[0] <= now - 3600:
            window.popleft()
        if len(window) >= 20:
            return False
        if (sender or telegram_notify.send_once)(dedup_key, text):
            window.append(time.monotonic())
            return True
    return False


def notify_account_state_change(state, kind):
    category = AlertCategory(kind)
    if category == AlertCategory.account_blocked:
        active = bool(getattr(state, "cookies_expired", False)) or getattr(state, "paused_reason", "") in {"auth", "cookies"}
    elif category == AlertCategory.daily_limit_reached:
        active = bool(getattr(state, "limit_exceeded", False))
    else:
        raise ValueError("Not an account state category")
    if not active:
        return False
    day = datetime.now().astimezone().date().isoformat()
    return send_alert(category, scope_key(account_key(state), f"{category.value}:{day}"),
                      f"HH [{state.short}]: {_LABELS[category]}")
