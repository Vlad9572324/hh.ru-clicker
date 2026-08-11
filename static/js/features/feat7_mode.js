/*
 * feat7_mode.js — per-account mode selector (auto / web / mobile) + badge effective-mode.
 *
 * Backend: GET/PUT /api/account/{idx}/mode (app/routes/account_mode.py).
 *   - PUT сохраняет mode в accounts.json или browser_sessions.json;
 *     GET нужен для инициализации dropdown.
 *
 * Интеграция (без правок app.js): оборачиваем window.buildSessList,
 * window.buildAccCookiesList и window.updateCard — вызов оригинала сохраняется,
 * добавляем своё после. Скрипт грузится ПОСЛЕ app.js (функции app.js — глобальные).
 *
 * Режим-редактор вставляется в двух местах:
 *   - Настройки → 🌐 Браузерные сессии (#sess-list, блоки #sess-row-<idx>) — как есть;
 *   - Настройки → 🔑 Обновить куки аккаунтов (#acc-cookies-list) — настоящий список
 *     ОСНОВНЫХ аккаунтов; блоки без id, ищем по textarea#ck-ta-<idx>, temp пропускаем.
 */
(function () {
  'use strict';

  // Guard от двойного оборачивания (повторная загрузка скрипта / dev-reload).
  if (window.__feat7ModeInstalled) return;
  window.__feat7ModeInstalled = true;

  var MODES = ['auto', 'web', 'mobile'];
  var MODE_TITLES = {
    auto: 'бот сам выбирает (сейчас всегда web)',
    web: 'cookies hh.ru (классика)',
    mobile: 'OAuth api.hh.ru (Android-приложение)'
  };

  // idx -> {mode, effective_client} | {error: true} (кэш в памяти, fetch 1 раз на аккаунт)
  var modeCache = {};
  // idx -> Promise (in-flight guard: параллельные updateCard не плодят запросы)
  var modeInflight = {};

  function fetchMode(idx) {
    if (modeCache[idx]) return Promise.resolve(modeCache[idx]);
    if (modeInflight[idx]) return modeInflight[idx];
    var p = fetch('/api/account/' + idx + '/mode')
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          if (res.ok && data && data.ok) {
            modeCache[idx] = { mode: data.mode, effective_client: data.effective_client };
          } else {
            modeCache[idx] = { error: true, status: res.status };
          }
          return modeCache[idx];
        });
      })
      .catch(function () {
        modeCache[idx] = { error: true };
        return modeCache[idx];
      })
      .then(function (entry) {
        delete modeInflight[idx];
        return entry;
      });
    modeInflight[idx] = p;
    return p;
  }

  function effectiveShort(entry) {
    if (!entry || entry.error) return '';
    return entry.effective_client === 'MobileHHClient' ? 'MOBILE' : 'WEB';
  }

  // State в app.js объявлен как top-level const — виден здесь как глобальный
  // lexical binding (скрипт грузится ПОСЛЕ app.js); возможный ReferenceError
  // (скрипт до app.js / TDZ) ловим в catch.
  function lastSnapshotAccounts() {
    try {
      var accs = State && State.lastSnapshot && State.lastSnapshot.accounts;
      return Array.isArray(accs) ? accs : null;
    } catch (e) {
      return null;
    }
  }

  // Множество idx temp-сессий (нужно, чтобы не дублировать редактор в списках).
  function tempIdxSet(snap) {
    var set = {};
    var accs = (snap && Array.isArray(snap.accounts)) ? snap.accounts : lastSnapshotAccounts();
    (accs || []).forEach(function (a) {
      if (a && a.temp) set[a.idx] = true;  // числовой idx → строковый ключ объекта
    });
    return set;
  }

  // ── Badge на карточке аккаунта ────────────────────────────────────
  function ensureBadge(card, idx) {
    var badge = card.querySelector('.feat7-mode-badge');
    if (badge) return badge;
    var header = card.querySelector('.acc-header');
    if (!header) return null;
    badge = document.createElement('span');
    badge.className = 'feat7-mode-badge';
    badge.id = 'feat7-mode-badge-' + idx;
    badge.style.display = 'none';
    header.appendChild(badge);
    return badge;
  }

  function renderBadge(card, idx) {
    var badge = ensureBadge(card, idx);
    if (!badge) return;
    var entry = modeCache[idx];
    if (!entry || entry.error) { badge.style.display = 'none'; return; }
    badge.style.display = '';
    badge.classList.remove('feat7-mode-web', 'feat7-mode-mobile', 'feat7-mode-auto');
    if (entry.mode === 'auto') {
      badge.textContent = 'AUTO';
      badge.classList.add('feat7-mode-auto');
      badge.title = 'effective: ' + effectiveShort(entry);
    } else if (entry.mode === 'mobile') {
      badge.textContent = 'MOBILE';
      badge.classList.add('feat7-mode-mobile');
      badge.title = 'mode: mobile (OAuth api.hh.ru)';
    } else {
      badge.textContent = 'WEB';
      badge.classList.add('feat7-mode-web');
      badge.title = 'mode: web (cookies hh.ru)';
    }
  }

  function updateBadgeForIdx(idx) {
    var card = document.getElementById('card-' + idx);
    if (card) renderBadge(card, idx);
  }

  // ── Общая строка mode-редактора: <select> + «💾 mode» + статус ────
  // Всё через DOM API / textContent — HTML-инъекции нет (esc не нужен).
  function makeModeRow(idx) {
    var wrap = document.createElement('div');
    wrap.className = 'feat7-mode-row';

    var label = document.createElement('span');
    label.className = 'feat7-mode-row-label';
    label.textContent = 'mode:';

    var sel = document.createElement('select');
    sel.className = 'feat7-mode-select apply-input';
    MODES.forEach(function (m) {
      var opt = document.createElement('option');
      opt.value = m;
      opt.textContent = m;
      opt.title = MODE_TITLES[m];
      sel.appendChild(opt);
    });

    var btn = document.createElement('button');
    btn.className = 'btn-sm feat7-mode-save';
    btn.textContent = '💾 mode';

    var st = document.createElement('span');
    st.className = 'feat7-mode-st';

    wrap.appendChild(label);
    wrap.appendChild(sel);
    wrap.appendChild(btn);
    wrap.appendChild(st);

    // Выбранный режим — из текущего (GET при первом рендере, кэш в памяти).
    fetchMode(idx).then(function (entry) {
      if (entry && !entry.error && MODES.indexOf(entry.mode) !== -1) {
        sel.value = entry.mode;
      }
    });

    btn.addEventListener('click', function () {
      btn.disabled = true;
      st.style.color = 'var(--dim)';
      st.textContent = '⏳ сохраняю...';
      fetch('/api/account/' + idx + '/mode', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: sel.value })
      })
        .then(function (res) {
          return res.json().catch(function () { return {}; }).then(function (data) {
            if (res.ok && data && data.ok) {
              modeCache[idx] = { mode: data.mode, effective_client: data.effective_client };
              st.style.color = 'var(--green)';
              st.textContent = '✅ ' + data.mode + ' → ' + (data.effective_client || '');
              updateBadgeForIdx(idx);
            } else {
              st.style.color = 'var(--red)';
              st.textContent = '❌ ' + ((data && data.error) || ('HTTP ' + res.status));
            }
          });
        })
        .catch(function (e) {
          st.style.color = 'var(--red)';
          st.textContent = '❌ ' + e;
        })
        .then(function () { btn.disabled = false; });
    });

    return wrap;
  }

  // ── Обёртка updateCard: badge effective mode ──────────────────────
  // updateCard вызывается на каждый snapshot (~0.3s) — поэтому badge
  // создаём один раз (ensureBadge) и только обновляем текст/класс из кэша.
  // fetch делаем ОДИН раз на аккаунт (modeCache), не на каждый updateCard.
  var origUpdateCard = window.updateCard;
  if (typeof origUpdateCard === 'function') {
    window.updateCard = function (card, acc) {
      var r = origUpdateCard.apply(this, arguments);
      try {
        if (card && acc && typeof acc.idx !== 'undefined') {
          renderBadge(card, acc.idx);
          if (!modeCache[acc.idx] && !modeInflight[acc.idx]) {
            fetchMode(acc.idx).then(function () { renderBadge(card, acc.idx); });
          }
        }
      } catch (e) { /* feat7 не должен ломать обновление карточек */ }
      return r;
    };
  }

  // ── Обёртка buildSessList: dropdown mode в блоках сессий ──────────
  // После оригинала добавляем в каждый блок (#sess-row-<idx>) строку mode.
  // Guard: .feat7-mode-row уже есть → skip (оригинал при неизменном
  // fingerprint innerHTML не пересобирает).
  var origBuildSessList = window.buildSessList;
  if (typeof origBuildSessList === 'function') {
    window.buildSessList = function (snap) {
      var r = origBuildSessList.apply(this, arguments);
      try { decorateSessList(snap); } catch (e) { /* feat7: sess-list не критичен */ }
      return r;
    };
  }

  function decorateSessList(snap) {
    var sessions = ((snap && snap.accounts) || []).filter(function (a) { return a && a.temp; });
    sessions.forEach(function (acc) {
      var row = document.getElementById('sess-row-' + acc.idx);
      if (!row || row.querySelector('.feat7-mode-row')) return;
      row.appendChild(makeModeRow(acc.idx));
    });
  }

  // ── Обёртка buildAccCookiesList: dropdown mode у ОСНОВНЫХ аккаунтов ──
  // #acc-cookies-list — список аккаунтов в Настройках
  // (buildAccCookiesList рендерит блок на каждый аккаунт snapshot'а: имя,
  // textarea#ck-ta-<idx>, flex-строка с кнопкой обновления кук; id у блоков нет).
  // Блоки пересоздаются при смене числа аккаунтов → идемпотентность по
  // .feat7-mode-row внутри блока. Temp пропускаем здесь, потому что их mode
  // уже редактируется в отдельном списке браузерных сессий.
  var origBuildAccCookiesList = window.buildAccCookiesList;
  if (typeof origBuildAccCookiesList === 'function') {
    window.buildAccCookiesList = function (snap) {
      var r = origBuildAccCookiesList.apply(this, arguments);
      try { decorateAccCookiesList(snap); } catch (e) { /* feat7: acc-cookies не критичен */ }
      return r;
    };
  }

  function decorateAccCookiesList(snap) {
    var el = document.getElementById('acc-cookies-list');
    if (!el) return;
    var tempSet = tempIdxSet(snap);
    var tas = el.querySelectorAll('textarea[id^="ck-ta-"]');
    Array.prototype.forEach.call(tas, function (ta) {
      var idx = ta.id.slice('ck-ta-'.length);
      if (!idx || tempSet[idx]) return;            // temp-аккаунты — вне scope endpoint'а
      var block = ta.parentElement;                 // блок аккаунта (div без id)
      if (!block || block.querySelector('.feat7-mode-row')) return;
      // Строка mode — в конце блока, сразу после flex-строки с кнопкой обновления кук.
      block.appendChild(makeModeRow(idx));
    });
  }

  // Если скрипт загрузился позже первого snapshot'а (карточки уже в DOM) —
  // дорисовываем badge для существующих основных аккаунтов.
  try {
    var snapAccounts = lastSnapshotAccounts();
    if (snapAccounts) {
      snapAccounts.forEach(function (acc) {
        if (acc) {
          var card = document.getElementById('card-' + acc.idx);
          if (card && !modeCache[acc.idx] && !modeInflight[acc.idx]) {
            fetchMode(acc.idx).then(function () { renderBadge(card, acc.idx); });
          }
        }
      });
    }
  } catch (e) { /* опциональный путь — не критично */ }
})();
