"""E2E: таб «Тесты» (.tab[data-tab="tests"]).

Что реально есть в UI (проверено по static/js/app.js и static/index.html):
- Таб read-only: loadTests() делает GET /api/tests?limit=300 и рендерит таблицу
  #tests-tbody (дата, вакансия, компания, аккаунт, отклик, ссылка) + счётчик
  #tests-count "(N)". Кнопок «Run» и статусов success/fail В ТАБЕ НЕТ —
  единственный action в панели это «↻ Обновить» (повторный loadTests).
- Единственный test-related POST в UI — чекбокс «Откликаться на вакансии с
  тестом» на карточке аккаунта (главный таб): #acc-apply-cb-{idx} →
  applyTestsToggle(idx) → POST /api/account/{idx}/apply_tests (тело пустое,
  idx передаётся в пути). Success: {"ok":true,"apply_tests":bool} → label
  #acc-apply-label-{idx} получает/теряет класс 'active'. Fail (!ok или
  ошибка сети): чекбокс откатывается (cb.checked = !cb.checked).

Поэтому сценарии «Run-кнопка» и «success/fail» из ТЗ заменены тестами
этого чекбокса (единственная реальная фича). Пустой список: отдельного
empty-state-элемента нет — пустота видна через #tests-count "(0)" и 0 строк.
"""

import re

from playwright.sync_api import expect


TESTS_API_PATH = "/api/tests"
APPLY_TESTS_API = "/api/account/0/apply_tests"


def _test_item(vacancy_id, title, company, **extra):
    item = {
        "vacancy_id": vacancy_id,
        "url": f"https://hh.ru/vacancy/{vacancy_id}",
        "title": title,
        "company": company,
        "account_name": "Основной (Иван)",
        "resume_hash": "hash" + vacancy_id,
        "applied_by": [],
        "at": "2026-08-09T12:00:00",
    }
    item.update(extra)
    return item


def _set_single_account(ui, apply_tests):
    ui.state["accounts"] = [
        {
            "idx": 0,
            "name": "Основной (Иван)",
            "short": "Иван",
            "color": "yellow",
            "status": "idle",
            "apply_tests": apply_tests,
            "degraded_fallback_enabled": True,
            "resume_touch_enabled": False,
            "use_oauth": False,
            "temp": False,
            "bot_active": False,
            "daily_sent": 0,
            "hh_interviews": 0,
            "cookies_expired": False,
        }
    ]


def _open_tests_tab(ui):
    ui.page.click('.tab[data-tab="tests"]')
    expect(ui.page.locator("#panel-tests")).to_have_class(re.compile(r"\bactive\b"))


def _calls(ui, method, path_sub):
    return [
        c
        for c in ui.calls
        if c.get("method") == method and path_sub in (c.get("path") or "")
    ]


def test_tab_click_fetches_and_renders_tests_list(ui):
    """Клик таба → GET /api/tests?limit=300 + строки из ui.data["tests"]."""
    ui.data["tests"] = [
        _test_item("111111", "Python-разработчик", "Ромашка",
                   applied_by=["Основной (Иван)"]),
        _test_item("222222", "QA-инженер", "Литех",
                   account_name="", resume_hash="", at="2026-08-08T09:30:00"),
    ]
    ui.open()
    _open_tests_tab(ui)

    rows = ui.page.locator("#tests-tbody tr")
    expect(rows).to_have_count(2)
    expect(rows.nth(0)).to_contain_text("Python-разработчик")
    expect(rows.nth(0)).to_contain_text("Ромашка")
    # resume_hash → ссылка на резюме hh.ru/resume/<hash>
    expect(
        rows.nth(0).locator("a[href='https://hh.ru/resume/hash111111']")
    ).to_have_count(1)
    # applied_by непустой → зелёная галочка; пустой → прочерк
    expect(rows.nth(0)).to_contain_text("✅")
    expect(rows.nth(1)).to_contain_text("—")
    expect(ui.page.locator("#tests-count")).to_have_text("(2)")

    calls = _calls(ui, "GET", TESTS_API_PATH)
    assert calls, f"GET {TESTS_API_PATH} не найден в ui.calls: {ui.calls}"
    # path хранится без query string — limit проверяем в полном url
    assert "limit=300" in calls[0]["url"], calls[0]


def test_empty_tests_list_shows_zero_state(ui):
    """Пустой список → счётчик (0) и ноль строк (отдельного empty-state нет)."""
    ui.data["tests"] = []
    ui.open()
    _open_tests_tab(ui)

    # "(0)" ставится только после успешного fetch+parse — доказывает,
    # что loadTests() отработал, а не просто пустой tbody с самого старта.
    expect(ui.page.locator("#tests-count")).to_have_text("(0)")
    expect(ui.page.locator("#tests-tbody tr")).to_have_count(0)
    assert _calls(ui, "GET", TESTS_API_PATH), (
        f"GET {TESTS_API_PATH} не найден в ui.calls: {ui.calls}"
    )


def test_apply_tests_checkbox_posts_toggle_for_account_idx(ui):
    """Чекбокс на карточке → POST /api/account/{idx}/apply_tests (idx в пути).

    Замена сценария «Run-кнопка»: в табе «Тесты» Run-кнопок нет;
    это единственный test-related POST в UI. Тело запроса пустое по
    дизайну (fetch POST без body) — idx передаётся в URL.
    """
    _set_single_account(ui, apply_tests=False)
    ui.set_response("POST", APPLY_TESTS_API,
                    body={"ok": True, "apply_tests": True})
    ui.open()

    cb = ui.page.locator("#acc-apply-cb-0")
    expect(cb).to_be_visible()
    expect(cb).not_to_be_checked()
    cb.check()

    # side-effect успеха (label стал active) доказывает, что POST прошёл
    expect(ui.page.locator("#acc-apply-label-0")).to_have_class(
        re.compile(r"\bactive\b")
    )
    expect(cb).to_be_checked()

    posts = _calls(ui, "POST", APPLY_TESTS_API)
    assert len(posts) == 1, f"ожидался 1 POST {APPLY_TESTS_API}: {ui.calls}"


def test_apply_tests_success_render_toggles_label(ui):
    """Success {"ok":true,"apply_tests":false} → label теряет класс active."""
    _set_single_account(ui, apply_tests=True)
    ui.set_response("POST", APPLY_TESTS_API,
                    body={"ok": True, "apply_tests": False})
    ui.open()

    label = ui.page.locator("#acc-apply-label-0")
    cb = ui.page.locator("#acc-apply-cb-0")
    expect(label).to_have_class(re.compile(r"\bactive\b"))
    expect(cb).to_be_checked()

    cb.uncheck()

    expect(label).not_to_have_class(re.compile(r"\bactive\b"))
    expect(cb).not_to_be_checked()
    assert _calls(ui, "POST", APPLY_TESTS_API), (
        f"POST {APPLY_TESTS_API} не найден в ui.calls: {ui.calls}"
    )


def test_apply_tests_fail_reverts_checkbox(ui):
    """Fail (HTTP 500, body с error) → чекбокс откатывается, label без active."""
    _set_single_account(ui, apply_tests=False)
    ui.set_response("POST", APPLY_TESTS_API,
                    body={"ok": False, "error": "account offline"}, status=500)
    ui.open()

    cb = ui.page.locator("#acc-apply-cb-0")
    expect(cb).to_be_visible()
    cb.check()

    # applyTestsToggle: !data.ok (или fetch-exception) → cb.checked = !cb.checked
    expect(cb).not_to_be_checked()
    expect(ui.page.locator("#acc-apply-label-0")).not_to_have_class(
        re.compile(r"\bactive\b")
    )
    assert _calls(ui, "POST", APPLY_TESTS_API), (
        f"POST {APPLY_TESTS_API} не найден в ui.calls: {ui.calls}"
    )
