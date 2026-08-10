"""Smoke-тесты самой E2E-инфраструктуры (фикстуры из conftest.py).

Проверяют контракт, против которого другие агенты пишут тесты:
  1. static + WS connect (#conn-dot.connected)
  2. дефолтный ui.state рендерит header/карточку аккаунта без JS-ошибок
  3. sendCmd уходит через WS в ui.commands
  4. HTTP-моки: POST записывается в ui.calls + работает set_response
"""


def test_static_and_ws_connect(ui):
    """ui.open() -> страница загрузилась, WS подключился (#conn-dot.connected)."""
    ui.open()
    dot = ui.page.locator("#conn-dot")
    assert "connected" in (dot.get_attribute("class") or "").split()
    # идемпотентность open(): повторный вызов не падает и ничего не ломает
    ui.open()
    assert "connected" in (ui.page.locator("#conn-dot").get_attribute("class") or "").split()


def test_state_renders(ui):
    """После ui.open() header и карточка аккаунта отражают дефолтный ui.state."""
    ui.open()
    gs = ui.state["global_stats"]
    acc = ui.state["accounts"][0]

    # renderHeader: #global-found / #global-sent
    assert ui.page.locator("#global-found").text_content().strip() == str(gs["total_found"])
    assert ui.page.locator("#global-sent").text_content().strip() == str(gs["total_sent"])
    # uptime отрендерен из снапшота (3661c -> "1ч 01м", не дефолтный "00:00")
    assert "00:00" not in ui.page.locator("#uptime").text_content()
    # renderAccounts: карточка аккаунта с именем из снапшота
    assert ui.page.locator("#card-0").count() == 1
    assert ui.page.locator("#acc-name-0").text_content().strip() == acc["name"]
    # счётчик sent карточки (updateCard -> #acc-sent-0)
    assert ui.page.locator("#acc-sent-0").text_content().strip() == str(acc["sent"])
    # дефолтный state не должен порождать window-level JS-ошибки
    assert ui.page_errors == []


def test_sendcmd_via_ws(ui):
    """Клик #pause-btn -> sendCmd({type:'pause_toggle'}) -> запись в ui.commands."""
    ui.open()
    assert ui.commands == []
    ui.page.click("#pause-btn")
    ui.wait_until(
        lambda: {"type": "pause_toggle"} in ui.commands,
        timeout=5,
        message="pause_toggle не пришёл на WS-сервер",
    )
    assert {"type": "pause_toggle"} in ui.commands


def test_http_mock_records_post(ui):
    """fetch POST: override через set_response + дефолт {"ok":true}; записи в ui.calls."""
    ui.open()
    ui.set_response("POST", r"/api/backup$", body={"ok": True, "mocked_marker": 123})

    res = ui.page.evaluate(
        """async () => {
            const r = await fetch('/api/backup', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({src: 'smoke', n: 42})
            });
            return {status: r.status, body: await r.json()};
        }"""
    )
    assert res["status"] == 200
    assert res["body"]["mocked_marker"] == 123

    backup_calls = [c for c in ui.calls if c["path"] == "/api/backup" and c["method"] == "POST"]
    assert len(backup_calls) == 1
    assert backup_calls[0]["json"] == {"src": "smoke", "n": 42}

    # POST без override -> 200 {"ok": true}
    res2 = ui.page.evaluate(
        """async () => {
            const r = await fetch('/api/pause', {method: 'POST'});
            return {status: r.status, body: await r.json()};
        }"""
    )
    assert res2["status"] == 200
    assert res2["body"] == {"ok": True}
    assert {"method": "POST", "path": "/api/pause", "json": None} in ui.calls

    # GET без мока -> 404 {"error": "not mocked"}
    res3 = ui.page.evaluate(
        """async () => {
            const r = await fetch('/api/definitely/not/mocked');
            return {status: r.status, body: await r.json()};
        }"""
    )
    assert res3["status"] == 404
    assert res3["body"] == {"error": "not mocked"}

    # GET из ui.data: /api/proxy/info
    res4 = ui.page.evaluate(
        """async () => {
            const r = await fetch('/api/proxy/info');
            return await r.json();
        }"""
    )
    assert res4 == ui.data["proxy_info"]
