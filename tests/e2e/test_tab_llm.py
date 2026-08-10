"""E2E: таб «LLM Ответы» (.tab[data-tab="llm"]).

Что реально есть в UI (проверено по static/js/app.js, static/index.html,
app/manager.py, app/storage.py):

- Список «ниток» (переговоров) рендерится в таблицу #llm-interviews-body из
  ленивого GET /api/interviews (llmInterviewsLoad/llmInterviewsRender), а НЕ
  напрямую из llm_log. llm_log из WS-снапшота питает статус-бар:
  #llm-st-sources (счётчики источников ответов: 💡 quick_reply / ✍️ ai_letter /
  🤖 llm / 📝 cached по полю source), #llm-st-replied (✅ sent · 📝 drafts по
  полю sent) и #llm-st-interval («последний: <time>» = llm_log[0].time).
- Сообщения нитки не «разворачиваются» — expand-механики в табе нет: текст
  сообщения работодателя и ответа бота рендерятся прямо в ячейки строки
  (.llm-msg-cell / .llm-reply-cell), плюс 🔗-ссылка на hh.ru/chat/<neg_id>.
- Dedup-индикаторов (exact/normalized/semantic) В UI НЕТ: grep app.js пуст,
  дедупликация на бэкенде внутренняя ((neg_id, msg_id) в app/storage.py и
  app/manager.py) и в снапшот не попадает. Заменено реальными индикаторами
  записи: бейдж статуса ответа (llm-sent-badge / llm-draft-badge / ⏳ / 🔒)
  и бейдж состояния чата (🤖 Робот / ⏳ Ждём HR / 💬 Ответили).
- quick_reply vs LLM-сгенерированный ответ визуально различаются цветными
  чипами в #llm-st-sources (💡 зелёный vs 🤖 циановый) — единственное место,
  где source записи виден в UI.
- Toggle «показать/скрыть заглушенные» ОТСУТСТВУЕТ (нет muted/suppressed ни в
  app.js, ни в снапшоте). Заменён реальной show/hide-механикой таба —
  клиентским поиском #llm-log-search (oninput → llmInterviewsRender) и
  счётчиком «N из M».
- Обновление через ui.push_state(): renderAll → renderLlmLog пересчитывает
  счётчики статус-бара и перерисовывает отладочный лог #llm-debug-log из
  snap.log (записи, содержащие 🤖 или «LLM»).
- Пустые данные: interviews [] → #llm-interviews-table скрыт, показан
  #llm-interviews-empty; ошибки рендера видны в #dbg-err («JS ERROR: …»)
  и в ui.page_errors.

Стейт собирается мутацией дефолтного ui.state из conftest (полная форма
аккаунта нужна ui.open() — там wait на #acc-sent-<idx> по полю «sent»).
"""

import copy
import re

from playwright.sync_api import expect


INTERVIEWS_API = "/api/interviews"


# ── данные ─────────────────────────────────────────────────────


def _llm_entry(entry_time, acc, employer, *, source="llm", sent=True,
               neg_id="n-1", vacancy_title="Вакансия",
               employer_msg="Сообщение HR", bot_reply="Ответ бота",
               color="cyan"):
    """Запись llm_log — структура из self.llm_log.appendleft(...) в app/manager.py."""
    return {
        "time": entry_time,
        "acc": acc,
        "color": color,
        "employer": employer,
        "vacancy_title": vacancy_title,
        "neg_id": neg_id,
        "vacancy_id": "",
        "employer_msg": employer_msg,
        "bot_reply": bot_reply,
        "sent": sent,
        "source": source,
    }


def _row(neg_id, acc, employer, *, status="pending_reply", chat_status="",
         vacancy_title="", employer_last_msg="", llm_reply="",
         last_seen="2026-08-10T12:00:00", acc_color="cyan"):
    """Запись interviews DB — поля из upsert_interview/get_interviews_list."""
    return {
        "neg_id": neg_id,
        "acc": acc,
        "acc_color": acc_color,
        "employer": employer,
        "vacancy_title": vacancy_title,
        "first_seen": "2026-08-09T10:00:00",
        "last_seen": last_seen,
        "employer_last_msg": employer_last_msg,
        "llm_reply": llm_reply,
        "llm_sent": status == "replied",
        "status": status,
        "chat_status": chat_status,
    }


# ── хелперы ────────────────────────────────────────────────────


def _enable_llm(ui):
    """Config/аккаунты так, чтобы LLM-таб был в состоянии «Работает»."""
    cfg = ui.state["config"]
    cfg["llm_enabled"] = True
    cfg["llm_auto_send"] = True
    cfg["llm_api_key_set"] = True
    for acc in ui.state["accounts"]:
        acc["llm_enabled"] = True


def _add_second_account(ui, idx=1, short="ИВ2", name="Второй Аккаунт",
                        color="green", **extra):
    """Клон дефолтного аккаунта (полная форма полей нужна ui.open())."""
    acc = copy.deepcopy(ui.state["accounts"][0])
    acc.update({"idx": idx, "short": short, "name": name, "color": color})
    acc.update(extra)
    ui.state["accounts"].append(acc)
    return acc


def _open_llm_tab(ui):
    ui.page.click('.tab[data-tab="llm"]')
    expect(ui.page.locator("#panel-llm")).to_have_class(re.compile(r"\bactive\b"))


def _calls(ui, method, path):
    # conftest пишет path через urlsplit(...).path — БЕЗ query string
    return [c for c in ui.calls if c.get("method") == method and c.get("path") == path]


# ── тесты ──────────────────────────────────────────────────────


def test_llm_tab_renders_threads_status_and_account_toggles(ui):
    """Список ниток с разными чатами: таблица из GET /api/interviews,
    статус-бар из llm_log/снапшота, тумблеры аккаунтов, счётчик записей."""
    _enable_llm(ui)
    ui.state["accounts"][0]["hh_interviews"] = 2
    ui.state["accounts"][0]["llm_pending_chats"] = 1
    _add_second_account(ui, hh_interviews=1, llm_pending_chats=0)
    ui.state["llm_log"] = [
        _llm_entry("10.08 14:00", "ИВ", "ООО Ромашка"),
    ]
    ui.data["interviews"] = [
        _row("101", "ИВ", "ООО Ромашка", status="replied",
             vacancy_title="Python-разработчик",
             employer_last_msg="Здравствуйте!", llm_reply="Добрый день!",
             last_seen="2026-08-10T12:04:00"),
        _row("102", "ИВ2", "ИП Петров", status="pending_reply",
             vacancy_title="QA-инженер",
             employer_last_msg="Расскажите о себе",
             last_seen="2026-08-10T12:03:00"),
        _row("103", "ИВ", "Литех", status="draft",
             vacancy_title="Аналитик",
             employer_last_msg="Когда готовы выйти?",
             llm_reply="Готов обсудить",
             last_seen="2026-08-10T12:02:00"),
    ]
    ui.open()
    _open_llm_tab(ui)

    body_rows = ui.page.locator("#llm-interviews-body tr")
    expect(body_rows).to_have_count(3)
    # дефолтная сортировка date_desc — свежие сверху
    expect(body_rows.nth(0)).to_contain_text("ООО Ромашка")
    expect(body_rows.nth(1)).to_contain_text("ИП Петров")
    expect(body_rows.nth(2)).to_contain_text("Литех")
    expect(ui.page.locator("#llm-log-count")).to_have_text("3 записей")

    # фильтр по аккаунту авто-пополняется из загруженных строк
    acc_filter = ui.page.locator("#llm-log-acc-filter")
    expect(acc_filter.locator("option[value='ИВ']")).to_have_count(1)
    expect(acc_filter.locator("option[value='ИВ2']")).to_have_count(1)

    # карточки статистики по аккаунтам (llmRenderAccStats, полная БД)
    acc_stats = ui.page.locator("#llm-acc-stats")
    expect(acc_stats).to_contain_text("Иван Тестов (ivan@example.com)")
    expect(acc_stats).to_contain_text("Второй Аккаунт")

    # статус-бар: интервью/обработка из accounts, состояние из config
    expect(ui.page.locator("#llm-st-state")).to_have_text(
        "✅ Работает — авто-ответы идут")
    expect(ui.page.locator("#llm-st-chats")).to_have_text(
        "🎯 3 интервью · ⏳ 1 в обработке")

    # тумблеры LLM по аккаунтам из snapshot.accounts
    btn0 = ui.page.locator("#llm-acc-btn-0")
    expect(btn0).to_be_visible()
    expect(ui.page.locator("#llm-acc-btn-1")).to_be_visible()

    assert _calls(ui, "GET", INTERVIEWS_API), (
        f"GET {INTERVIEWS_API} не найден в ui.calls: {ui.calls}"
    )

    # клик тумблера аккаунта → WS-команда account_llm
    btn0.click()
    expect(btn0).to_be_disabled()  # double-click guard в llmToggleAccount
    ui.wait_until(
        lambda: any(c.get("type") == "account_llm" and c.get("idx") == 0
                    for c in ui.commands),
        message=f"команда account_llm не пришла в ui.commands: {ui.commands}",
    )


def test_thread_row_shows_conversation_messages_and_chat_link(ui):
    """«Разворачивание» нитки: в UI нет expand-механики — сообщения работодателя
    и ответ бота рендерятся прямо в ячейки строки + ссылка на чат HH."""
    _enable_llm(ui)
    ui.data["interviews"] = [
        _row("777", "ИВ", "ООО Ромашка", status="replied",
             vacancy_title="Python-разработчик",
             employer_last_msg="Здравствуйте!\nКогда удобно созвониться?",
             llm_reply="Добрый день!\nУдобно завтра после 15:00.",
             last_seen="2026-08-10T12:00:00"),
    ]
    ui.open()
    _open_llm_tab(ui)

    tr = ui.page.locator("#llm-interviews-body tr")
    expect(tr).to_have_count(1)
    msg = tr.nth(0).locator(".llm-msg-cell")
    expect(msg).to_contain_text("Здравствуйте!")
    expect(msg).to_contain_text("Когда удобно созвониться?")
    reply = tr.nth(0).locator(".llm-reply-cell")
    expect(reply).to_contain_text("Добрый день!")
    expect(reply).to_contain_text("Удобно завтра после 15:00.")
    # ссылка на чат по neg_id
    expect(tr.nth(0).locator("a[href='https://hh.ru/chat/777']")).to_have_count(1)
    # дата: last_seen с заменой T на пробел, обрезка до минут
    expect(tr.nth(0).locator("td").nth(0)).to_have_text("2026-08-10 12:00")
    # аккаунт в строке
    expect(tr.nth(0)).to_contain_text("ИВ")


def test_record_level_indicators_status_and_chat_badges(ui):
    """Индикаторы по записи. ТЗ-вариант «dedup exact/normalized/semantic» в UI
    отсутствует (grep app.js пуст; дедуп бэкенда (neg_id, msg_id) в снапшот не
    попадает) — заменено реальными индикаторами: статус ответа + статус чата."""
    _enable_llm(ui)
    ui.data["interviews"] = [
        _row("1", "ИВ", "Альфа", status="replied", llm_reply="ок",
             last_seen="2026-08-10T12:04:00"),
        _row("2", "ИВ", "Бета", status="draft", llm_reply="черновик",
             last_seen="2026-08-10T12:03:00"),
        _row("3", "ИВ", "Гамма", status="pending_reply",
             employer_last_msg="?", last_seen="2026-08-10T12:02:00"),
        _row("4", "ИВ", "Робот Рекрутер", status="replied",
             chat_status="robot", llm_reply="🤖 Кнопка: ДА",
             last_seen="2026-08-10T12:01:00"),
    ]
    ui.open()
    _open_llm_tab(ui)

    tr = ui.page.locator("#llm-interviews-body tr")
    expect(tr).to_have_count(4)
    expect(tr.nth(0).locator(".llm-sent-badge")).to_have_text("✅ Отправлено")
    expect(tr.nth(1).locator(".llm-draft-badge")).to_have_text("📝 Черновик")
    expect(tr.nth(2)).to_contain_text("⏳ Ждёт ответа")
    expect(tr.nth(2).locator(".llm-sent-badge, .llm-draft-badge")).to_have_count(0)
    # робот-чат: бейдж чата + статус отправленного ответа
    expect(tr.nth(3)).to_contain_text("🤖 Робот")
    expect(tr.nth(3).locator(".llm-sent-badge")).to_have_text("✅ Отправлено")


def test_quick_reply_and_llm_sources_render_distinct_badges(ui):
    """quick_reply vs LLM-ответ различаются визуально: цветные чипы в
    #llm-st-sources (💡 зелёный quick_reply / 🤖 циановый llm / 📝 cached)
    по полю source записей llm_log; sent/draft — в #llm-st-replied."""
    _enable_llm(ui)
    ui.state["llm_log"] = [
        _llm_entry("10.08 15:05", "ИВ", "Литех", source="quick_reply", sent=True),
        _llm_entry("10.08 15:04", "ИВ", "Ромашка", source="llm", sent=False),
        _llm_entry("10.08 15:03", "ИВ", "Петров", source="llm", sent=True),
        _llm_entry("10.08 15:02", "ИВ", "Гамма", source="quick_reply", sent=True),
        _llm_entry("10.08 15:01", "ИВ", "Дельта", source="cached", sent=True),
    ]
    ui.open()
    _open_llm_tab(ui)

    sources = ui.page.locator("#llm-st-sources")
    expect(sources).to_have_text("💡2 · 🤖2 · 📝1")
    spans = sources.locator("span")
    expect(spans.nth(0)).to_have_text("💡2")
    expect(spans.nth(0)).to_have_attribute("style", re.compile(r"var\(--green\)"))
    expect(spans.nth(1)).to_have_text("🤖2")
    expect(spans.nth(1)).to_have_attribute("style", re.compile(r"var\(--cyan\)"))
    expect(spans.nth(2)).to_have_text("📝1")

    expect(ui.page.locator("#llm-st-replied")).to_have_text(
        "✅ 4 отправлено · 📝 1 черновиков")
    expect(ui.page.locator("#llm-st-interval")).to_have_text(
        "🔄 каждые 5м · последний: 10.08 15:05")


def test_search_filter_hides_and_restores_rows(ui):
    """Показать/скрыть записи. ТЗ-вариант «заглушенные сообщения + toggle»
    отсутствует (muted/suppressed нет ни в app.js, ни в снапшоте) — заменено
    реальной show/hide-механикой таба: клиентский поиск #llm-log-search."""
    _enable_llm(ui)
    ui.data["interviews"] = [
        _row("1", "ИВ", "ООО Ромашка", status="replied", llm_reply="x",
             last_seen="2026-08-10T12:03:00"),
        _row("2", "ИВ", "ИП Петров", status="pending_reply",
             employer_last_msg="вопрос", last_seen="2026-08-10T12:02:00"),
        _row("3", "ИВ2", "Литех", status="draft", llm_reply="y",
             last_seen="2026-08-10T12:01:00"),
    ]
    ui.open()
    _open_llm_tab(ui)

    tr = ui.page.locator("#llm-interviews-body tr")
    expect(tr).to_have_count(3)

    search = ui.page.locator("#llm-log-search")
    search.fill("ромашка")
    expect(tr).to_have_count(1)
    expect(tr.nth(0)).to_contain_text("ООО Ромашка")
    expect(ui.page.locator("#llm-log-count")).to_have_text("1 из 3")

    search.fill("петров")
    expect(tr).to_have_count(1)
    expect(tr.nth(0)).to_contain_text("ИП Петров")

    search.fill("")
    expect(tr).to_have_count(3)
    expect(ui.page.locator("#llm-log-count")).to_have_text("3 записей")


def test_push_state_appends_llm_log_records_to_ui(ui):
    """ui.push_state() с новой записью llm_log → счётчики статус-бара и
    отладочный лог обновляются без перезагрузки (renderAll → renderLlmLog)."""
    _enable_llm(ui)
    ui.state["llm_log"] = [
        _llm_entry("10.08 14:00", "ИВ", "Ромашка", source="llm", sent=True),
    ]
    ui.state["log"] = []  # без 🤖/LLM-записей — debug-лог пуст до push_state
    ui.open()
    _open_llm_tab(ui)

    expect(ui.page.locator("#llm-st-sources")).to_have_text("🤖1")
    expect(ui.page.locator("#llm-st-interval")).to_contain_text(
        "последний: 10.08 14:00")

    # новая запись llm_log (appendleft → элемент [0]) + запись в activity log
    ui.state["llm_log"].insert(0, _llm_entry(
        "10.08 15:30", "ИВ", "Литех", source="quick_reply", sent=False))
    ui.state["log"].append({
        "time": "15:30:01",
        "acc": "ИВ",
        "color": "cyan",
        "level": "success",
        "neg_id": "555",
        "message": "🤖 Авто-ответ → Литех: Добрый день! Готов подойти…",
    })
    ui.push_state()

    expect(ui.page.locator("#llm-st-sources")).to_have_text("💡1 · 🤖1")
    expect(ui.page.locator("#llm-st-interval")).to_contain_text(
        "последний: 10.08 15:30")
    expect(ui.page.locator("#llm-st-replied")).to_have_text(
        "✅ 1 отправлено · 📝 1 черновиков")
    debug = ui.page.locator("#llm-debug-log")
    expect(debug).to_contain_text("Авто-ответ → Литех")
    expect(debug).to_contain_text("15:30:01")
    expect(ui.page.locator("#llm-debug-count")).to_have_text("(1)")
    expect(debug.locator("a[href='https://hh.ru/chat/555']")).to_have_count(1)


def test_empty_llm_log_empty_state_without_js_errors(ui):
    """Пустой llm_log и пустая БД интервью → empty-state, #dbg-err скрыт."""
    _enable_llm(ui)
    ui.state["llm_log"] = []
    ui.data["interviews"] = []  # дефолт и так [], фиксируем явно
    ui.open()
    _open_llm_tab(ui)

    expect(ui.page.locator("#llm-interviews-table")).to_be_hidden()
    expect(ui.page.locator("#llm-interviews-empty")).to_be_visible()
    expect(ui.page.locator("#llm-interviews-empty")).to_contain_text("Нет данных")
    expect(ui.page.locator("#llm-log-count")).to_have_text("0 записей")
    expect(ui.page.locator("#llm-st-sources")).to_have_text("без ответов")
    expect(ui.page.locator("#llm-st-replied")).to_have_text(
        "✅ 0 отправлено · 📝 0 черновиков")
    expect(ui.page.locator("#llm-st-interval")).to_have_text("🔄 каждые 5м · —")
    # renderAll не упал в catch — иначе #dbg-err показал бы «JS ERROR: …»
    expect(ui.page.locator("#dbg-err")).to_be_hidden()
    assert not ui.page_errors, f"JS-ошибки страницы: {ui.page_errors}"
