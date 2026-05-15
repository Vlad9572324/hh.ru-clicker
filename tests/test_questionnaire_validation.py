"""Tests for pure questionnaire helpers (no _coerce_questionnaire_answer found)."""
from app.questionnaire import _parse_questionnaire_rich


_HTML_TEXTAREA = (
    '<div data-qa="task-question">Q1</div>'
    '<textarea name="task_123_text"></textarea>'
)

_HTML_RADIO = (
    '<div data-qa="task-question">Q1</div>'
    '<input type="radio" name="task_456" value="yes" id="r1">'
    '<label for="r1">Yes</label>'
    '<input type="radio" name="task_456" value="no" id="r2">'
    '<label for="r2">No</label>'
)

_HTML_MIXED = (
    '<div data-qa="task-question">Text Q</div>'
    '<textarea name="task_1_text"></textarea>'
    '<div data-qa="task-question">Radio Q</div>'
    '<input type="radio" name="task_2" value="a" id="x1">'
    '<label for="x1">A</label>'
    '<input type="radio" name="task_2" value="b" id="x2">'
    '<label for="x2">B</label>'
    '<div data-qa="task-question">Check Q</div>'
    '<input type="checkbox" name="task_3" value="c1">'
    '<input type="checkbox" name="task_3" value="c2">'
    '<div data-qa="task-question">Select Q</div>'
    '<select name="task_4"><option value="s1">Opt1</option><option value="s2">Opt2</option></select>'
)


def test_empty_html_returns_empty():
    assert _parse_questionnaire_rich("") == []


def test_textarea_parsing():
    result = _parse_questionnaire_rich(_HTML_TEXTAREA)
    assert len(result) == 1
    assert result[0]["field"] == "task_123_text"
    assert result[0]["type"] == "textarea"
    assert result[0]["text"] == "Q1"


def test_radio_with_labels():
    result = _parse_questionnaire_rich(_HTML_RADIO)
    assert len(result) == 1
    assert result[0]["type"] == "radio"
    assert [o["label"] for o in result[0]["options"]] == ["Yes", "No"]


def test_mixed_fields_order():
    result = _parse_questionnaire_rich(_HTML_MIXED)
    types = [r["type"] for r in result]
    assert types == ["textarea", "radio", "checkbox", "select"]
    assert result[3]["options"][0]["value"] == "s1"
