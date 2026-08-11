"""E2E: WebSocket toggle в Настройках (Feature 8, subagent_8).

Секция #ws-realtime-section (⚙️ Настройки → 📡 WebSocket):
- клик «▶ Вкл» в строке аккаунта → POST /api/ws/0/enable (запись в ui.calls),
  после чего список перерисовывается и появляется точка-индикатор feat8;
- глобальный чекбокс #feat8-ws-global-cb → WS-команда
  {"type":"set_config","key":"use_websocket_realtime","value":...}
  (точное равенство dict в ui.commands), плюс синхронизация чекбокса
  из state["config"]["use_websocket_realtime"].

Тесты используют изолированную Playwright-страницу из e2e/conftest.py и
проверяют фактический UI-контракт без sleep и недетерминированного polling.
"""

from playwright.sync_api import expect


# Форма ответа GET /api/ws/status — 1:1 с app/ws_manager.py status().
def _ws_status_body(enabled=False, status="disabled", global_flag=False):
    return {
        "ok": True,
        "use_websocket_realtime": global_flag,
        "accounts": {
            "0": {
                "enabled": enabled,
                "status": status,
                "events_total": 0,
                "last_event_type": None,
                "last_event_at": None,
            }
        },
    }


def _wait_until(ui, predicate, timeout=6.0, message="condition"):
    """Bounded polling для python-списков ui.calls/ui.commands (через
    ui.wait_until → page.wait_for_timeout, а не time.sleep: route-обработчики
    playwright крутятся только пока качаются события)."""
    try:
        ui.wait_until(predicate, timeout=timeout, message="ok")
    except AssertionError:
        raise AssertionError(f"timeout {timeout}s waiting for {message}")


def _open_ws_section(ui):
    """Вкладка Настройки → раскрыть <details> #ws-realtime-section."""
    page = ui.page
    page.locator('.tab[data-tab="settings"]').click()
    expect(page.locator("#panel-settings")).to_be_visible()
    # секция — <details> без open; раскрываем кликом по summary
    page.locator("#ws-realtime-section > summary").click()
    expect(page.locator("#ws-realtime-section")).to_have_attribute("open", "")
    return page


def _boot(ui, global_flag=False, status_body=None):
    ui.state.setdefault("config", {})["use_websocket_realtime"] = global_flag
    ui.set_response(
        "GET",
        r"/api/ws/status",
        body=status_body or _ws_status_body(global_flag=global_flag),
    )
    ui.open()
    return _open_ws_section(ui)


# ── 1. клик «▶ Вкл» → POST /api/ws/{idx}/enable + индикатор ───────────────

def test_ws_enable_button_posts_enable(ui):
    page = _boot(ui)  # аккаунт выключен, статус disabled (тело из ТЗ)
    ui.set_response(
        "POST",
        r"/api/ws/0/enable$",
        body={"ok": True, "enabled": True, "status": "disabled_global"},
    )

    # строка аккаунта с бейджем статуса отрисовалась (retry-рендер inline-скрипта)
    btn_on = page.locator("#ws-acc-list button", has_text="Вкл")
    expect(btn_on).to_be_visible(timeout=15000)
    expect(page.locator("#ws-badge-0")).to_have_text("disabled")

    btn_on.click()

    _wait_until(
        ui,
        lambda: any(
            c["method"] == "POST" and c["path"] == "/api/ws/0/enable"
            for c in ui.calls
        ),
        timeout=5,
        message="POST /api/ws/0/enable",
    )
    # после toggle inline-wsToggle заново вызывает wsRender — список перерисован,
    # feat8-обёртка добавила точку-индикатор рядом с бейджем
    dot = page.locator("#ws-acc-list .feat8-dot")
    expect(dot).to_have_count(1)
    # статус в моке по-прежнему disabled → серая точка
    expect(dot).to_have_class("feat8-dot feat8-dot-off")


def test_ws_disable_button_posts_disable(ui):
    page = _boot(
        ui,
        status_body=_ws_status_body(enabled=True, status="disabled_global"),
    )
    ui.set_response(
        "POST",
        r"/api/ws/0/disable$",
        body={"ok": True, "enabled": False, "status": "disabled"},
    )

    btn_off = page.locator("#ws-acc-list button", has_text="Выкл")
    expect(btn_off).to_be_visible(timeout=15000)
    btn_off.click()

    _wait_until(
        ui,
        lambda: any(
            c["method"] == "POST" and c["path"] == "/api/ws/0/disable"
            for c in ui.calls
        ),
        timeout=5,
        message="POST /api/ws/0/disable",
    )


# ── 2. индикатор коннекта по статусу из /api/ws/status ────────────────────

def test_ws_status_indicator_connected_green(ui):
    page = _boot(
        ui,
        global_flag=True,
        status_body=_ws_status_body(enabled=True, status="connected", global_flag=True),
    )
    expect(page.locator("#ws-badge-0")).to_be_visible(timeout=15000)
    dot = page.locator("#ws-acc-list .feat8-dot")
    expect(dot).to_have_count(1)
    expect(dot).to_have_class("feat8-dot feat8-dot-connected")


# ── 3. глобальный чекбокс → set_config через WS ───────────────────────────

def test_ws_global_checkbox_sends_set_config(ui):
    page = _boot(ui, global_flag=False)
    cb = page.locator("#feat8-ws-global-cb")
    expect(cb).to_be_visible(timeout=15000)
    expect(cb).not_to_be_checked()  # синхронизирован с config=False

    cb.check()  # False → True
    _wait_until(
        ui,
        lambda: {"type": "set_config", "key": "use_websocket_realtime",
                 "value": True} in ui.commands,
        timeout=5,
        message="set_config use_websocket_realtime=true",
    )
    assert {"type": "set_config", "key": "use_websocket_realtime",
            "value": True} in ui.commands

    cb.uncheck()  # True → False (инверсия в обе стороны)
    _wait_until(
        ui,
        lambda: {"type": "set_config", "key": "use_websocket_realtime",
                 "value": False} in ui.commands,
        timeout=5,
        message="set_config use_websocket_realtime=false",
    )


def test_ws_global_checkbox_syncs_from_snapshot(ui):
    """config.use_websocket_realtime=true в снапшоте → чекбокс взведён."""
    page = _boot(ui, global_flag=True)
    cb = page.locator("#feat8-ws-global-cb")
    expect(cb).to_be_visible(timeout=15000)
    # expect сам повторяет DOM-проверку до timeout. Это важно: снапшот приходит
    # асинхронно по WS, но тест не должен вручную крутить event loop страницы.
    expect(cb).to_be_checked(timeout=5000)
