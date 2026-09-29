"""HR text attached to a status change must be answered unless it is a rejection."""
import pytest

from app.hh_chat import _build_thread_from_chat_item
from app.hr_rejection import is_rejection


def item(text, wf_id):
    return {'id': 1, 'unreadCount': 1,
            'lastMessage': {'id': 9, 'text': text, 'participantId': 'emp',
                            'workflowTransition': {'id': wf_id}}}


@pytest.mark.parametrize('text,wf_id,needs', [
    ('Приглашаем вас на собеседование, формат онлайн', '15563505813', True),
    ('Приглашаем вас на собеседование, формат онлайн', 15563505813, True),
    ('К сожалению, сейчас мы не готовы пригласить вас', '15563505813', False),
    ('Мы ценим ваше желание работать с нами, но позиция закрыта', '1', False),
    ('Приглашаем вас на собеседование', 'DISCARD', False),
])
def test_numeric_workflow_is_real_message(text, wf_id, needs):
    thread = _build_thread_from_chat_item(item(text, wf_id), {}, 'me', '1')
    assert thread['needs_reply'] is needs


def test_rejection_detection_does_not_eat_invitations():
    assert not is_rejection('Мы ценим ваш опыт и приглашаем на интервью')
    assert is_rejection('Unfortunately we decided to move on')
