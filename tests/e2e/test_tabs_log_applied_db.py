"""E2E: табы «Лог», «Отклики», «База» (log / applied / db).

Зоны (по static/index.html и static/js/app.js):

Лог (#panel-log):
  1. строки из state-снапшота (state["log"]) рендерятся в #log-list;
  2. фильтр по уровню — кнопки .log-level-btn[data-level=...] (logSetLevel);
  3. поиск #log-search (oninput -> renderLog) по message и по acc;
  4. live-обновление: ui.push_state() с новыми строками перерисовывает список.

Отклики (#panel-applied):
  5. ленивый GET /api/applied при открытии таба + рендер таблицы;
  6. поиск #applied-search по названию / компании / vacancy_id;
  7. чекбокс #applied-hide-empty («Только с названием») скрывает строки
     без названия и компании (row-no-title).

База (#panel-db):
  8. ленивый GET /api/vacancies при открытии таба + рендер + счётчик
     #db-count «(N из M)» + фильтр по статусу #db-status-filter.

Расхождения с ТЗ (фич в UI реально нет, проверено по app.js/index.html):
  - Автоскролла в табе «Лог» нет — scrollTop-логика есть только у
    LLM debug-бокса (renderLlmLog). Тест не заводился.
  - «Скрытия тестовых откликов» в табе «Отклики» нет — единственный
    toggle там это «Только с названием» (#applied-hide-empty); тест 7
    проверяет его. Вакансии с тестами живут в отдельном табе «Тесты»
    (вне скоупа этого файла).
"""

import re

from playwright.sync_api import expect


# ── Данные ─────────────────────────────────────────────────────────────


def _log_entry(time, acc, color, message, level="info"):
    """Формат записи лога бота (app/manager.py::_add_log)."""
    return {
        "time": time,
        "acc": acc,
        "color": color,
        "message": message,
        "level": level,
    }


LOG_ENTRIES = [
    _log_entry("10:00:01", "A1", "cyan", "Бот запущен", "success"),
    _log_entry("10:00:02", "A2", "green", "Ответ отправлен Ромашка", "info"),
    _log_entry("10:00:03", "B1", "yellow", "Лимит почти достигнут", "warning"),
    _log_entry("10:00:04", "A1", "cyan", "Ошибка сети при отклике", "error"),
]


def _base_state(log):
    """Минимальный state_update-снапшот, достаточный для renderAll."""
    return {
        "uptime_seconds": 3600,
        "paused": False,
        "accounts": [],
        "recent_responses": [],
        "log": list(log),
        "llm_log": [],
        "global_stats": {
            "total_found": 0,
            "total_sent": 0,
            "storage_total": 0,
            "storage_tests": 0,
        },
        "config": {},
    }


#_PAYLOAD GET /api/applied (форма app/storage.py::get_applied_list).
# at подобраны так, что сортировка по дате desc даёт порядок 333, 222, 111.
APPLIED_ITEMS = [
    {
        "account": "Иван (main)",
        "vacancy_id": "111",
        "url": "https://hh.ru/vacancy/111",
        "title": "Python Developer",
        "company": "Ромашка",
        "salary_from": 200000,
        "salary_to": 300000,
        "at": "2026-08-09T10:00:00",
    },
    {
        "account": "Иван (main)",
        "vacancy_id": "222",
        "url": "https://hh.ru/vacancy/222",
        "title": "QA Engineer",
        "company": "Кактус",
        "salary_from": None,
        "salary_to": None,
        "at": "2026-08-09T11:00:00",
    },
    {   # без названия и компании — попадает под row-no-title / hide-empty
        "account": "Пётр (second)",
        "vacancy_id": "333",
        "url": "https://hh.ru/vacancy/333",
        "title": "",
        "company": "",
        "salary_from": None,
        "salary_to": None,
        "at": "2026-08-09T12:00:00",
    },
]

# Payload GET /api/vacancies (форма app/storage.py::get_vacancy_db).
DB_ITEMS = [
    {
        "vacancy_id": "111",
        "url": "https://hh.ru/vacancy/111",
        "title": "Python Developer",
        "company": "Ромашка",
        "at": "2026-08-09T10:00:00",
        "is_test": False,
        "applied_by": ["Иван (main)"],
        "status": "sent",
    },
    {
        "vacancy_id": "222",
        "url": "https://hh.ru/vacancy/222",
        "title": "QA Engineer",
        "company": "Кактус",
        "at": "2026-08-09T11:00:00",
        "is_test": True,
        "applied_by": ["Иван (main)"],
        "status": "test_passed",
    },
    {
        "vacancy_id": "333",
        "url": "https://hh.ru/vacancy/333",
        "title": "Backend Go",
        "company": "Ёлка",
        "at": "2026-08-09T12:00:00",
        "is_test": True,
        "applied_by": [],
        "status": "test_pending",
    },
]


# ── Хелперы ────────────────────────────────────────────────────────────


def _open_tab(ui, name):
    """Клик по табу + ожидание, что панель стала активной."""
    ui.page.click(f'.tab[data-tab="{name}"]')
    expect(ui.page.locator(f"#panel-{name}")).to_have_class(re.compile(r"\bactive\b"))


def _get_calls(ui, path_substr):
    """GET-вызовы из ui.calls, чей path содержит path_substr (с query или без)."""
    return [
        c
        for c in ui.calls
        if c.get("method") == "GET" and path_substr in c.get("path", "")
    ]


# ── Лог ────────────────────────────────────────────────────────────────


def test_log_rows_render_from_state_snapshot(ui):
    """(1) Строки из ui.state['log'] рендерятся в #log-list с временем/аккаунтом/сообщением."""
    ui.state.update(_base_state(LOG_ENTRIES))
    ui.open()
    _open_tab(ui, "log")

    items = ui.page.locator("#log-list .log-item")
    expect(items).to_have_count(4)
    expect(ui.page.locator("#log-count")).to_have_text("4 записей")

    first = items.nth(0)
    expect(first.locator(".log-time")).to_have_text("10:00:01")
    expect(first.locator(".log-acc")).to_have_text("A1")
    expect(first.locator(".log-msg")).to_have_text("Бот запущен")
    expect(first.locator(".log-msg")).to_have_class(re.compile(r"\blog-success\b"))
    expect(items.nth(3).locator(".log-msg")).to_have_class(re.compile(r"\blog-error\b"))


def test_log_level_filter_buttons(ui):
    """(2) Кнопки уровня .log-level-btn фильтруют список и подсвечиваются active."""
    ui.state.update(_base_state(LOG_ENTRIES))
    ui.open()
    _open_tab(ui, "log")
    page = ui.page
    items = page.locator("#log-list .log-item")
    expect(items).to_have_count(4)

    page.click('.log-level-btn[data-level="error"]')
    expect(items).to_have_count(1)
    expect(items.nth(0).locator(".log-msg")).to_have_text("Ошибка сети при отклике")
    expect(page.locator('.log-level-btn[data-level="error"]')).to_have_class(
        re.compile(r"\bactive\b")
    )
    expect(page.locator("#log-count")).to_have_text("1 записей")

    page.click('.log-level-btn[data-level="warning"]')
    expect(items).to_have_count(1)
    expect(items.nth(0).locator(".log-msg")).to_have_text("Лимит почти достигнут")

    # «Все» возвращает полный список
    page.click('.log-level-btn[data-level=""]')
    expect(items).to_have_count(4)


def test_log_search_filters_by_message_and_account(ui):
    """(3) #log-search ищет подстроку (без учёта регистра) в message и в acc."""
    ui.state.update(_base_state(LOG_ENTRIES))
    ui.open()
    _open_tab(ui, "log")
    page = ui.page
    items = page.locator("#log-list .log-item")
    expect(items).to_have_count(4)

    page.fill("#log-search", "ошибк")
    expect(items).to_have_count(1)
    expect(items.nth(0).locator(".log-msg")).to_have_text("Ошибка сети при отклике")
    expect(page.locator("#log-count")).to_have_text("1 записей")

    # поиск по имени аккаунта
    page.fill("#log-search", "a2")
    expect(items).to_have_count(1)
    expect(items.nth(0).locator(".log-acc")).to_have_text("A2")

    # нет совпадений — пусто
    page.fill("#log-search", "несуществующее-слово")
    expect(items).to_have_count(0)

    # очистка поиска возвращает всё
    page.fill("#log-search", "")
    expect(items).to_have_count(4)


def test_log_live_update_via_push_state(ui):
    """(4) ui.push_state() с новыми строками перерисовывает лог без перезагрузки."""
    ui.state.update(_base_state(LOG_ENTRIES[:2]))
    ui.open()
    _open_tab(ui, "log")
    items = ui.page.locator("#log-list .log-item")
    expect(items).to_have_count(2)

    ui.state["log"] = ui.state["log"] + [
        _log_entry("10:05:00", "B1", "yellow", "Свежая строка из push_state", "success")
    ]
    ui.push_state()

    expect(items).to_have_count(3)
    expect(items.last.locator(".log-msg")).to_have_text("Свежая строка из push_state")
    expect(ui.page.locator("#log-count")).to_have_text("3 записей")


# ── Отклики ────────────────────────────────────────────────────────────


def test_applied_tab_lazy_fetch_and_render(ui):
    """(5) Клик таба -> ленивый GET /api/applied; таблица и счётчик из ui.data['applied']."""
    ui.data["applied"] = list(APPLIED_ITEMS)
    ui.open()
    page = ui.page

    # ленивость: до открытия таба запросов нет
    assert not _get_calls(ui, "/api/applied"), (
        f"GET /api/applied должен быть ленивым, но уже был: {ui.calls}"
    )

    _open_tab(ui, "applied")
    rows = page.locator("#applied-tbody tr")
    expect(rows).to_have_count(3)
    expect(page.locator("#applied-count")).to_have_text("(3)")
    assert _get_calls(ui, "/api/applied"), (
        f"после открытия таба ожидался GET /api/applied, calls={ui.calls}"
    )

    # сортировка по дате desc: самая свежая (333, без названия) сверху;
    # имя аккаунта показывается короткой частью из скобок
    expect(rows.nth(0)).to_contain_text("hh.ru/vacancy/333")
    expect(rows.nth(0)).to_contain_text("second")
    expect(rows.nth(1)).to_contain_text("QA Engineer")
    expect(rows.nth(1)).to_contain_text("Кактус")
    expect(page.locator("#applied-tbody a", has_text="Python Developer")).to_be_visible()
    # формат зарплаты: 200 000 — 300 000 (toLocaleString('ru'), пробелы допускаем любые)
    expect(rows.nth(2)).to_have_text(re.compile(r"200\s*000\s*—\s*300\s*000"))


def test_applied_search_by_title_company_and_id(ui):
    """(6) #applied-search фильтрует по названию, компании и vacancy_id."""
    ui.data["applied"] = list(APPLIED_ITEMS)
    ui.open()
    _open_tab(ui, "applied")
    page = ui.page
    rows = page.locator("#applied-tbody tr")
    expect(rows).to_have_count(3)

    page.fill("#applied-search", "python")
    expect(rows).to_have_count(1)
    expect(rows.nth(0)).to_contain_text("Python Developer")
    expect(page.locator("#applied-count")).to_have_text("(1)")

    page.fill("#applied-search", "кактус")
    expect(rows).to_have_count(1)
    expect(rows.nth(0)).to_contain_text("QA Engineer")

    page.fill("#applied-search", "333")
    expect(rows).to_have_count(1)
    expect(rows.nth(0)).to_contain_text("hh.ru/vacancy/333")

    page.fill("#applied-search", "zz-нет-такого")
    expect(rows).to_have_count(0)
    expect(page.locator("#applied-count")).to_have_text("(0)")


def test_applied_hide_empty_rows_toggle(ui):
    """(7) «Только с названием» (#applied-hide-empty) скрывает/возвращает строки без названия.

    Замена ТЗ-пункта «скрытие тестовых откликов»: в табе «Отклики» такого
    механизма нет (тестовые вакансии живут в отдельном табе «Тесты»);
    реальный hide-toggle здесь один — #applied-hide-empty.
    """
    ui.data["applied"] = list(APPLIED_ITEMS)
    ui.open()
    _open_tab(ui, "applied")
    page = ui.page
    rows = page.locator("#applied-tbody tr")
    expect(rows).to_have_count(3)
    expect(page.locator("#applied-tbody tr.row-no-title")).to_have_count(1)

    page.check("#applied-hide-empty")
    expect(rows).to_have_count(2)
    expect(page.locator("#applied-tbody tr.row-no-title")).to_have_count(0)
    expect(page.locator("#applied-count")).to_have_text("(2)")

    page.uncheck("#applied-hide-empty")
    expect(rows).to_have_count(3)
    expect(page.locator("#applied-tbody tr.row-no-title")).to_have_count(1)


# ── База ───────────────────────────────────────────────────────────────


def test_db_tab_lazy_fetch_render_and_counters(ui):
    """(8) Клик таба -> ленивый GET /api/vacancies; рендер, счётчик «(N из M)», фильтр статуса."""
    ui.data["vacancies"] = list(DB_ITEMS)
    ui.open()
    page = ui.page

    assert not _get_calls(ui, "/api/vacancies"), (
        f"GET /api/vacancies должен быть ленивым, но уже был: {ui.calls}"
    )

    _open_tab(ui, "db")
    rows = page.locator("#db-tbody tr")
    expect(rows).to_have_count(3)
    expect(page.locator("#db-count")).to_have_text("(3 из 3)")
    assert _get_calls(ui, "/api/vacancies"), (
        f"после открытия таба ожидался GET /api/vacancies, calls={ui.calls}"
    )

    # статусы из DB_STATUS: sent / test_passed / test_pending
    expect(page.locator("#db-tbody tr", has_text="Python Developer")).to_contain_text(
        "Отклик отправлен"
    )
    expect(page.locator("#db-tbody tr", has_text="QA Engineer")).to_contain_text(
        "Тест пройден"
    )
    expect(page.locator("#db-tbody tr", has_text="Backend Go")).to_contain_text(
        "Не пройден"
    )

    # фильтр по статусу сужает список и обновляет счётчик
    page.select_option("#db-status-filter", "test_pending")
    expect(rows).to_have_count(1)
    expect(rows.nth(0)).to_contain_text("Backend Go")
    expect(page.locator("#db-count")).to_have_text("(1 из 3)")

    page.select_option("#db-status-filter", "")
    expect(rows).to_have_count(3)
    expect(page.locator("#db-count")).to_have_text("(3 из 3)")
