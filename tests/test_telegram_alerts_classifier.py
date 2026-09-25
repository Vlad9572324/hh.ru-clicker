from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app import telegram_alerts as alerts


@pytest.mark.parametrize('body,workflow,bot,expected', [
    ('ПРИГЛАШАЕМ вас', None, True, 'interview_invitation'),
    ('Давайте созвонимся', None, False, 'interview_invitation'),
    ('', {'id': 'video_interview'}, True, 'interview_invitation'),
    ('Наш оффер', None, True, 'job_offer'),
    ('Готовы предложить позицию', None, False, 'job_offer'),
    ('', {'id': 'JOB_OFFER'}, True, 'job_offer'),
    ('Спасибо за отклик', None, False, None),
    ('Получили ваш отклик. Какой опыт?', None, False, None),
    ('Когда удобно?', None, False, 'hr_question'),
    ('Расскажите про опыт', {'id': ''}, False, 'hr_question'),
    ('Есть опыт?', {'id': 'APPLICATION_ACCEPTED'}, True, None),
    ('Есть опыт?', {'id': 'APPLICATION_ACCEPTED'}, False, None),
    ('Есть опыт?', None, True, None),
    ('Здравствуйте', None, False, None),
    # Rejections (HH шлёт через workflow INTERVIEW, но это отказ) — silence
    ('Спасибо за интерес. К сожалению, не готовы пригласить', {'id': 'INTERVIEW'}, False, None),
    ('Мы приняли решение остановить кандидатуру. Сохраним резюме.', None, False, None),
    ('Мы не готовы предложить эту вакансию', {'id': 'INTERVIEW'}, False, None),
    ('Ищем специалиста другого профиля', {'id': 'INTERVIEW'}, False, None),
    ('Unfortunately we cannot offer this position', {'id': 'INTERVIEW'}, False, None),
])
def test_classification(body, workflow, bot, expected):
    category, key, text = alerts.classify_chat_message('n1', body, workflow, bot, [{'id': 'm1'}])
    assert category == expected
    assert key
    if expected:
        assert 'n1' in text


def test_history_does_not_classify_old_invitation():
    assert alerts.classify_chat_message('n', 'Спасибо', None, False,
        [{'text': 'Приглашение', 'id': 'old'}])[0] is None


def test_account_state_daily_dedup(monkeypatch):
    sent = Mock(return_value=True)
    monkeypatch.setattr(alerts, 'send_alert', sent)
    state = SimpleNamespace(acc={'user_id': 'u1'}, short='A', cookies_expired=True,
                            paused_reason='', limit_exceeded=True)
    alerts.notify_account_state_change(state, 'account_blocked')
    assert ':u1:' in sent.call_args.args[1]
    alerts.notify_account_state_change(state, 'daily_limit_reached')
    key = sent.call_args.args[1]
    alerts.notify_account_state_change(state, 'daily_limit_reached')
    assert sent.call_args.args[1] == key
    state.cookies_expired = False
    assert alerts.notify_account_state_change(state, 'account_blocked') is False
    state.paused_reason = 'auth'
    alerts.notify_account_state_change(state, 'account_blocked')
    assert sent.call_args.args[0] == 'account_blocked'


@pytest.mark.parametrize('last,needs_reply,expected', [
    ({'text': 'Есть опыт?', 'is_bot': True}, True, None),
    ({'text': 'Есть опыт?', 'is_bot': False}, True, 'hr_question'),
    ({'text': '', 'workflow_transition': {'id': 'OFFER'}}, False, 'job_offer'),
    ({'text': '', 'workflow_transition': {'id': 'INVITATION'}}, False, 'interview_invitation'),
    ({'text': 'Спасибо за отклик', 'workflow_transition': {'id': 'APPLICATION_ACCEPTED'}}, False, None),
])
def test_manager_filters_mobile_chat(monkeypatch, last, needs_reply, expected):
    import threading
    from app import manager

    last = {**last, 'participant_id': 'hr'}
    item = {'type': 'NEGOTIATION', 'unreadCount': 1, 'messages': {'last': last}}
    client = SimpleNamespace(fetch_chat_list=Mock(return_value=({'n': item}, {}, 'applicant')))
    monkeypatch.setattr(manager, 'get_client', lambda acc: client)
    monkeypatch.setattr(manager, 'telegram_is_configured', lambda: True)
    monkeypatch.setattr(manager, '_build_thread_from_chat_item', lambda *a: {
        'needs_reply': needs_reply, 'last_employer_msg': last['text'], 'last_msg_id': 'm',
    })
    send = Mock()
    monkeypatch.setattr(manager, 'send_alert', send)
    state = SimpleNamespace(acc={}, short='A', _telegram_notify_lock=threading.Lock())
    manager.BotManager.__new__(manager.BotManager)._notify_employer_messages(state)
    if expected:
        assert send.call_args.args[0] == expected
        assert ':A:' in send.call_args.args[1]
    else:
        send.assert_not_called()
    assert not state._telegram_notify_lock.locked()
