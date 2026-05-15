"""
Questionnaire parsing and template-based answer generation.
"""

import re

from bs4 import BeautifulSoup

from app.config import CONFIG
from app.logging_utils import log_debug


def get_questionnaire_answer(question_text: str) -> str:
    """Найти подходящий шаблонный ответ по ключевым словам вопроса."""
    q_lower = question_text.lower()
    for tmpl in CONFIG.questionnaire_templates:
        keywords = tmpl.get("keywords", [])
        if not keywords:
            continue
        if any(kw.lower() in q_lower for kw in keywords):
            return tmpl["answer"]
    return CONFIG.questionnaire_default_answer


def _parse_questionnaire_fields(html: str) -> tuple:
    """
    Парсит форму опросника. Возвращает (questions, field_answers):
      questions: list of str (тексты вопросов по порядку)
      field_answers: dict {field_name: answer_value} — готовые значения для POST
    Поддерживает textarea, radio, checkbox.
    """
    # Тексты вопросов
    q_blocks = re.findall(
        r'data-qa="task-question">(.*?)(?=data-qa="task-question"|</(?:div|section|form)>)',
        html, re.DOTALL
    )
    questions = []
    for block in q_blocks:
        clean = re.sub(r'<[^>]+>', ' ', block)
        clean = re.sub(r'\s+', ' ', clean).strip()
        questions.append(clean)

    field_answers = {}

    # ── Textarea (task_*_text) ──────────────────────────────────
    for i, name in enumerate(re.findall(r'<textarea[^>]+name="(task_\d+_text)"', html)):
        q_text = questions[i] if i < len(questions) else ""
        field_answers[name] = get_questionnaire_answer(q_text)

    # ── Radio (task_*) ──────────────────────────────────────────
    # Собираем группы: {name: [(value, label), ...]}
    radio_groups: dict = {}
    for inp in re.findall(r'<input[^>]+type="radio"[^>]+>', html, re.IGNORECASE):
        name_m = re.search(r'name="([^"]+)"', inp)
        val_m  = re.search(r'value="([^"]+)"', inp)
        if name_m and val_m and re.match(r'task_\d+', name_m.group(1)):
            radio_groups.setdefault(name_m.group(1), []).append(val_m.group(1))

    # Для каждой radio-группы выбираем значение
    # Порядок radio-групп ≈ порядку вопросов после textarea
    textarea_count = len([k for k in field_answers])
    for i, (name, values) in enumerate(radio_groups.items()):
        if name in field_answers:
            continue
        q_idx = textarea_count + i
        q_text = questions[q_idx] if q_idx < len(questions) else ""
        tmpl_answer = get_questionnaire_answer(q_text).lower()

        if not values:
            continue
        chosen = values[0]  # дефолт — первый вариант

        # Ищем label-текст для каждого value чтобы сопоставить с шаблоном
        # Порядок: первый input = "да", второй = "нет" (типичная раскладка HH)
        # Если шаблон содержит "нет"/"no" — берём второй
        if any(w in tmpl_answer for w in ("нет", "no", "не готов", "не готова", "не могу")):
            chosen = values[1] if len(values) > 1 else values[0]

        field_answers[name] = chosen

    # ── Checkbox (task_*) ───────────────────────────────────────
    checkbox_groups: dict = {}
    for inp in re.findall(r'<input[^>]+type="checkbox"[^>]+>', html, re.IGNORECASE):
        name_m = re.search(r'name="([^"]+)"', inp)
        val_m  = re.search(r'value="([^"]+)"', inp)
        if name_m and val_m and re.match(r'task_\d+', name_m.group(1)):
            checkbox_groups.setdefault(name_m.group(1), []).append(val_m.group(1))

    cb_idx = len(field_answers)
    for name, values in checkbox_groups.items():
        if name in field_answers:
            continue
        q_idx = cb_idx
        cb_idx += 1
        q_text = questions[q_idx] if q_idx < len(questions) else ""
        answer = get_questionnaire_answer(q_text).lower()
        # Pick values that match keywords in the answer
        selected = [v for v in values if any(kw in v.lower() for kw in answer.split() if len(kw) > 2)]
        if not selected:
            selected = [values[0]]  # fallback to first
        field_answers[name] = selected[0]

    # ── Select (dropdown) fields ───────────────────────────────
    select_idx = cb_idx
    for m in re.finditer(r'<select[^>]+name="(task_\d+)"[^>]*>([\s\S]*?)</select>', html):
        sel_name = m.group(1)
        options_html = m.group(2)
        options = re.findall(r'<option[^>]+value="([^"]*)"[^>]*>([^<]*)</option>', options_html)
        if options and sel_name not in field_answers:
            q_text = questions[select_idx] if select_idx < len(questions) else ""
            select_idx += 1
            answer = get_questionnaire_answer(q_text).lower()
            # Pick best matching option
            best = options[0][0]  # default first
            for val, label in options:
                if any(kw in label.lower() for kw in answer.split() if len(kw) > 2):
                    best = val
                    break
            field_answers[sel_name] = best

    return questions, field_answers


def _parse_questionnaire_rich(html: str) -> list:
    """Парсит форму опросника и возвращает богатую структуру для LLM:
    list of {field, type, text, options: [{value, label}]}
    """
    soup = BeautifulSoup(html, "html.parser")

    q_blocks = soup.find_all(attrs={"data-qa": "task-question"})
    q_texts = []
    for b in q_blocks:
        c = b.get_text(separator=' ', strip=True)
        q_texts.append(c)

    result = []
    q_idx = 0

    for textarea in soup.find_all("textarea", attrs={"name": re.compile(r"task_\d+_text")}):
        name = textarea.get("name")
        result.append({"field": name, "type": "textarea",
                       "text": q_texts[q_idx] if q_idx < len(q_texts) else "", "options": []})
        q_idx += 1

    radio_groups: dict = {}      # name -> [value, ...]
    radio_value_label: dict = {}  # (name, value) -> label_text
    radio_order: list = []
    for inp in soup.find_all("input", attrs={"type": "radio", "name": re.compile(r"task_\d+")}):
        n = inp.get("name")
        v = inp.get("value")
        if not (n and v):
            continue
        if n not in radio_groups:
            radio_groups[n] = []
            radio_order.append(n)
        radio_groups[n].append(v)
        inp_id = inp.get("id")
        if inp_id:
            label = soup.find("label", attrs={"for": inp_id})
            if label:
                lbl_text = label.get_text(strip=True)
                if lbl_text:
                    radio_value_label[(n, v)] = lbl_text

    default_labels = ["да", "нет"]
    for name in radio_order:
        vals = radio_groups[name]
        options = [
            {"value": v,
             "label": radio_value_label.get((name, v), default_labels[i] if i < len(default_labels) else v)}
            for i, v in enumerate(vals)
        ]
        result.append({"field": name, "type": "radio",
                       "text": q_texts[q_idx] if q_idx < len(q_texts) else "", "options": options})
        q_idx += 1

    checkbox_groups: dict = {}
    checkbox_order: list = []
    for inp in soup.find_all("input", attrs={"type": "checkbox", "name": re.compile(r"task_\d+")}):
        n = inp.get("name")
        v = inp.get("value")
        if not (n and v):
            continue
        if n not in checkbox_groups:
            checkbox_groups[n] = []
            checkbox_order.append(n)
        checkbox_groups[n].append(v)

    for name in checkbox_order:
        vals = checkbox_groups[name]
        options = [{"value": v, "label": v} for v in vals]
        result.append({"field": name, "type": "checkbox",
                       "text": q_texts[q_idx] if q_idx < len(q_texts) else "", "options": options})
        q_idx += 1

    # Select (dropdown) fields
    for sel in soup.find_all("select", attrs={"name": re.compile(r"task_\d+")}):
        sel_name = sel.get("name")
        options = []
        for opt in sel.find_all("option"):
            val = opt.get("value", "")
            label = opt.get_text(strip=True)
            options.append({"value": val, "label": label})
        q_text = q_texts[q_idx] if q_idx < len(q_texts) else ""
        q_idx += 1
        result.append({"field": sel_name, "type": "select", "text": q_text,
                       "options": options})

    return result
