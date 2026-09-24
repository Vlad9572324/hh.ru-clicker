"""Important HH alerts, with account-scoped deduplication and delivery budget."""
from collections import defaultdict, deque
from datetime import datetime
from enum import Enum
from html import escape as _html_escape
import hashlib
import re
import threading
import time

from app.config import CONFIG
from app import telegram_notify


_CAT_ICONS = {
    "interview_invitation": "🗓️",
    "job_offer": "🎁",
    "hr_question": "💬",
    "account_blocked": "🚫",
    "daily_limit_reached": "📉",
}


def _h(s):
    """HTML-escape для TG parse_mode=HTML."""
    return _html_escape(str(s or ""))


def build_alert_html(category, *, acc_short="", employer="", vacancy_title="",
                     vacancy_id="", neg_id="", body="", extra_lines=()):
    """Красивый HTML-шаблон для TG-уведомления с живыми ссылками hh.ru/chat и /vacancy."""
    icon = _CAT_ICONS.get(getattr(category, "value", category), "🔔")
    label = _LABELS.get(category, str(category)) if category else "уведомление"
    lines = [f"{icon} <b>HH: {_h(label)}</b>", ""]
    if acc_short:
        lines.append(f"<b>Аккаунт:</b> {_h(acc_short)}")
    if vacancy_title:
        if vacancy_id:
            lines.append(f"<b>Вакансия:</b> <a href=\"https://hh.ru/vacancy/{_h(vacancy_id)}\">{_h(vacancy_title)}</a>")
        else:
            lines.append(f"<b>Вакансия:</b> {_h(vacancy_title)}")
    if employer:
        lines.append(f"<b>Работодатель:</b> {_h(employer)}")
    for line in extra_lines:
        if line:
            lines.append(_h(line))
    body_str = str(body or "").strip()
    if body_str:
        lines.append("")
        lines.append(f"<i>{_h(body_str[:1500])}</i>")
    if neg_id:
        lines.append("")
        lines.append(f"🔗 <a href=\"https://hh.ru/chat/{_h(neg_id)}\">Открыть чат в HH</a>")
    return "\n".join(lines)


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


def send_alert(category, dedup_key, text, *, sender=None, parse_mode=None):
    """Send an account-scoped key (kind:account:event) using existing transport.

    parse_mode='HTML' → передаётся в telegram_notify.send_once для форматирования
    с <b>/<i>/<a> tags (кликабельные ссылки на hh.ru/chat/<id> и /vacancy/<id>).
    """
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
        send_fn = sender or telegram_notify.send_once
        try:
            delivered = send_fn(dedup_key, text, parse_mode=parse_mode) if parse_mode else send_fn(dedup_key, text)
        except TypeError:
            # Sender не поддерживает parse_mode kwarg (mock-инъекции в тестах).
            delivered = send_fn(dedup_key, text)
        if delivered:
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
    icon = _CAT_ICONS.get(category.value, "🔔")
    if category == AlertCategory.account_blocked:
        body = ("Cookies протухли или OAuth недействителен. "
                "Откройте дашборд и обновите авторизацию.")
    else:
        body = "HH ограничил количество откликов на сегодня. Отклики возобновятся автоматически завтра."
    html_text = (
        f"{icon} <b>HH: {_LABELS[category]}</b>\n\n"
        f"<b>Аккаунт:</b> {_html_escape(state.short)}\n\n"
        f"<i>{_html_escape(body)}</i>"
    )
    return send_alert(category, scope_key(account_key(state), f"{category.value}:{day}"),
                      html_text, parse_mode='HTML')
