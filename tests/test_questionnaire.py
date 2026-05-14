"""Тесты на _parse_questionnaire_rich — фикс M2.

До фикса label_map keyed by input id, lookup by value → для radio
'да/нет' могло отдать "да" вместо реальной метки.
"""
from app.questionnaire import _parse_questionnaire_rich


def test_textarea_extracted():
    html = '''
    <div data-qa="task-question">Расскажите о себе</div>
    <textarea name="task_1_text"></textarea>
    '''
    result = _parse_questionnaire_rich(html)
    assert len(result) == 1
    assert result[0]["field"] == "task_1_text"
    assert result[0]["type"] == "textarea"


def test_radio_yes_no_labels_match_values():
    """Самый частый кейс: yes/no radio."""
    html = '''
    <div data-qa="task-question">Готовы ли вы к командировкам?</div>
    <input type="radio" name="task_2" value="1" id="r_yes">
    <label for="r_yes">Да, готов</label>
    <input type="radio" name="task_2" value="0" id="r_no">
    <label for="r_no">Нет, не готов</label>
    '''
    result = _parse_questionnaire_rich(html)
    assert len(result) == 1
    q = result[0]
    assert q["type"] == "radio"
    assert q["field"] == "task_2"
    labels = {opt["value"]: opt["label"] for opt in q["options"]}
    assert labels == {"1": "Да, готов", "0": "Нет, не готов"}


def test_radio_label_with_id_different_from_value():
    """Регресс-кейс M2: input id="custom_id_X", value="actual_value".
    До фикса label_map keyed by id, options lookup by value → mismatch."""
    html = '''
    <div data-qa="task-question">Опыт в Python?</div>
    <input type="radio" name="task_5" value="junior" id="opt_a_uniq">
    <label for="opt_a_uniq">Junior (до 1 года)</label>
    <input type="radio" name="task_5" value="middle" id="opt_b_uniq">
    <label for="opt_b_uniq">Middle (1-3 года)</label>
    <input type="radio" name="task_5" value="senior" id="opt_c_uniq">
    <label for="opt_c_uniq">Senior (3+)</label>
    '''
    result = _parse_questionnaire_rich(html)
    q = next(r for r in result if r["field"] == "task_5")
    labels = {opt["value"]: opt["label"] for opt in q["options"]}
    assert labels == {
        "junior": "Junior (до 1 года)",
        "middle": "Middle (1-3 года)",
        "senior": "Senior (3+)",
    }, "Labels must align with their actual radio value, not yes/no defaults"


def test_checkbox_extracted():
    html = '''
    <div data-qa="task-question">Какие фреймворки знаете?</div>
    <input type="checkbox" name="task_3" value="django">
    <input type="checkbox" name="task_3" value="flask">
    <input type="checkbox" name="task_3" value="fastapi">
    '''
    result = _parse_questionnaire_rich(html)
    q = next(r for r in result if r["field"] == "task_3")
    assert q["type"] == "checkbox"
    values = [o["value"] for o in q["options"]]
    assert values == ["django", "flask", "fastapi"]


def test_select_extracted():
    html = '''
    <div data-qa="task-question">Гражданство?</div>
    <select name="task_4">
      <option value="RU">Российское</option>
      <option value="BY">Беларусь</option>
    </select>
    '''
    result = _parse_questionnaire_rich(html)
    q = next(r for r in result if r["field"] == "task_4")
    assert q["type"] == "select"
    labels = {o["value"]: o["label"] for o in q["options"]}
    assert labels == {"RU": "Российское", "BY": "Беларусь"}


def test_empty_html_returns_empty_list():
    assert _parse_questionnaire_rich("") == []
    assert _parse_questionnaire_rich("<div>nothing here</div>") == []
