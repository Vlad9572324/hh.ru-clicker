"""E2E: cross-cutting concerns — i18n, тёмная тема, responsive, WS reconnect, error handling.

Что реально есть в UI (проверено по static/index.html, static/js/app.js, static/css/*.css
и живыми Playwright-пробами):

i18n
- #lang-btn (onclick=toggleLang) переключает lang ru↔en; applyI18n() заполняет
  [data-i18n] текстом из словаря T в app.js, [data-i18n-ph] — placeholder'ы,
  плюс ставит document.documentElement.lang. Выбор хранится в localStorage['hh-lang'].
- Кнопка сама меняет подпись RU↔EN. Повторный клик возвращает RU.
- Квирк: при загрузке страницы init НЕ вызывает applyI18n() — из localStorage
  восстанавливается только подпись кнопки (#lang-btn = "EN"), статические
  data-i18n-элементы остаются RU до первого клика. Тест persistence проверяет
  именно реальное поведение.

Тема
- Светлой темы и переключателя темы НЕТ (prefers-color-scheme в CSS тоже нет).
- index.html грузит style.css и theme-autoclicker.css ПОСЛЕ него, поэтому
  фактический :root --bg = #08090d (а не #0d1117 из style.css), а background
  body — многослойный градиент (background-color: transparent), а не сплошной
  rgb(13,17,23). Тест ассертит реальность: тёмный --bg из известного набора
  значений + тёмный фактический фон + светлый текст.

Responsive
- Медиазапросов в CSS НЕТ. Строка табов (#tabs, flex nowrap) при 375/768px
  не помещается (scrollWidth ~1107px) — страница получает горизонтальный
  скролл, но до любого таба можно доскроллить и кликнуть. Поэтому
  "body scrollWidth <= viewport" ассертится только для 1920x1080 (где
  выполняется); для мобильных ассертится доступность UI через скролл.

WS reconnect
- onclose: #conn-dot теряет класс connected, все кнопки (.btn-sm, .apply-btn,
  button[onclick]) кроме #pause-btn становятся disabled; reconnect через
  setTimeout от 1s (x2 до 30s), onopen возвращает connected и re-enable.
  close code 4401 останавливает цикл (не тестируем: требует отдельного
  серверного сценария авторизации).

Error handling
- POST /api/proxy/set вызывает proxySave() (кнопка в Settings → секция
  «Прокси», button.btn-sm[onclick^="proxySave"]). !ok/500 → inline-ошибка
  #proxy-error ("⚠️ <error> — откат..."); toast-системы в UI нет.
- #dbg-err показывает "JS ERROR: ..." только при падении renderAll.
"""

import re

import pytest
from playwright.sync_api import expect


# Минимальный снапшот, при котором renderAll() не падает (проверено пробой:
# renderHeader/renderGlobalStats/renderMain требуют global_stats и config).
# Подмешивается в ui.state ДО ui.open().
SNAP = {
    "uptime_seconds": 123,
    "paused": False,
    "accounts": [],
    "recent_responses": [],
    "log": [],
    "llm_log": [],
    "config": {
        "daily_apply_limit": 0,
        "filter_agencies": False,
        "filter_low_competition": False,
        "search_period_days": 0,
        "skip_inconsistent": False,
        "use_oauth_apply": False,
        "questionnaire_templates": [],
        "questionnaire_default_answer": "",
        "letter_templates": [],
        "url_pool": [],
        "llm_profiles": [],
        "llm_profile_mode": "single",
    },
    "global_stats": {
        "total_sent": 0,
        "total_tests": 0,
        "total_errors": 0,
        "total_found": 0,
        "storage_total": 0,
        "storage_tests": 0,
    },
    "vacancy_queues": {},
}

CONNECTED = re.compile(r"\bconnected\b")


def _prime_state(ui):
    """Подмешиваем рендер-безопасный снапшот (conftest может уже что-то давать)."""
    for key, val in SNAP.items():
        ui.state.setdefault(key, val)


def _lang_snapshot(page):
    return {
        "btn": page.locator("#lang-btn").inner_text(),
        "tab_main": page.locator(".tab[data-tab=main]").inner_text(),
        "tab_settings": page.locator(".tab[data-tab=settings]").inner_text(),
        "hdr_found": page.locator("[data-i18n=hdr_found]").inner_text(),
        "html_lang": page.evaluate("document.documentElement.lang"),
        "log_ph": page.locator("#log-search").get_attribute("placeholder"),
    }


# ───────────────────────────── i18n ─────────────────────────────


def test_i18n_toggle_ru_to_en_and_back(ui):
    """Клик #lang-btn: data-i18n/text/href-тексты → EN, повторный клик → RU."""
    _prime_state(ui)
    ui.open()

    before = _lang_snapshot(ui.page)
    assert before["btn"] == "RU"
    assert before["tab_main"] == "📊 Главная"
    assert before["html_lang"] == "ru"

    ui.page.click("#lang-btn")

    expect(ui.page.locator("#lang-btn")).to_have_text("EN")
    expect(ui.page.locator(".tab[data-tab=main]")).to_have_text("📊 Main")
    expect(ui.page.locator(".tab[data-tab=settings]")).to_have_text("⚙️ Settings")
    expect(ui.page.locator("[data-i18n=hdr_found]")).to_have_text("found")
    # data-i18n-ph: placeholder тоже переводится
    expect(ui.page.locator("#log-search")).to_have_attribute("placeholder", "🔍 Search...")
    expect(ui.page.locator("html")).to_have_attribute("lang", "en")

    # повторный клик возвращает RU
    ui.page.click("#lang-btn")

    expect(ui.page.locator("#lang-btn")).to_have_text("RU")
    expect(ui.page.locator(".tab[data-tab=main]")).to_have_text("📊 Главная")
    expect(ui.page.locator(".tab[data-tab=settings]")).to_have_text("⚙️ Настройки")
    expect(ui.page.locator("[data-i18n=hdr_found]")).to_have_text("найдено")
    expect(ui.page.locator("#log-search")).to_have_attribute("placeholder", "🔍 Поиск...")
    expect(ui.page.locator("html")).to_have_attribute("lang", "ru")


def test_i18n_choice_persisted_across_reload(ui):
    """Выбор EN сохраняется в localStorage: после reload кнопка показывает EN,
    а клик возвращает RU (внутренний lang был 'en'). Реальное поведение:
    статические data-i18n при reload НЕ перерисовываются (applyI18n на init
    не вызывается) — ассертим только подпись кнопки и результат клика."""
    _prime_state(ui)
    ui.open()

    ui.page.click("#lang-btn")
    expect(ui.page.locator("#lang-btn")).to_have_text("EN")

    ui.page.reload()

    # lang из localStorage применён к подписи кнопки
    expect(ui.page.locator("#lang-btn")).to_have_text("EN", timeout=10_000)
    # внутренний lang == 'en' → клик переключает обратно на RU
    expect(ui.page.locator("#lang-btn")).to_be_enabled(timeout=10_000)
    ui.page.click("#lang-btn")
    expect(ui.page.locator("#lang-btn")).to_have_text("RU")
    expect(ui.page.locator(".tab[data-tab=main]")).to_have_text("📊 Главная")


# ───────────────────────────── тема ─────────────────────────────


def test_dark_theme_css_variables_applied(ui):
    """Только тёмная тема: :root --bg из тёмного набора, фактический фон body
    тёмный (сплошной цвет или градиент поверх transparent), текст светлый,
    переключателя темы в DOM нет."""
    _prime_state(ui)
    ui.open()

    bg_var = ui.page.evaluate(
        "getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()"
    )
    # style.css даёт #0d1117; theme-autoclicker.css (грузится позже) — #08090d
    assert bg_var.lower() in {"#0d1117", "#08090d"}, f"--bg={bg_var!r} не тёмный"

    body_bg_color = ui.page.evaluate(
        "getComputedStyle(document.body).backgroundColor"
    )
    body_bg_image = ui.page.evaluate(
        "getComputedStyle(document.body).backgroundImage"
    )

    def _rgb(s):
        m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", s)
        return tuple(int(x) for x in m.groups()) if m else None

    rgb = _rgb(body_bg_color)
    if rgb is not None and rgb != (0, 0, 0):
        # сплошной фон — должен быть тёмным
        assert max(rgb) < 60, f"body background-color {body_bg_color!r} не тёмный"
    else:
        # transparent/чёрный color → фон рисуется градиентом (theme-autoclicker)
        assert body_bg_image != "none", (
            f"body не тёмный: color={body_bg_color!r}, image={body_bg_image!r}"
        )

    # текст светлый на тёмном — var(--text) применён к body
    text_rgb = _rgb(
        ui.page.evaluate("getComputedStyle(document.body).color")
    )
    assert text_rgb and min(text_rgb) > 150, f"body color {text_rgb} не светлый"

    # переключателя темы не существует
    assert ui.page.locator(
        "#theme-btn, [data-theme-toggle], .theme-switch, #theme-toggle"
    ).count() == 0


# ─────────────────────────── responsive ───────────────────────────


def _open_settings_tab(page):
    """Клик таба Settings; на узких вьюпортах Playwright сам доскроллит."""
    page.locator(".tab[data-tab=settings]").click()
    expect(page.locator("#panel-settings")).to_have_class(re.compile(r"\bactive\b"))


def test_responsive_desktop_1920_no_overflow(ui):
    """1920x1080: без горизонтального overflow, header и все табы в viewport,
    активный контент видим."""
    _prime_state(ui)
    ui.open()
    ui.page.set_viewport_size({"width": 1920, "height": 1080})

    header = ui.page.locator("#header")
    expect(header).to_be_visible()

    scroll_width = ui.page.evaluate("document.body.scrollWidth")
    assert scroll_width <= 1920 + 20, f"horizontal overflow: {scroll_width=}"

    # весь таб-бар влезает: последний таб (Settings) внутри viewport
    right = ui.page.locator(".tab[data-tab=settings]").evaluate(
        "el => el.getBoundingClientRect().right"
    )
    assert right <= 1920, f"settings tab right={right} за пределами viewport"

    expect(ui.page.locator("#panel-main")).to_be_visible()
    _open_settings_tab(ui.page)
    expect(ui.page.locator("#panel-settings")).to_be_visible()


@pytest.mark.parametrize("width,height", [(375, 667), (768, 1024)])
def test_responsive_narrow_header_and_tabs_reachable(ui, width, height):
    """375x667 / 768x1024: header виден на всю ширину, табы доступны через
    горизонтальный скролл, контент активного таба видим.

    Примечание: медиазапросов в CSS нет, таб-бар (10 nowrap-табов ~1107px)
    на этих ширинах создаёт горизонтальный overflow — ассерт scrollWidth<=viewport
    здесь НЕ выполняется и сознательно не проверяется (см. docstring модуля)."""
    _prime_state(ui)
    ui.open()
    ui.page.set_viewport_size({"width": width, "height": height})

    header = ui.page.locator("#header")
    expect(header).to_be_visible()
    header_w = header.evaluate("el => el.getBoundingClientRect().width")
    assert abs(header_w - width) <= 2, f"header width {header_w} != viewport {width}"

    # активный контент (main по умолчанию) видим
    expect(ui.page.locator("#panel-main")).to_be_visible()

    # до таба Settings можно доскроллить и кликнуть → панель активна и видима
    _open_settings_tab(ui.page)
    expect(ui.page.locator("#panel-settings")).to_be_visible()
    # контент settings-панели (первая секция) тоже видима
    expect(ui.page.locator("#proxy-section")).to_be_visible()

    # возврат на main работает
    ui.page.locator(".tab[data-tab=main]").click()
    expect(ui.page.locator("#panel-main")).to_have_class(re.compile(r"\bactive\b"))


# ─────────────────────────── WS reconnect ───────────────────────────


def test_ws_reconnect_after_server_close(ui):
    """Серверный разрыв: conn-dot гаснет, кнопки (кроме #pause-btn) disabled,
    затем клиент сам переподключается (reconnect delay от 1s)."""
    _prime_state(ui)
    ui.open()

    dot = ui.page.locator("#conn-dot")
    lang_btn = ui.page.locator("#lang-btn")
    pause_btn = ui.page.locator("#pause-btn")
    expect(dot).to_have_class(CONNECTED)
    expect(lang_btn).to_be_enabled()

    ui.close_ws(code=1000)

    # onclose: индикатор гаснет, кнопки (кроме pause) блокируются
    expect(dot).not_to_have_class(CONNECTED, timeout=5_000)
    expect(lang_btn).to_be_disabled(timeout=5_000)
    expect(pause_btn).to_be_enabled()

    # reconnect: delay начинается с 1s → с запасом ждём до 10s
    expect(dot).to_have_class(CONNECTED, timeout=10_000)
    expect(lang_btn).to_be_enabled(timeout=5_000)


def test_ws_reconnect_two_consecutive_closes(ui):
    """Два последовательных разрыва: после каждого успешного reconnect
    delay сбрасывается на 1s, поэтому восстановление происходит оба раза."""
    _prime_state(ui)
    ui.open()

    dot = ui.page.locator("#conn-dot")
    lang_btn = ui.page.locator("#lang-btn")
    expect(dot).to_have_class(CONNECTED)

    for round_no in (1, 2):
        ui.close_ws(code=1000)
        expect(dot).not_to_have_class(CONNECTED, timeout=5_000)
        expect(lang_btn).to_be_disabled(timeout=5_000)
        expect(dot).to_have_class(
            CONNECTED, timeout=10_000
        ), f"reconnect не произошёл после разрыва #{round_no}"
        expect(lang_btn).to_be_enabled(timeout=5_000)


# ─────────────────────────── error handling ───────────────────────────


def test_proxy_save_500_shows_inline_error(ui):
    """POST /api/proxy/set → 500: proxySave() показывает inline-ошибку
    #proxy-error (toast-системы в UI нет). Попутно проверяем, что POST
    реально ушёл с телом {url}."""
    _prime_state(ui)
    # стабильный auto-probe при загрузке страницы (proxyCheck на DOMContentLoaded)
    ui.set_response(
        "GET", r"/api/proxy/info",
        body={"proxy": "", "ip": "203.0.113.7", "impersonate": "нет"},
    )
    ui.set_response(
        "POST", r"/api/proxy/set",
        body={"error": "cc8-boom"}, status=500,
    )
    ui.open()

    _open_settings_tab(ui.page)
    save_btn = ui.page.locator("#panel-settings button.btn-sm[onclick^='proxySave']")
    expect(save_btn).to_be_visible()
    expect(save_btn).to_be_enabled()
    save_btn.click()

    err = ui.page.locator("#proxy-error")
    expect(err).to_be_visible(timeout=10_000)
    expect(err).to_contain_text("cc8-boom")
    expect(err).to_contain_text("⚠️")

    posts = [
        c for c in ui.calls
        if c.get("method") == "POST" and "/api/proxy/set" in (c.get("path") or "")
    ]
    assert posts, f"POST /api/proxy/set не найден в ui.calls: {ui.calls}"
    assert "url" in (posts[0].get("json") or {}), posts[0]


def test_dbg_err_empty_and_no_pageerrors_on_normal_ops(ui):
    """Штатные операции (открытие, смена табов, повторный state_update)
    не зажигают #dbg-err и не сыплют pageerror'ами (ui.page_errors
    заполняет pageerror-обработчик фикстуры)."""
    _prime_state(ui)
    ui.open()

    # несколько штатных операций
    for tab in ("log", "settings", "main"):
        ui.page.locator(f".tab[data-tab={tab}]").click()
        expect(ui.page.locator(f"#panel-{tab}")).to_have_class(
            re.compile(r"\bactive\b")
        )
    ui.push_state()

    dbg = ui.page.locator("#dbg-err")
    expect(dbg).to_have_text("")
    expect(dbg).to_be_hidden()
    assert not ui.page_errors, f"pageerror при штатных операциях: {ui.page_errors}"
