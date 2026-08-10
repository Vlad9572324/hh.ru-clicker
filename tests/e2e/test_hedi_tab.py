"""E2E: вкладка «🤖 HH Хэдди» — чат с HH AI-ассистентом (subagent_7).

Тесты написаны по ФАКТИЧЕСКОМУ поведению static/js/features/hedi.js и
формам ответов app/routes/hedi.py:

Переключение вкладки (data-tab="hedi")
    app.js вызывает initHediTab(): select #hedi-account заполняется из
    State.lastSnapshot.accounts, ПЕРВЫЙ аккаунт выбирается автоматически,
    после чего уходит GET /api/account/{idx}/hedi/history?limit=50.
    Фронтенд НЕ дёргает GET .../hedi/start напрямую: старт чата на бэкенде
    происходит внутри api_hedi_history/api_hedi_send (_chat_id -> _start),
    поэтому chat_id приходит в ответе history/send.

Формы ответов (app/routes/hedi.py):
    ok:    GET history -> {"ok": true, "chat_id": ..., "messages": [...]}
           POST send   -> {"ok": true, "chat_id": ...}
    error: HTTPException -> {"detail": "..."} со статусом 4xx — фронтенд
           берёт data.detail и показывает в #hedi-status с классом error.

Рендер истории (hediRender):
    sender == "applicant" -> bubble .hedi-message.user (аватар 👤),
    остальные             -> .hedi-message.bot (аватар 🤖);
    пустая история        -> плейсхолдер .hedi-empty.

Отправка: #hedi-send (onclick) или Enter в #hedi-input (keydown без Shift)
-> POST /api/account/{idx}/hedi/send {"text": ...}; при успехе input
очищается, история перезагружается, статус «Сообщение отправлено».

Все ответы мокаются через ui.set_response ДО ui.open() (автозапросы вкладки
не должны попадать на 404 «not mocked»).
"""

import re

from playwright.sync_api import expect

T_MS = 15_000
T_S = 15.0

HISTORY_RE = r"/api/account/0/hedi/history"
SEND_RE = r"/api/account/0/hedi/send"
HISTORY_PATH = "/api/account/0/hedi/history"
SEND_PATH = "/api/account/0/hedi/send"

ACCOUNT_NAME = "Иван Тестов (ivan@example.com)"


# ── helpers ────────────────────────────────────────────────────────────────

def find_calls(ui, method, path):
    return [c for c in ui.calls if c.get("method") == method and c.get("path") == path]


def wait_call(ui, method, path, timeout=T_S):
    ui.wait_until(
        lambda: find_calls(ui, method, path),
        timeout=timeout,
        message=f"не дождались {method} {path} в ui.calls",
    )
    return find_calls(ui, method, path)[0]


def history_payload(messages):
    """ok-форма GET /api/account/{idx}/hedi/history (app/routes/hedi.py)."""
    return {"ok": True, "chat_id": "chat-test-123", "messages": messages}


def open_hedi(ui):
    """Открывает вкладку Хэдди; панель видима, дефолтный аккаунт idx=0."""
    ui.open()
    page = ui.page
    page.locator('.tab[data-tab="hedi"]').click()
    expect(page.locator("#panel-hedi")).to_be_visible()
    return page


def fill_and_send(ui, page, text, via_enter=False):
    page.locator("#hedi-input").fill(text)
    if via_enter:
        page.locator("#hedi-input").press("Enter")
    else:
        page.locator("#hedi-send").click()


# ── 1. выбор аккаунта и загрузка истории ─────────────────────────────────

def test_hedi_tab_account_select_and_history_fetch(ui):
    """Открытие вкладки: аккаунт из снапшота, авто-выбор, GET history."""
    ui.set_response("GET", HISTORY_RE, history_payload([]))
    page = open_hedi(ui)

    sel = page.locator("#hedi-account")
    # плейсхолдер «Выберите аккаунт» + один аккаунт из default_state
    expect(sel.locator("option")).to_have_count(2, timeout=T_MS)
    expect(sel.locator("option", has_text=ACCOUNT_NAME)).to_have_count(1)
    # initHediTab автоматически выбирает первый аккаунт (idx=0)
    expect(sel).to_have_value("0")

    # выбор аккаунта -> GET /api/account/0/hedi/history?limit=50
    call = wait_call(ui, "GET", HISTORY_PATH)
    assert call["path"] == HISTORY_PATH

    expect(page.locator("#hedi-status")).to_have_text("История обновлена", timeout=T_MS)
    # пустая история -> плейсхолдер
    expect(page.locator("#hedi-messages .hedi-empty")).to_contain_text("История пуста")
    expect(page.locator("#hedi-messages .hedi-message")).to_have_count(0)


def test_hedi_history_renders_messages(ui):
    """История из mock'а: applicant -> .user, бот -> .bot, время отрисовано."""
    messages = [
        {"sender": "bot", "text": "Привет! Я Хэдди.", "created_at": "2026-08-10T12:00:00"},
        {"sender": "applicant", "text": "Подбери вакансии для Python-разработчика",
         "created_at": "2026-08-10T12:01:00"},
    ]
    ui.set_response("GET", HISTORY_RE, history_payload(messages))
    page = open_hedi(ui)

    msgs = page.locator("#hedi-messages .hedi-message")
    expect(msgs).to_have_count(2, timeout=T_MS)

    bot = page.locator("#hedi-messages .hedi-message.bot")
    expect(bot).to_have_count(1)
    expect(bot).to_contain_text("Привет! Я Хэдди.")
    expect(bot.locator(".hedi-avatar")).to_have_text("🤖")

    user = page.locator("#hedi-messages .hedi-message.user")
    expect(user).to_have_count(1)
    expect(user).to_contain_text("Подбери вакансии для Python-разработчика")
    expect(user.locator(".hedi-avatar")).to_have_text("👤")

    # hediTime() форматирует created_at; формат локали не фиксируем
    expect(bot.locator(".hedi-time")).not_to_have_text("")
    expect(page.locator("#hedi-status")).to_have_text("История обновлена")


# ── 2. отправка сообщения ─────────────────────────────────────────────────

def test_hedi_send_posts_message_and_updates_status(ui):
    """Клик #hedi-send -> POST /hedi/send {"text": ...}; затем Enter-отправка."""
    ui.set_response("GET", HISTORY_RE, history_payload([]))
    ui.set_response("POST", SEND_RE, {"ok": True, "chat_id": "chat-test-123"})
    page = open_hedi(ui)
    wait_call(ui, "GET", HISTORY_PATH)  # автозагрузка истории до отправки

    fill_and_send(ui, page, "Привет, Хэдди!")

    call = wait_call(ui, "POST", SEND_PATH)
    assert call["json"] == {"text": "Привет, Хэдди!"}

    expect(page.locator("#hedi-status")).to_have_text("Сообщение отправлено", timeout=T_MS)
    expect(page.locator("#hedi-input")).to_have_value("")  # input очищен
    expect(page.locator("#hedi-send")).to_be_enabled()     # кнопка разблокирована

    # Enter (без Shift) тоже отправляет — keydown-обработчик hedi.js
    fill_and_send(ui, page, "Какие вакансии рядом?", via_enter=True)

    def _two_posts():
        return len(find_calls(ui, "POST", SEND_PATH)) >= 2

    ui.wait_until(_two_posts, timeout=T_S, message="второй POST /hedi/send")
    posts = find_calls(ui, "POST", SEND_PATH)
    assert posts[-1]["json"] == {"text": "Какие вакансии рядом?"}
    expect(page.locator("#hedi-status")).to_have_text("Сообщение отправлено")


def test_hedi_send_error_shows_detail_in_status(ui):
    """Error-ветка hedi.py: 404 {"detail": ...} -> #hedi-status с классом error."""
    ui.set_response("GET", HISTORY_RE, history_payload([]))
    ui.set_response("POST", SEND_RE, {"detail": "hedi chat not found"}, status=404)
    page = open_hedi(ui)
    wait_call(ui, "GET", HISTORY_PATH)

    fill_and_send(ui, page, "Сообщение в никуда")

    wait_call(ui, "POST", SEND_PATH)
    status = page.locator("#hedi-status")
    expect(status).to_contain_text("hedi chat not found", timeout=T_MS)
    expect(status).to_have_class(re.compile(r"\berror\b"))
    # input при ошибке НЕ очищается, кнопка снова доступна
    expect(page.locator("#hedi-input")).to_have_value("Сообщение в никуда")
    expect(page.locator("#hedi-send")).to_be_enabled()


# ── 3. статус: ошибка истории и сброс аккаунта ───────────────────────────

def test_hedi_history_error_shows_detail(ui):
    """GET history -> 404 {"detail": ...}: статус показывает detail с error."""
    ui.set_response("GET", HISTORY_RE, {"detail": "hedi chat not found"}, status=404)
    page = open_hedi(ui)

    status = page.locator("#hedi-status")
    expect(status).to_contain_text("hedi chat not found", timeout=T_MS)
    expect(status).to_have_class(re.compile(r"\berror\b"))
    expect(page.locator("#hedi-messages .hedi-message")).to_have_count(0)


def test_hedi_select_placeholder_resets_chat(ui):
    """Выбор «Выберите аккаунт» ('') очищает сообщения и просит выбрать аккаунт."""
    ui.set_response("GET", HISTORY_RE, history_payload(
        [{"sender": "bot", "text": "Привет!", "created_at": "2026-08-10T12:00:00"}],
    ))
    page = open_hedi(ui)
    expect(page.locator("#hedi-messages .hedi-message")).to_have_count(1, timeout=T_MS)

    page.select_option("#hedi-account", "")

    expect(page.locator("#hedi-status")).to_have_text(
        "Выберите mobile-аккаунт для начала чата.", timeout=T_MS)
    expect(page.locator("#hedi-messages .hedi-message")).to_have_count(0)

    # отправка без аккаунта не уходит в сеть
    page.locator("#hedi-input").fill("Есть кто?")
    page.locator("#hedi-send").click()
    expect(page.locator("#hedi-status")).to_contain_text("Сначала выберите аккаунт")
    assert find_calls(ui, "POST", SEND_PATH) == []
