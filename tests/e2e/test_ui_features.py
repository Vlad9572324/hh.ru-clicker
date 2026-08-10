"""E2E: новые UI-фичи (subagent_7) — reviews-badge в header и секции
«🧭 Карьера» вкладки Настройки (статус поиска, верификации навыков,
анализ резюме).

Все сетевые ответы мокаются через ui.set_response ДО ui.open()
(незамоканый GET -> 404 {"error": "not mocked"}). Записи ui.calls
содержат доп. ключ 'url', поэтому сравнения/поиск идут по method+path.

Reviews badge (static/js/features/reviews_badge.js)
    Бейдж #reviews-to-rate-badge грузится лениво ПОСЛЕ первого WS-snapshot
    (поллинг State.lastSnapshot ~1с) — ждём через expect с таймаутом.
    Клик по бейджу открывает попап со списком работодателей из кэша.

Статус поиска работы (static/js/features/job_status.js, #job-status-root)
    GET /api/account/{idx}/diagnostics (форма app/routes/accounts.py:
    status / status_label / available_statuses — dict id->label) ->
    #job-status-current + options в #job-status-select.
    Клик #job-status-apply -> POST /api/account/{idx}/job_status
    {"status": "<id>"}; успех -> #job-status-result с «✅».

Навыки и верификации (static/js/features/skills.js, #skills-verifications-root)
    Автозагрузки НЕТ: клик #skills-load -> GET skill_verifications/methods
    + skill_verifications/skills; клик по .skill-verify-item
    (data-skill-id = id из verification_objects) -> GET
    /api/account/{idx}/skill_verification/{skill_id} -> #skills-modal.

Анализ резюме (static/js/features/analyze_resume.js, #analyze-resume-root)
    Клик #analyze-run -> GET /api/account/{idx}/resume_audit (mobile-форма
    ok: grade/missing_skills/...) -> рендер в #analyze-result.
"""

from playwright.sync_api import expect

T_MS = 15_000
T_S = 15.0


# ── helpers ────────────────────────────────────────────────────────────────

def find_calls(ui, method, path_sub):
    return [
        c for c in ui.calls
        if c.get("method") == method and path_sub in (c.get("path") or "")
    ]


def wait_call(ui, method, path_sub, timeout=T_S):
    ui.wait_until(
        lambda: find_calls(ui, method, path_sub),
        timeout=timeout,
        message=f"не дождались {method} {path_sub} в ui.calls",
    )
    return find_calls(ui, method, path_sub)[0]


def _open_settings(ui):
    ui.open()
    page = ui.page
    page.locator('.tab[data-tab="settings"]').click()
    expect(page.locator("#panel-settings")).to_be_visible()
    return page


def _ensure_details_open(ui, page, section_id):
    """Секция настроек — <details>; раскрываем, если ещё не открыта."""
    sec = page.locator(f"#{section_id}")
    expect(sec).to_have_count(1)
    if not sec.evaluate("e => e.open"):
        sec.locator("summary").first.click()
        ui.wait_until(
            lambda: sec.evaluate("e => e.open"),
            timeout=T_S,
            message=f"секция #{section_id} не раскрылась",
        )


def _select_account_zero(ui, page, select_id):
    """Дождаться option value=0 (фичи поллят State.lastSnapshot) и выбрать.

    Если фича уже авто-выбрала аккаунт — передёргиваем change, чтобы
    загрузка наверняка стартовала и в реализациях «только по выбору юзера».
    """
    sel = page.locator(f"#{select_id}")
    expect(sel).to_be_visible(timeout=T_MS)
    ui.wait_until(
        lambda: sel.locator('option[value="0"]').count() > 0,
        timeout=T_S,
        message=f"option value=0 не появился в #{select_id}",
    )
    if sel.evaluate("e => e.value") != "0":
        sel.select_option("0")
    else:
        sel.evaluate("e => e.dispatchEvent(new Event('change', {bubbles: true}))")
    return sel


# ── payloads (формы: контракт оркестратора + реальные routes) ────────────

REVIEWS_PAYLOAD = {
    "ok": True,
    "count": 2,
    "status": "EMPLOYERS_CAN_BE_REVIEWED",
    "items": [
        {"employer_id": 118368, "employer_name": "МТС", "position": "Инженер",
         "target": "PREVIOUS_EMPLOYER"},
        {"employer_id": 77, "employer_name": "Ромашка", "position": "Курьер",
         "target": "PREVIOUS_EMPLOYER"},
    ],
}

# GET /api/account/0/diagnostics: фактическая форма
# app/routes/accounts.py::api_account_diagnostics (status/status_label/
# available_statuses из fetch_account_diagnostics + _JOB_SEARCH_STATUSES).
# jobSearchStatus/job_search_status_label продублированы как страховка от
# альтернативных имён ключей из ТЗ.
DIAGNOSTICS_PAYLOAD = {
    "ok": True,
    "status": "active_search",
    "status_label": "🟢 Активно ищу работу",
    "jobSearchStatus": "active_search",
    "job_search_status_label": "🟢 Активно ищу работу",
    "red_flags": [],
    "stats": {},
    "resumes": [],
    "available_statuses": {
        "active_search": "🟢 Активно ищу работу",
        "looking_for_offers": "🟡 Рассматриваю предложения",
        "accept_offers": "🟡 Готова к предложениям",
        "has_job_offer": "🟠 Есть оффер",
        "accepted_job_offer": "🔵 Принят оффер",
        "not_looking_for_job": "🔴 Не ищу работу",
    },
}

JOB_STATUS_POST_OK = {
    "ok": True,
    "status": "looking_for_offers",
    "label": "🟡 Рассматриваю предложения",
}

SKILLS_METHODS_PAYLOAD = {
    "ok": True,
    "found": 1,
    "items": [
        {
            "id": 295,
            "name": "Python — средний уровень",
            "description": "Тест по основам Python",
            "platform": "KAK_DELA_QUIZ",
            "task_number": 13,
            "estimated_time": 1200,
            "availability": {"status": "AVAILABLE"},
            "verification_objects": [
                {"id": 1114, "name": "Python", "category": "SKILL",
                 "level": {"name": "Средний"}},
            ],
            "kak_dela_quiz": {
                "content": "• Функции\n• Модули",
                "task_number": 13,
                "estimated_time": 1200,
            },
        },
    ],
}

SKILLS_SKILLS_PAYLOAD = {
    "ok": True,
    "found": 1,
    "items": [
        {"id": 1114, "name": "Python", "category": "SKILL", "verified": False,
         "verified_by": "NONE", "has_report": False},
    ],
}

SKILL_SYLLABUS_PAYLOAD = {
    "ok": True,
    "id": 1114,
    "name": "Python",
    "category": "SKILL",
    "result": {"state": "NONE", "theory": "AVAILABLE"},
    "levels": [
        {
            "id": 9,
            "internal_id": "middle",
            "name": "Средний",
            "theory": {
                "id": 295,
                "name": "Python — средний уровень",
                "content": "• Функции\n• Модули",
                "task_number": 13,
                "estimated_time": 1200,
            },
        },
    ],
}

AUDIT_PAYLOAD = {
    "ok": True,
    "resume_id": "abc",
    "title": "Python-разработчик",
    "missing_skills": ["Docker"],
    "recommended_duties": ["Написание тестов"],
    "subroles": ["Backend-разработчик"],
    "grade": "MIDDLE",
    "current_score": 82,
    "partial": False,
    "errors": [],
}


# ── 1. Reviews badge ──────────────────────────────────────────────────────

def test_reviews_badge_shows_count_after_snapshot(ui):
    """Бейдж появляется (после первого WS-snapshot) и содержит счётчик «2»."""
    ui.set_response("GET", r"/api/account/0/reviews_to_rate", REVIEWS_PAYLOAD)
    ui.open()

    badge = ui.page.locator("#reviews-to-rate-badge")
    expect(badge).to_be_visible(timeout=T_MS)
    expect(badge).to_contain_text("2")
    wait_call(ui, "GET", "/api/account/0/reviews_to_rate")


def test_reviews_badge_click_opens_popup_with_employers(ui):
    """Клик по бейджу -> попап со списком работодателей (МТС, Ромашка)."""
    ui.set_response("GET", r"/api/account/0/reviews_to_rate", REVIEWS_PAYLOAD)
    ui.open()
    page = ui.page

    badge = page.locator("#reviews-to-rate-badge")
    expect(badge).to_be_visible(timeout=T_MS)
    # до клика работодатели нигде не отрисованы
    expect(page.get_by_text("МТС")).to_have_count(0)

    badge.click()

    popup = page.locator("#reviews-to-rate-popup")
    expect(popup).to_be_visible(timeout=T_MS)
    expect(popup).to_contain_text("МТС")
    expect(popup).to_contain_text("Инженер")
    expect(popup).to_contain_text("Ромашка")
    expect(popup).to_contain_text("Курьер")


# ── 2. Статус поиска работы (Настройки) ──────────────────────────────────

def test_job_status_loads_diagnostics_and_applies_new_status(ui):
    """Сценарий: выбор аккаунта -> диагностика; смена статуса -> POST -> ✅."""
    ui.set_response("GET", r"/api/account/0/diagnostics", DIAGNOSTICS_PAYLOAD)
    ui.set_response("POST", r"/api/account/0/job_status", JOB_STATUS_POST_OK)
    page = _open_settings(ui)
    _ensure_details_open(ui, page, "job-status-section")
    _select_account_zero(ui, page, "job-status-account")

    wait_call(ui, "GET", "/api/account/0/diagnostics")

    # текущий статус из диагностики
    expect(page.locator("#job-status-current")).to_contain_text(
        "Активно ищу работу", timeout=T_MS)

    # options нового статуса — все id из available_statuses
    sel = page.locator("#job-status-select")
    for status_id in DIAGNOSTICS_PAYLOAD["available_statuses"]:
        expect(sel.locator(f'option[value="{status_id}"]')).to_have_count(1)

    sel.select_option("looking_for_offers")
    page.locator("#job-status-apply").click()

    call = wait_call(ui, "POST", "/api/account/0/job_status")
    assert call["json"] == {"status": "looking_for_offers"}

    expect(page.locator("#job-status-result")).to_contain_text("✅", timeout=T_MS)
    # после успеха текущий статус обновлён на новый
    expect(page.locator("#job-status-current")).to_contain_text(
        "Рассматриваю предложения")


def test_job_status_apply_error_shows_cross(ui):
    """ok:false на POST -> «❌» + текст ошибки в #job-status-result."""
    ui.set_response("GET", r"/api/account/0/diagnostics", DIAGNOSTICS_PAYLOAD)
    ui.set_response(
        "POST", r"/api/account/0/job_status",
        {"ok": False, "error": "Аккаунт не найден"},
    )
    page = _open_settings(ui)
    _ensure_details_open(ui, page, "job-status-section")
    _select_account_zero(ui, page, "job-status-account")
    wait_call(ui, "GET", "/api/account/0/diagnostics")

    page.locator("#job-status-select").select_option("active_search")
    page.locator("#job-status-apply").click()

    wait_call(ui, "POST", "/api/account/0/job_status")
    result = page.locator("#job-status-result")
    expect(result).to_contain_text("❌", timeout=T_MS)
    expect(result).to_contain_text("Аккаунт не найден")


# ── 3. Навыки и верификации (Настройки) ──────────────────────────────────

def _skills_select_account(ui, page):
    """skills.js заполняет #skills-account при клике «Загрузить»: первый клик
    без аккаунта показывает ошибку и заполняет options из снапшота."""
    load = page.locator("#skills-load")
    expect(load).to_be_visible(timeout=T_MS)
    load.click()
    sel = page.locator("#skills-account")
    ui.wait_until(
        lambda: sel.locator('option[value="0"]').count() > 0,
        timeout=T_S,
        message="option value=0 не появился в #skills-account",
    )
    sel.select_option("0")
    return sel


def test_skills_load_lists_and_open_syllabus_modal(ui):
    """Загрузка тестов/навыков; клик по тесту -> модалка с программой."""
    ui.set_response(
        "GET", r"/api/account/0/skill_verifications/methods", SKILLS_METHODS_PAYLOAD)
    ui.set_response(
        "GET", r"/api/account/0/skill_verifications/skills", SKILLS_SKILLS_PAYLOAD)
    ui.set_response(
        "GET", r"/api/account/0/skill_verification/1114", SKILL_SYLLABUS_PAYLOAD)
    page = _open_settings(ui)
    _ensure_details_open(ui, page, "skills-section")
    _skills_select_account(ui, page)
    page.locator("#skills-load").click()

    wait_call(ui, "GET", "/api/account/0/skill_verifications/methods")
    wait_call(ui, "GET", "/api/account/0/skill_verifications/skills")

    # доступный тест: один элемент с data-skill-id из verification_objects
    item = page.locator("#skills-list .skill-verify-item")
    expect(item).to_have_count(1, timeout=T_MS)
    expect(item).to_have_attribute("data-skill-id", "1114")
    expect(item).to_contain_text("Python — средний уровень")

    # блок «Мои навыки» из skill_verifications/skills
    expect(page.locator("#skills-list")).to_contain_text("Мои навыки")
    expect(page.locator("#skills-list")).to_contain_text("Python")

    # клик по тесту -> GET skill_verification/1114 -> модалка с программой
    item.click()
    wait_call(ui, "GET", "/api/account/0/skill_verification/1114")
    modal = page.locator("#skills-modal")
    expect(modal).to_be_visible(timeout=T_MS)
    expect(modal).to_contain_text("Python")
    expect(modal).to_contain_text("Функции")
    expect(modal).to_contain_text("Модули")


def test_skills_requires_account_selected(ui):
    """Клик «Загрузить» без аккаунта: ошибка, сетевых запросов нет."""
    page = _open_settings(ui)
    _ensure_details_open(ui, page, "skills-section")
    load = page.locator("#skills-load")
    expect(load).to_be_visible(timeout=T_MS)
    load.click()

    expect(page.locator("#skills-list")).to_contain_text(
        "Сначала выберите аккаунт", timeout=T_MS)
    assert find_calls(ui, "GET", "/skill_verifications/methods") == []


# ── 4. Анализ резюме (Настройки) ─────────────────────────────────────────

def test_analyze_resume_run_renders_result(ui):
    """Клик #analyze-run -> GET resume_audit; в результате grade и скиллы."""
    ui.set_response("GET", r"/api/account/0/resume_audit", AUDIT_PAYLOAD)
    page = _open_settings(ui)
    _ensure_details_open(ui, page, "analyze-section")
    _select_account_zero(ui, page, "analyze-account")

    page.locator("#analyze-run").click()
    wait_call(ui, "GET", "/api/account/0/resume_audit")

    result = page.locator("#analyze-result")
    expect(result).to_contain_text("MIDDLE", timeout=T_MS)
    expect(result).to_contain_text("Docker")
    expect(result).to_contain_text("Python-разработчик")


def test_analyze_resume_requires_account_selected(ui):
    """Клик #analyze-run без аккаунта: ошибка, запрос не уходит."""
    page = _open_settings(ui)
    _ensure_details_open(ui, page, "analyze-section")
    run = page.locator("#analyze-run")
    expect(run).to_be_visible(timeout=T_MS)
    run.click()

    expect(page.locator("#analyze-result")).to_contain_text(
        "Сначала выберите аккаунт", timeout=T_MS)
    assert find_calls(ui, "GET", "/resume_audit") == []
