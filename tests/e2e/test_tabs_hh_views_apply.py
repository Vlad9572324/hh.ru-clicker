"""E2E-тесты табов «HH Статус», «Просмотры» и «Отклик» (ручной отклик).

Что покрывается (по фактической реализации static/js/app.js):

HH Статус (data-tab="hh")
    Эндпоинта /api/hh_status в роутере НЕТ: renderHH() рисует данные прямо
    из WS-снапшота (snap.accounts[*].hh_*), поэтому состояние задаётся через
    мутацию ui.state до ui.open().

Просмотры (data-tab="views")
    loadViews() строит шапку-счётчики и блоки аккаунтов из снапшота, затем
    loadViewHistory(idx) делает GET /api/account/{idx}/resume_views и
    дорисовывает таблицу истории + обновляет шапку из payload'а
    ({stats: {...}, history: [...]}). Payload задаётся в
    ui.data["resume_views"][idx] (conftest смотрит ключ int(idx)).

Отклик (data-tab="apply")
    applyCheck() → POST /api/apply/check {account_idx, vacancy_id, letter};
    при status="test_required" рисуется опросник и applySubmit() →
    POST /api/apply/submit {account_idx, vacancy_id, letter, answers}.
    Ответы мокаются через ui.set_response.

Во всех тестах используется ОДИН дефолтный аккаунт из conftest (idx=0):
он содержит полный набор полей для renderAll, тесты лишь точечно мутируют
нужные поля — это гарантирует чистый первичный рендер в ui.open().
"""

from playwright.sync_api import expect

# Общий таймаут для expect/ui.wait_until (мс / секунды)
T_MS = 15_000
T_S = 15.0

CHECK_BTN = '#panel-apply button[data-i18n="apply_btn_check"]'


def acc(ui):
    """Дефолтный аккаунт (idx=0) из conftest-снапшота — мутируется точечно."""
    return ui.state["accounts"][0]


def find_call(ui, method, path_suffix):
    for call in ui.calls:
        if call.get("method") == method and str(call.get("path", "")).endswith(path_suffix):
            return call
    return None


def wait_call(ui, method, path_suffix):
    """Ждёт перехваченный HTTP-вызов в ui.calls (без sleep: ui.wait_until)."""
    ui.wait_until(
        lambda: find_call(ui, method, path_suffix) is not None,
        timeout=T_S,
        message=f"не дождались {method} {path_suffix} в ui.calls",
    )
    return find_call(ui, method, path_suffix)


def set_resume_views_payload(ui, idx, payload):
    """Пейлоад ленивого GET /api/account/{idx}/resume_views."""
    ui.data.setdefault("resume_views", {})[idx] = payload


def open_apply_tab(ui):
    """Открывает таб «Отклик» с дефолтным аккаунтом, готовый к вводу вакансии."""
    acc(ui)["letter"] = ""  # авто-заполнение textarea письмом аккаунта -> пусто
    ui.open()
    page = ui.page
    page.locator('.tab[data-tab="apply"]').click()
    # applyBuildAccountSelect строит <option> из снапшота при переключении таба
    expect(page.locator("#apply-account option")).to_have_count(1, timeout=T_MS)
    page.select_option("#apply-account", "0")
    return page


# ── HH Статус ─────────────────────────────────────────────────────────────


def test_hh_status_renders_counters_invitations_offers(ui):
    """HH Статус: счётчики, дата обновления, приглашения и офферы из снапшота."""
    acc(ui).update(
        name="acc-test",
        hh_stats_updated="10.08.2026 12:00",
        hh_interviews=3,
        hh_viewed=5,
        hh_discards=2,
        hh_not_viewed=7,
        hh_unread_by_employer=1,
        hh_interviews_list=[
            {
                "text": "Ромашка — приглашение на интервью",
                "date": "12.08 14:00",
                "neg_id": "neg123",
            }
        ],
        hh_possible_offers=[
            {
                "name": "Компания X",
                "vacancyNames": ["Python Dev", "Go Dev", "QA", "Extra Vacancy"],
            }
        ],
    )
    ui.open()
    page = ui.page
    page.locator('.tab[data-tab="hh"]').click()

    content = page.locator("#hh-content")
    expect(content.locator(".hh-account-title")).to_have_text("acc-test", timeout=T_MS)

    # 4 базовых счётчика + «HR не чит.» (hh_unread_by_employer > 0)
    expect(content.locator(".hh-counter")).to_have_count(5, timeout=T_MS)
    expect(content.locator(".hh-counter-val.c-green")).to_have_text("3")
    expect(content.locator(".hh-counter-val.c-yellow")).to_have_text("5")
    expect(content.locator(".hh-counter-val.c-red")).to_have_text("2")
    expect(content.locator(".hh-counter-val.c-dim")).to_have_text("7")
    expect(content.locator(".hh-counter-val.c-blue")).to_have_text("1")
    expect(content).to_contain_text("Обновлено:")
    expect(content).to_contain_text("10.08.2026 12:00")

    # Приглашение на интервью: дата + ссылка на negotiations по neg_id
    item = content.locator(".hh-interview-item")
    expect(item).to_have_count(1)
    expect(item.locator(".hh-interview-date")).to_have_text("12.08 14:00")
    link = item.locator("a.hh-interview-text")
    expect(link).to_have_text("Ромашка — приглашение на интервью")
    expect(link).to_have_attribute("href", "https://hh.ru/applicant/negotiations/neg123")

    # Возможные офферы: показываются максимум 3 вакансии из списка
    expect(content.locator(".hh-offer-name")).to_have_text("Компания X")
    expect(content.locator(".hh-offer-vacs")).to_have_text("Python Dev, Go Dev, QA")


def test_hh_status_placeholder_when_no_stats_yet(ui):
    """HH Статус: аккаунт без hh_stats_updated показывает плейсхолдер «Нет данных»."""
    # дефолтный аккаунт: hh_stats_updated == "", hh_stats_loading == False
    acc(ui)["name"] = "acc-test"
    ui.open()
    page = ui.page
    page.locator('.tab[data-tab="hh"]').click()

    content = page.locator("#hh-content")
    expect(content.locator(".hh-account-title")).to_have_text("acc-test", timeout=T_MS)
    expect(content).to_contain_text("Нет данных")
    expect(content.locator(".hh-counter")).to_have_count(0)


# ── Просмотры резюме ──────────────────────────────────────────────────────


def test_views_tab_fetches_resume_views_and_renders_history(ui):
    """Просмотры: GET /api/account/0/resume_views и рендер таблицы истории."""
    set_resume_views_payload(
        ui,
        0,
        {
            "stats": {},
            "history": [
                {
                    "date": "09.08.2026",
                    "employer_id": "123456",
                    "name": "ООО Ромашка",
                    "vacancy": "Python Developer",
                },
                {
                    "date": "08.08.2026",
                    "employer_id": "789012",
                    "name": "Яндекс",
                    "vacancy": "Backend Engineer",
                },
            ],
        },
    )
    ui.open()
    page = ui.page
    page.locator('.tab[data-tab="views"]').click()

    # Переключение таба запускает loadViewHistory(0) → GET уходит в ui.calls
    wait_call(ui, "GET", "/api/account/0/resume_views")

    hist = page.locator("#views-hist-0")
    rows = hist.locator(".views-table tbody tr")
    expect(rows).to_have_count(2, timeout=T_MS)
    expect(rows.nth(0)).to_contain_text("09.08.2026")
    expect(rows.nth(0)).to_contain_text("ООО Ромашка")
    expect(rows.nth(0)).to_contain_text("Python Developer")
    expect(rows.nth(1)).to_contain_text("Яндекс")

    employer_link = hist.locator(".views-table a").first
    expect(employer_link).to_have_text("ООО Ромашка")
    expect(employer_link).to_have_attribute("href", "https://hh.ru/employer/123456")


def test_views_header_counters_updated_from_payload(ui):
    """Просмотры: шапка-счётчики перезаписывается из stats payload'а,
    агрегат «всего просмотров» и плейсхолдер при пустой истории."""
    set_resume_views_payload(
        ui,
        0,
        {
            "stats": {
                "views_7d": 42,
                "views_new": 7,
                "shows_7d": 15,
                "invitations_7d": 3,
                "invitations_new": 1,
                "total_all_time": 987,
                "total_new_unseen": 5,
                "graph_30d": [
                    {"date": "08.08.2026", "count": 2},
                    {"date": "09.08.2026", "count": 4},
                ],
            },
            "history": [],
        },
    )
    # В снапшоте другие значения — финальные цифры должны прийти из payload'а
    acc(ui).update(
        resume_views_7d=1,
        resume_views_new=1,
        resume_shows_7d=1,
        resume_invitations_7d=1,
        resume_invitations_new=1,
    )
    ui.open()
    page = ui.page
    page.locator('.tab[data-tab="views"]').click()

    row = page.locator("#views-stats-row")
    expect(row.locator(".views-stat-val.c-cyan")).to_have_text("42", timeout=T_MS)
    greens = row.locator(".views-stat-val.c-green")
    expect(greens.nth(0)).to_have_text("+7")  # новые просмотры
    expect(greens.nth(1)).to_have_text("+1")  # новые приглашения
    expect(row.locator(".views-stat-val[style]")).to_have_text("15")  # показы
    expect(row.locator(".views-stat-val.c-magenta")).to_have_text("3")  # приглашения

    # Агрегат за всё время из payload'а + плейсхолдер при пустой истории
    hist = page.locator("#views-hist-0")
    expect(hist).to_contain_text("всего просмотров", timeout=T_MS)
    expect(hist).to_contain_text("987")
    expect(hist).to_contain_text("+5 новых")
    expect(hist.locator("svg")).to_be_visible()  # sparkline по graph_30d
    expect(hist.locator(".views-table")).to_have_count(0)
    expect(hist).to_contain_text("Нет данных")


# ── Ручной отклик ─────────────────────────────────────────────────────────


def test_apply_check_posts_and_renders_success(ui):
    """Отклик: POST /api/apply/check с верным телом и рендер успеха."""
    ui.set_response(
        "POST",
        r"/api/apply/check",
        body={"status": "sent", "message": "Отклик отправлен"},
        status=200,
    )
    page = open_apply_tab(ui)
    page.fill("#apply-vacancy", "130334718")
    page.fill("#apply-letter", "Здравствуйте!")
    page.locator(CHECK_BTN).click()

    call = wait_call(ui, "POST", "/api/apply/check")
    assert call["json"]["account_idx"] == 0
    assert call["json"]["vacancy_id"] == "130334718"
    assert call["json"]["letter"] == "Здравствуйте!"

    result = page.locator("#apply-result")
    expect(result).to_be_visible(timeout=T_MS)
    expect(result).to_have_class("apply-result ok")
    expect(result).to_contain_text("Отклик отправлен")


def test_apply_check_test_required_questionnaire_then_submit(ui):
    """Отклик: status=test_required рисует опросник; submit шлёт answers."""
    ui.set_response(
        "POST",
        r"/api/apply/check",
        body={
            "status": "test_required",
            "message": "Нужно ответить на вопросы",
            "questions": [
                {
                    "text": "Готовы ли к переезду?",
                    "field": "q1",
                    "type": "radio",
                    "options": [
                        {"value": "yes", "label": "Да"},
                        {"value": "no", "label": "Нет"},
                    ],
                    "suggested": "yes",
                }
            ],
        },
        status=200,
    )
    ui.set_response(
        "POST",
        r"/api/apply/submit",
        body={"status": "sent", "message": "Отклик с опросом отправлен"},
        status=200,
    )
    page = open_apply_tab(ui)
    page.fill("#apply-vacancy", "12345678")
    page.locator(CHECK_BTN).click()

    # Опросник: вопрос, варианты, suggested-ответ предвыбран
    questionnaire = page.locator("#apply-questionnaire")
    expect(questionnaire).to_be_visible(timeout=T_MS)
    expect(questionnaire).to_contain_text("Опросник — 1 вопросов")
    expect(questionnaire).to_contain_text("Вопрос 1 из 1")
    expect(questionnaire).to_contain_text("Готовы ли к переезду?")
    expect(page.locator("input[name='aq_q1'][value='yes']")).to_be_checked()

    # «🚀 Откликнуться» внутри опросника → POST /api/apply/submit
    questionnaire.locator("button.apply-btn").click()

    call = wait_call(ui, "POST", "/api/apply/submit")
    assert call["json"]["account_idx"] == 0
    assert call["json"]["vacancy_id"] == "12345678"
    assert call["json"]["answers"] == {"q1": "yes"}
    assert call["json"]["letter"] == ""

    result = page.locator("#apply-result")
    expect(result).to_be_visible(timeout=T_MS)
    expect(result).to_have_class("apply-result ok")
    expect(result).to_contain_text("Отклик с опросом отправлен")


def test_apply_check_http_error_renders_error_state(ui):
    """Отклик: HTTP 500 на check → результат с классом err и «❌»."""
    ui.set_response(
        "POST",
        r"/api/apply/check",
        body={"message": "Сервер перегружен"},
        status=500,
    )
    page = open_apply_tab(ui)
    page.fill("#apply-vacancy", "99999999")
    page.locator(CHECK_BTN).click()

    result = page.locator("#apply-result")
    expect(result).to_be_visible(timeout=T_MS)
    # data.status отсутствует -> ветка «❌ {message}» с классом err
    expect(result).to_have_class("apply-result err")
    expect(result).to_contain_text("❌")
