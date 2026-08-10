"""E2E: таб «Главная» (.tab[data-tab="main"], #panel-main).

Факты из static/js/app.js + static/index.html (проверено):
- Аккаунты рендерятся в #accounts-grid как .acc-card#card-{idx}
  (renderAccounts → buildCardHTML/updateCard). Пустое состояние —
  динамически создаваемый #accounts-empty с текстом t('no_accounts').
- ВАЖНО: buildCardHTML рисует счётчики/бейдж статуса дефолтами (0 / «ОЖИДАНИЕ»);
  реальные значения подставляет updateCard, который вызывается ТОЛЬКО для уже
  существующих карточек — т.е. со ВТОРОГО снапшота. Поэтому тесты карточек
  делают ui.open() + ui.push_state() (повторная отправка того же стейта).
- Header: #global-found/#global-sent/#storage-total/#storage-tests из
  snap.global_stats (renderHeader, работает с первого снапшота).
- #pause-btn → sendCmd({type:'pause_toggle'}). При snap.paused текст
  t('btn_resume')='▶ Продолжить (все)' + класс 'paused'; иначе '⏸ Пауза'.
- #apply-mode-badge → sendCmd({type:'set_config', key:'use_oauth_apply',
  value:!State.lastSnapshot.config.use_oauth_apply}). Текст: '🌐 Web' /
  '🔑 OAuth (все)' (config.use_oauth_apply) / '🔑 OAuth (N/M)' (по аккаунтам).
- Temp-сессия отличается полями acc.temp + acc.bot_active: pending
  (temp=true, bot_active=false) показывает кнопки «▶ Запустить»
  (sessionActivate → POST /api/session/{idx}/activate) и «✕ Удалить»,
  а также блок выбора резюме #acc-resume-wrap-{idx}.
- Ошибка рендера снапшота ловится в ws.onmessage и показывается в #dbg-err
  ('JS ERROR: ...'). renderGlobalStats/renderRecentResponses падают без
  snap.global_stats / snap.recent_responses — в стейте они обязательны.
"""

from playwright.sync_api import expect


def _base_config(**over):
    # Минимально полный конфиг: renderAll читает эти ключи в sync*-функциях.
    cfg = {
        "use_oauth_apply": False,
        "daily_apply_limit": 0,
        "filter_agencies": False,
        "filter_low_competition": False,
        "search_period_days": 0,
        "skip_inconsistent": False,
        "letter_templates": [],
        "url_pool": [],
        "allowed_schedules": [],
        "title_include_keywords": [],
        "title_exclude_keywords": [],
        "llm_enabled": False,
        "llm_auto_send": False,
        "llm_check_interval": 5,
        "llm_profiles": [],
        "llm_system_prompt": "",
        "llm_api_key_set": False,
        "min_salary": 0,
    }
    cfg.update(over)
    return cfg


def _account(idx=0, name="user1", **over):
    # Форма аккаунта — как в app/manager.py get_full_state().
    acc = {
        "idx": idx, "name": name, "short": name[:8], "color": "yellow",
        "temp": False, "bot_active": True,
        "status": "idle", "status_detail": "",
        "sent": 0, "total_applied": 0, "tests": 0, "errors": 0,
        "already_applied": 0, "found_vacancies": 0,
        "current_vacancy_title": "", "current_vacancy_company": "",
        "current_vacancy_idx": 0, "total_vacancies": 0,
        "salary_skipped": 0, "questionnaire_sent": 0,
        "limit_exceeded": False, "paused": False,
        "next_resume_touch": "", "resume_touch_status": "",
        "resume_touch_enabled": True,
        "letter": "", "urls": [], "url_pages": {},
        "hh_interviews": 0, "hh_interviews_recent": 0, "hh_viewed": 0,
        "hh_discards": 0, "hh_not_viewed": 0, "hh_unread_by_employer": 0,
        "hh_stats_updated": "", "hh_stats_loading": False,
        "hh_interviews_list": [], "hh_possible_offers": [],
        "action_history": [],
        "resume_views_7d": 0, "resume_views_new": 0, "resume_shows_7d": 0,
        "resume_invitations_7d": 0, "resume_invitations_new": 0,
        "resume_next_touch_seconds": 0, "resume_free_touches": 0,
        "resume_global_invitations": 0, "resume_new_invitations_total": 0,
        "acc_event_log": [],
        "apply_tests": False, "consecutive_errors": 0, "url_stats": {},
        "cookies_expired": False,
        "degraded_mode": False, "degraded_skipped": 0,
        "degraded_fallback_enabled": True, "resume_status_oauth": {},
        "hh_today_applies": 0, "hh_today_applies_updated": "",
        "hh_daily_limit": 200,
        "responses_streak_count": 0, "responses_streak_required": 0,
        "oauth_status": {}, "llm_enabled": True, "use_oauth": False,
        "daily_sent": 0, "daily_limit": 0, "hard_stopped": False,
        "last_apply_at": "", "last_apply_attempt_at": "", "paused_reason": "",
        "all_resumes": [], "resume_hash": "",
    }
    acc.update(over)
    return acc


def _state(accounts=None, **over):
    st = {
        "uptime_seconds": 3600,
        "paused": False,
        "accounts": accounts if accounts is not None else [],
        "recent_responses": [],
        "log": [],
        "llm_log": [],
        "config": _base_config(),
        "global_stats": {
            "total_found": 0, "total_sent": 0, "total_tests": 0,
            "total_errors": 0, "storage_total": 0, "storage_tests": 0,
        },
        "vacancy_queues": {},
    }
    st.update(over)
    return st


def _install_state(ui, state):
    # Перезаписываем ключи по одному, не подменяя объект ui.state.
    for k, v in state.items():
        ui.state[k] = v


def _cmds(commands, **match):
    """WS-команды страницы, у которых все ключи match совпадают."""
    return [
        c for c in commands
        if all(c.get(k) == v for k, v in match.items())
    ]


def _expect_cmd(ui, **match):
    """Ждём WS-команду в ui.commands через ui.wait_until (expect() не умеет
    poll python-объектов) и возвращаем найденные."""
    ui.wait_until(
        lambda: _cmds(ui.commands, **match),
        message=f"WS-команда {match} не пришла",
    )
    return _cmds(ui.commands, **match)


def test_empty_state_no_accounts_no_js_errors(ui):
    """accounts: [] → #accounts-empty, карточек нет, рендер без JS-ошибок."""
    page_errors = []
    ui.page.on("pageerror", lambda e: page_errors.append(str(e)))
    _install_state(ui, _state(accounts=[]))
    ui.open()

    empty = ui.page.locator("#accounts-empty")
    expect(empty).to_be_visible()
    expect(empty).to_contain_text("Нет аккаунтов")
    expect(ui.page.locator("#accounts-grid .acc-card")).to_have_count(0)
    # Ошибка renderAll показывается в #dbg-err ('JS ERROR: ...') — её нет.
    expect(ui.page.locator("#dbg-err")).to_be_hidden()
    assert page_errors == [], f"непойманные JS-ошибки страницы: {page_errors}"


def test_single_account_renders_login_and_counters(ui):
    """Один аккаунт: имя(логин), счётчики карточки и header-статистика."""
    acc = _account(
        idx=0, name="ivan@example.com",
        sent=7, total_applied=42, tests=3, already_applied=5, errors=1,
    )
    state = _state(accounts=[acc])
    state["global_stats"] = {
        "total_found": 120, "total_sent": 7, "total_tests": 3,
        "total_errors": 2, "storage_total": 500, "storage_tests": 12,
    }
    _install_state(ui, state)
    ui.open()
    # Второй снапшот: счётчики подставляет updateCard (только для
    # уже созданных карточек) — эмулируем следующий периодческий broadcast.
    ui.push_state()

    p = ui.page
    expect(p.locator("#acc-name-0")).to_have_text("ivan@example.com")
    expect(p.locator("#acc-sent-0")).to_have_text("7")
    expect(p.locator("#acc-total-0")).to_have_text("42")
    expect(p.locator("#acc-tests-0")).to_have_text("3")
    expect(p.locator("#acc-already-0")).to_have_text("5")
    expect(p.locator("#acc-err-0")).to_have_text("1")
    # Статус не paused → 'ОЖИДАНИЕ'
    expect(p.locator("#acc-badge-0")).to_contain_text("ОЖИДАНИЕ")
    # Header-статистика из global_stats (рендерится с первого снапшота)
    expect(p.locator("#global-found")).to_have_text("120")
    expect(p.locator("#global-sent")).to_have_text("7")
    expect(p.locator("#storage-total")).to_have_text("500")
    expect(p.locator("#storage-tests")).to_have_text("12")
    expect(p.locator("#global-stats-body")).to_contain_text("120")
    # Sidebar «Последние отклики»: пусто → placeholder
    expect(p.locator("#recent-list")).to_contain_text("Ожидание откликов")
    # Не temp-сессия → блока выбора резюме и кнопок сессии быть не должно
    expect(p.locator("#acc-resume-wrap-0")).to_have_count(0)


def test_multiple_accounts_all_rendered(ui):
    """Несколько аккаунтов (4) → все карточки отрисованы в #accounts-grid."""
    accs = [_account(idx=i, name=f"acc_login_{i}") for i in range(4)]
    _install_state(ui, _state(accounts=accs))
    ui.open()

    grid_cards = ui.page.locator("#accounts-grid .acc-card")
    expect(grid_cards).to_have_count(4)
    for i in range(4):
        expect(ui.page.locator(f"#card-{i}")).to_be_visible()
        expect(ui.page.locator(f"#acc-name-{i}")).to_have_text(f"acc_login_{i}")
    expect(ui.page.locator("#accounts-empty")).to_have_count(0)


def test_temp_session_pending_shows_launch_controls(ui):
    """Temp-сессия pending (temp=true, bot_active=false): «Запустить»/«Удалить»
    и блок выбора резюме; кнопки «Стоп» нет (бот не активен)."""
    acc = _account(
        idx=0, name="temp_session_1",
        temp=True, bot_active=False, status="—",
        resume_hash="deadbeef01",
        all_resumes=[{"hash": "deadbeef01", "title": "Backend-разработчик"}],
    )
    _install_state(ui, _state(accounts=[acc]))
    ui.open()

    card = ui.page.locator("#card-0")
    expect(card).to_be_visible()
    expect(card.locator(".acc-name")).to_have_text("temp_session_1")
    # pending → кнопка запуска (sessionActivate) и удаления (sessionRemove)
    expect(card.locator(".acc-actions button", has_text="Запустить")).to_have_count(1)
    expect(card.locator(".acc-actions button", has_text="Удалить")).to_have_count(1)
    expect(card.locator(".acc-actions button", has_text="Стоп")).to_have_count(0)
    # У temp-аккаунта есть блок выбора резюме с его резюме
    resume_wrap = ui.page.locator("#acc-resume-wrap-0")
    expect(resume_wrap).to_have_count(1)
    expect(ui.page.locator("#acc-resume-sel-0")).to_contain_text("Backend-разработчик")


def test_pause_button_sends_pause_toggle(ui):
    """Клик #pause-btn → WS-команда {"type":"pause_toggle"}."""
    _install_state(ui, _state(accounts=[_account(idx=0)]))
    ui.open()

    btn = ui.page.locator("#pause-btn")
    expect(btn).to_have_text("⏸ Пауза")  # бот не на паузе
    assert _cmds(ui.commands, type="pause_toggle") == []
    btn.click()

    pause_cmds = _expect_cmd(ui, type="pause_toggle")
    assert len(pause_cmds) == 1, f"ожидалась ровно 1 команда: {ui.commands}"


def test_apply_mode_badge_toggles_oauth_config(ui):
    """Клик #apply-mode-badge → set_config use_oauth_apply с инверсией;
    новый стейт с включённым OAuth → badge меняет текст и цвет."""
    state = _state(accounts=[_account(idx=0, use_oauth=False)])
    assert state["config"]["use_oauth_apply"] is False
    _install_state(ui, state)
    ui.open()

    badge = ui.page.locator("#apply-mode-badge")
    expect(badge).to_have_text("🌐 Web")
    bg_before = badge.evaluate("el => getComputedStyle(el).backgroundColor")
    assert bg_before.replace(" ", "") == "rgba(57,208,216,0.15)"

    badge.click()
    # Инверсия текущего false → value=true
    cfg_cmds = _expect_cmd(ui, type="set_config", key="use_oauth_apply", value=True)
    assert len(cfg_cmds) == 1, f"ожидалась ровно 1 команда: {ui.commands}"

    # Бэкенд «применил» конфиг → UI перерисовывает badge
    ui.state["config"]["use_oauth_apply"] = True
    ui.push_state()
    expect(badge).to_have_text("🔑 OAuth (все)")
    bg_after = badge.evaluate("el => getComputedStyle(el).backgroundColor")
    assert bg_after.replace(" ", "") == "rgba(63,185,80,0.15)"


def test_paused_bot_pause_button_reflects_state(ui):
    """paused=true → кнопка «▶ Продолжить (все)» с классом paused,
    бейдж аккаунта «⏸ ВСЕ НА ПАУЗЕ»."""
    state = _state(accounts=[_account(idx=0)], paused=True)
    _install_state(ui, state)
    ui.open()

    btn = ui.page.locator("#pause-btn")
    expect(btn).to_have_text("▶ Продолжить (все)")
    assert "paused" in (btn.get_attribute("class") or "").split()

    # Глобальная пауза на бейдже аккаунта — через updateCard (2-й снапшот)
    ui.push_state()
    expect(ui.page.locator("#acc-badge-0")).to_have_text("⏸ ВСЕ НА ПАУЗЕ")
