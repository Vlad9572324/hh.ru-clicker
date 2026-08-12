/*
 * feat5_recommendations.js — «🎯 Рекомендации HH» (possible job offers).
 *
 * Динамически создаёт вкладку + панель без правки index.html:
 *   - <div class="tab" data-tab="recoh"> вставляется в #tabs перед settings;
 *   - <div id="panel-recoh"> вставляется в body перед #panel-settings.
 * Переключение работает через делегированный обработчик #tabs из app.js,
 * свой listener только подгружает данные, если они устарели (>30с) или
 * сменился аккаунт.
 *
 * Загружается ПОСЛЕ app.js: использует window.State, esc(), safeHref()
 * (с локальными fallback'ами на случай отсутствия).
 */
(function () {
  'use strict';

  // ── Guards: не запускаться дважды ─────────────────────────────
  if (window.__feat5RecommendationsLoaded) return;
  window.__feat5RecommendationsLoaded = true;

  var TAB_ID = 'recoh';
  var STALE_MS = 30000;      // данные старее 30с → перезагрузка при открытии
  var APPLY_DELAY_MS = 500;  // пауза между откликами

  // ── Helpers из app.js с fallback ──────────────────────────────
  var _esc = (typeof window.esc === 'function')
    ? window.esc
    : function (s) {
        if (s === null || s === undefined) return '';
        return String(s)
          .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/`/g, '&#96;');
      };
  var _safeHref = (typeof window.safeHref === 'function')
    ? window.safeHref
    : function (u) { return /^https?:\/\//i.test(String(u || '')) ? String(u) : '#'; };

  // ── Локальное состояние ───────────────────────────────────────
  var state = {
    loadedAt: 0,         // ts последней успешной загрузки
    loadedAccIdx: null,  // для какого аккаунта загружена таблица
    offers: [],          // [{vacancy_id, name, employer, url}]
    applying: false,
    loading: false,
  };

  function $(id) { return document.getElementById(id); }

  function getAccounts() {
    var snap = window.State && window.State.lastSnapshot;
    var accs = (snap && snap.accounts) || [];
    // Раньше фильтровали `!a.temp` — но mobile OTP-логин создаёт ИМЕННО
    // temp-account'ы (a.temp=true), для них /api/account/{idx}/hh_recommendations
    // работает через bot._get_apply_acc. Юзер видел пустой dropdown при
    // единственном mobile-аккаунте. Оставляем только не-удалённые.
    return accs.filter(function (a) { return a && !a._deleted; });
  }

  function currentAccIdx() {
    var sel = $('feat5-account');
    if (!sel || !sel.options.length) return null;
    var v = parseInt(sel.value, 10);
    return isNaN(v) ? null : v;
  }

  // ── CSS: подтягиваем свой stylesheet (CSP style-src 'self' ок) ─
  function cssInject() {
    if ($('feat5-css')) return;
    var link = document.createElement('link');
    link.id = 'feat5-css';
    link.rel = 'stylesheet';
    link.href = '/static/css/features/feat5_recommendations.css';
    document.head.appendChild(link);
  }

  // ── Вкладка ───────────────────────────────────────────────────
  function buildTab() {
    var tabs = document.getElementById('tabs');
    if (!tabs || tabs.querySelector('.tab[data-tab="' + TAB_ID + '"]')) return;
    var tab = document.createElement('div');
    tab.className = 'tab';
    tab.setAttribute('data-tab', TAB_ID);
    tab.textContent = '🎯 Рекомендации HH';
    var settingsTab = tabs.querySelector('.tab[data-tab="settings"]');
    if (settingsTab) tabs.insertBefore(tab, settingsTab);
    else tabs.appendChild(tab);
    // Переключение обработает делегирование #tabs из app.js;
    // здесь только подгрузка данных.
    tab.addEventListener('click', onTabOpen);
  }

  // ── Панель ────────────────────────────────────────────────────
  function buildPanel() {
    if ($('panel-' + TAB_ID)) return;
    var panel = document.createElement('div');
    panel.id = 'panel-' + TAB_ID;
    panel.className = 'panel';
    panel.innerHTML =
      '<div class="feat5-box">' +
        '<div class="feat5-title">🎯 Рекомендации HH</div>' +
        '<div class="feat5-desc">Вакансии, которые сам HH подобрал под резюме аккаунта. ' +
          'Можно отправить отклики на все одной кнопкой (вакансии с опросом пропускаются).</div>' +
        '<div class="feat5-controls">' +
          '<select id="feat5-account" class="feat5-select"></select>' +
          '<button id="feat5-refresh" class="feat5-btn" type="button">↻ Загрузить</button>' +
          '<button id="feat5-autoapply" class="feat5-btn feat5-btn-primary" type="button" disabled>🚀 auto-apply на все</button>' +
          '<span id="feat5-progress" class="feat5-progress"></span>' +
        '</div>' +
        '<div id="feat5-status" class="feat5-status"></div>' +
        '<div class="feat5-table-wrap">' +
          '<table class="feat5-table">' +
            '<thead><tr>' +
              '<th>Вакансия</th><th>Работодатель</th><th>Ссылка</th><th>Статус auto-apply</th>' +
            '</tr></thead>' +
            '<tbody id="feat5-tbody"></tbody>' +
          '</table>' +
        '</div>' +
      '</div>';

    var anchor = $('panel-settings') || $('panel-llm');
    if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(panel, anchor);
    else document.body.appendChild(panel);

    var refreshBtn = $('feat5-refresh');
    if (refreshBtn) refreshBtn.addEventListener('click', function () { loadOffers(); });
    var applyBtn = $('feat5-autoapply');
    if (applyBtn) applyBtn.addEventListener('click', function () { autoApplyAll(); });
    var sel = $('feat5-account');
    if (sel) sel.addEventListener('change', onAccountChange);
  }

  // ── Select аккаунтов (из State.lastSnapshot, только не-temp) ──
  function buildAccountSelect() {
    var sel = $('feat5-account');
    if (!sel) return;
    var accs = getAccounts();
    var newKey = accs.map(function (a) { return a.idx + ':' + a.name; }).join(',');
    if (sel.dataset.builtKey === newKey) return;
    sel.dataset.builtKey = newKey;
    var prev = sel.value;
    sel.innerHTML = accs.length
      ? accs.map(function (a) {
          return '<option value="' + _esc(a.idx) + '">' + _esc(a.name) + '</option>';
        }).join('')
      : '<option value="">— нет аккаунтов —</option>';
    if (prev && sel.querySelector('option[value="' + prev + '"]')) sel.value = prev;
  }

  function onAccountChange() {
    // Сменили аккаунт — таблица больше не актуальна
    if (state.loadedAccIdx !== null && state.loadedAccIdx !== currentAccIdx()) {
      state.offers = [];
      state.loadedAccIdx = null;
      state.loadedAt = 0;
      renderRows();
      setStatus('Выберите «↻ Загрузить», чтобы получить рекомендации для этого аккаунта', 'info');
    }
  }

  // ── Открытие вкладки: подгрузка, если данные устарели ─────────
  function onTabOpen() {
    if (state.applying || state.loading) return;
    buildAccountSelect();
    var accIdx = currentAccIdx();
    if (accIdx === null) return;
    var stale = (Date.now() - state.loadedAt) > STALE_MS;
    if (stale || state.loadedAccIdx !== accIdx) loadOffers();
  }

  // ── Статусная строка ──────────────────────────────────────────
  function setStatus(html, kind) {
    var el = $('feat5-status');
    if (!el) return;
    el.className = 'feat5-status' + (kind ? ' feat5-status-' + kind : '');
    el.innerHTML = html || '';
  }

  function mapApiError(data, httpStatus) {
    var err = data && data.error;
    if (err === 'no_oauth_token') return 'нет OAuth-токена для этого аккаунта';
    if (err) return err;
    return 'HTTP ' + httpStatus;
  }

  // ── Загрузка рекомендаций ─────────────────────────────────────
  function loadOffers() {
    if (state.applying) {
      setStatus('⏳ Идёт auto-apply — дождитесь завершения', 'warn');
      return;
    }
    if (state.loading) return;
    buildAccountSelect();
    var accIdx = currentAccIdx();
    if (accIdx === null) {
      state.offers = [];
      renderRows();
      setStatus('Нет аккаунтов — добавьте аккаунт на вкладке «Настройки»', 'err');
      return;
    }
    state.loading = true;
    var refreshBtn = $('feat5-refresh');
    if (refreshBtn) refreshBtn.disabled = true;
    setStatus('⏳ Загружаю рекомендации HH…', 'info');

    fetch('/api/account/' + accIdx + '/hh_recommendations')
      .then(function (res) {
        return res.json().catch(function () { return {}; })
          .then(function (data) { return { res: res, data: data }; });
      })
      .then(function (out) {
        var res = out.res, data = out.data;
        if (!res.ok || !data.ok) {
          state.offers = [];
          state.loadedAccIdx = null;
          renderRows();
          setStatus('❌ ' + _esc(mapApiError(data, res.status)), 'err');
          return;
        }
        state.offers = Array.isArray(data.offers) ? data.offers : [];
        state.loadedAt = Date.now();
        state.loadedAccIdx = accIdx;
        renderRows();
        if (data.found > 0) {
          setStatus('Найдено рекомендаций: <b>' + data.found + '</b>', 'ok');
        } else {
          setStatus('HH ничего не порекомендовал для этого аккаунта (пустой список)', 'info');
        }
      })
      .catch(function (e) {
        setStatus('❌ Ошибка запроса: ' + _esc(e), 'err');
      })
      .then(function () {
        state.loading = false;
        if (refreshBtn) refreshBtn.disabled = false;
      });
  }

  // ── Таблица ───────────────────────────────────────────────────
  function renderRows() {
    var tbody = $('feat5-tbody');
    if (!tbody) return;
    if (!state.offers.length) {
      tbody.innerHTML = '<tr class="feat5-empty"><td colspan="4">— нет данных —</td></tr>';
    } else {
      tbody.innerHTML = state.offers.map(function (o) {
        var vid = _esc(o.vacancy_id);
        return '<tr data-vid="' + vid + '">' +
          '<td>' + _esc(o.name || '(без названия)') + '</td>' +
          '<td>' + _esc(o.employer || '—') + '</td>' +
          '<td><a href="' + _safeHref(o.url) + '" target="_blank" rel="noopener noreferrer">hh.ru/vacancy/' + vid + '</a></td>' +
          '<td class="feat5-apply-status">—</td>' +
        '</tr>';
      }).join('');
    }
    var applyBtn = $('feat5-autoapply');
    if (applyBtn) applyBtn.disabled = state.applying || !state.offers.length;
    var progress = $('feat5-progress');
    if (progress && !state.applying) progress.textContent = '';
  }

  function statusCellFor(vid) {
    var tbody = $('feat5-tbody');
    if (!tbody) return null;
    var row = tbody.querySelector('tr[data-vid="' + String(vid).replace(/"/g, '') + '"]');
    return row ? row.querySelector('.feat5-apply-status') : null;
  }

  // ── auto-apply на все ─────────────────────────────────────────
  function applyStatusRender(st) {
    switch (st) {
      case 'sent':          return { text: '✅ отправлен', cls: 'feat5-st-ok' };
      case 'already':       return { text: '🔄 уже', cls: 'feat5-st-warn' };
      case 'limit':         return { text: '🚫 лимит', cls: 'feat5-st-err' };
      case 'test_required': return { text: '📝 требует опрос — пропущено', cls: 'feat5-st-warn' };
      default:              return { text: '❌', cls: 'feat5-st-err' };
    }
  }

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function autoApplyAll() {
    if (state.applying || state.loading || !state.offers.length) return;
    var accIdx = currentAccIdx();
    if (accIdx === null) {
      setStatus('Сначала выберите аккаунт', 'err');
      return;
    }

    state.applying = true;
    var applyBtn = $('feat5-autoapply');
    var refreshBtn = $('feat5-refresh');
    var sel = $('feat5-account');
    if (applyBtn) applyBtn.disabled = true;
    if (refreshBtn) refreshBtn.disabled = true;
    if (sel) sel.disabled = true;

    var total = state.offers.length;
    var counts = { sent: 0, already: 0, limit: 0, test_required: 0, error: 0 };
    var done = 0;
    var progress = $('feat5-progress');
    if (progress) progress.textContent = '0/' + total;
    setStatus('🚀 auto-apply: отправляю отклики…', 'info');

    var chain = Promise.resolve();
    state.offers.forEach(function (off, i) {
      chain = chain.then(function () {
        var cell = statusCellFor(off.vacancy_id);
        if (cell) { cell.textContent = '⏳…'; cell.className = 'feat5-apply-status feat5-st-pending'; }
        return fetch('/api/apply/check', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            account_idx: accIdx,
            vacancy_id: String(off.vacancy_id),
            letter: '',
          }),
        })
          .then(function (res) { return res.json().catch(function () { return {}; }); })
          .then(function (data) {
            var st = (data && data.status) ? data.status : 'error';
            if (!(st in counts)) st = 'error';
            counts[st] += 1;
            var r = applyStatusRender(data && data.status);
            if (cell) { cell.textContent = r.text; cell.className = 'feat5-apply-status ' + r.cls; }
          })
          .catch(function () {
            counts.error += 1;
            var r = applyStatusRender('error');
            if (cell) { cell.textContent = r.text; cell.className = 'feat5-apply-status ' + r.cls; }
          })
          .then(function () {
            done += 1;
            if (progress) progress.textContent = done + '/' + total;
            // пауза между запросами, чтобы не спамить HH
            if (i < total - 1) return sleep(APPLY_DELAY_MS);
          });
      });
    });

    chain.then(function () {
      var parts = [
        '✅ отправлено: ' + counts.sent,
        '🔄 уже: ' + counts.already,
        '🚫 лимит: ' + counts.limit,
        '📝 опрос (пропущено): ' + counts.test_required,
        '❌ ошибки: ' + counts.error,
      ];
      setStatus('Готово ' + done + '/' + total + ' — ' + parts.join(' · '), 'ok');
      state.applying = false;
      if (applyBtn) applyBtn.disabled = !state.offers.length;
      if (refreshBtn) refreshBtn.disabled = false;
      if (sel) sel.disabled = false;
    });
  }

  // ── Init ──────────────────────────────────────────────────────
  function init() {
    cssInject();
    buildTab();
    buildPanel();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
