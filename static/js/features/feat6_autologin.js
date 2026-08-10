// feat6_autologin.js — Autologin bridge: кнопка «🔗 web-сессия» в блоках
// браузерных сессий (Настройки → 🌐 Браузерные сессии, #sess-list).
//
// POST /api/account/<idx>/autologin_url → одноразовый URL вида
// https://hh.ru/?loginkey=<KEY> для входа в web без пароля. Ключ ОДНОРАЗОВЫЙ:
// каждый клик запрашивает новый URL.
//
// Грузится ПОСЛЕ app.js. Оборачивает window.buildSessList и добавляет кнопку
// в каждый блок сессии; index.html/app.js не модифицируются.
(function () {
  'use strict';

  // Guard от двойной загрузки/оборачивания.
  if (window.__feat6AutologinLoaded) return;
  window.__feat6AutologinLoaded = true;

  var CSS_ID = 'feat6-autologin-css';
  var RESULT_CLASS = 'feat6-result';

  // ── helpers ────────────────────────────────────────────────────────────────

  function esc(s) {
    if (s === null || s === undefined) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
      .replace(/`/g, '&#96;');
  }

  function injectCss() {
    if (document.getElementById(CSS_ID)) return;
    var link = document.createElement('link');
    link.id = CSS_ID;
    link.rel = 'stylesheet';
    link.href = '/static/css/features/feat6_autologin.css';
    document.head.appendChild(link);
  }

  var ERROR_LABELS = {
    no_oauth_token: 'нет OAuth-токена — аккаунт не авторизован',
    invalid_idx: 'аккаунт не найден',
    no_key_in_response: 'HH не вернул ключ — попробуйте позже',
    me_failed: 'HH /me вернул ошибку — попробуйте позже',
    me_request_failed: 'сеть: не удалось запросить HH /me',
    autologin_failed: 'HH вернул ошибку при получении ключа',
    autologin_request_failed: 'сеть: не удалось получить ключ',
    internal_error: 'внутренняя ошибка бота'
  };

  function errorLabel(err) {
    return ERROR_LABELS[err] || err || 'неизвестная ошибка';
  }

  // Публичный API: получить одноразовый autologin-URL для аккаунта idx.
  async function getUrl(idx) {
    var res = await fetch('/api/account/' + encodeURIComponent(idx) + '/autologin_url', {
      method: 'POST'
    });
    var data = {};
    try { data = await res.json(); } catch (e) { /* не-JSON тело */ }
    if (!res.ok || !data.ok) {
      throw new Error(data.error || ('HTTP ' + res.status));
    }
    return data;
  }

  async function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (e) { /* fallback ниже */ }
    }
    // Fallback: временный textarea + execCommand('copy').
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    return ok;
  }

  // ── определение idx блока ──────────────────────────────────────────────────

  function idxFromBlock(block) {
    // Основной путь: id блока «sess-row-<idx>» (см. buildSessList в app.js).
    if (block.id) {
      var m = /^sess-row-(\d+)$/.exec(block.id);
      if (m) return parseInt(m[1], 10);
    }
    // Fallback: onclick-атрибуты кнопок sessActivate/sessEditToggle/... внутри блока.
    var btns = block.querySelectorAll('button[onclick]');
    for (var i = 0; i < btns.length; i++) {
      var attr = btns[i].getAttribute('onclick') || '';
      var m2 = /(?:sessActivate|sessRefresh|sessEditToggle|sessionRemove|updateCookiesFromTextarea)\((\d+)/.exec(attr);
      if (m2) return parseInt(m2[1], 10);
    }
    return null;
  }

  // ── рендер результата под блоком ───────────────────────────────────────────

  function setResultStatus(statusEl, text, color) {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.style.color = color || 'var(--dim)';
  }

  function renderResult(block, idx, url) {
    // Повторный клик: заменяем прежний результат (старый ключ уже невалиден).
    var prev = block.querySelector('.' + RESULT_CLASS);
    if (prev) prev.remove();

    var box = document.createElement('div');
    box.className = RESULT_CLASS;

    var note = document.createElement('div');
    note.className = 'feat6-note';
    note.textContent = 'Одноразовый ключ: URL сработает один раз. Повторный клик — новый ключ.';
    box.appendChild(note);

    var urlEl = document.createElement('code');
    urlEl.className = 'feat6-url';
    urlEl.textContent = url; // textContent — безопасно без esc
    box.appendChild(urlEl);

    var actions = document.createElement('div');
    actions.className = 'feat6-actions';

    var copyBtn = document.createElement('button');
    copyBtn.className = 'btn-sm feat6-btn';
    copyBtn.textContent = '📋 Копировать';
    copyBtn.addEventListener('click', async function () {
      var ok = await copyText(url);
      setResultStatus(statusEl, ok ? '✅ Скопировано в буфер' : '❌ Не удалось скопировать',
        ok ? 'var(--green)' : 'var(--red)');
      if (ok) setTimeout(function () { setResultStatus(statusEl, '', ''); }, 4000);
    });

    var openBtn = document.createElement('button');
    openBtn.className = 'btn-sm feat6-btn';
    openBtn.textContent = '↗ Открыть';
    openBtn.addEventListener('click', function () {
      try {
        window.open(url, '_blank', 'noopener');
        setResultStatus(statusEl, '✅ Открыто в новой вкладке', 'var(--green)');
      } catch (e) {
        setResultStatus(statusEl, '❌ Браузер заблокировал открытие окна', 'var(--red)');
      }
    });

    var statusEl = document.createElement('span');
    statusEl.className = 'feat6-status';

    actions.appendChild(copyBtn);
    actions.appendChild(openBtn);
    actions.appendChild(statusEl);
    box.appendChild(actions);
    block.appendChild(box);
  }

  // ── клик по кнопке «🔗 web-сессия» ─────────────────────────────────────────

  async function onOpen(idx, block, btn, statusEl) {
    btn.disabled = true;
    setResultStatus(statusEl, '⏳ Получаем одноразовый ключ…', 'var(--dim)');
    try {
      var data = await getUrl(idx);
      setResultStatus(statusEl, '', '');
      renderResult(block, idx, data.url);
    } catch (e) {
      setResultStatus(statusEl, '❌ Ошибка: ' + errorLabel(e && e.message), 'var(--red)');
    } finally {
      btn.disabled = false;
    }
  }

  // ── декорирование блоков в #sess-list ─────────────────────────────────────

  function decorate() {
    var list = document.getElementById('sess-list');
    if (!list) return;
    var blocks = list.children;
    for (var i = 0; i < blocks.length; i++) {
      var block = blocks[i];
      if (!block || block.nodeType !== 1) continue;
      if (block.dataset && block.dataset.feat6 === '1') continue; // уже декорирован
      var idx = idxFromBlock(block);
      if (idx === null || isNaN(idx)) continue; // placeholder «Нет сессий» и т.п.

      if (block.dataset) {
        block.dataset.feat6 = '1';
        block.dataset.feat6Idx = String(idx);
      }

      var bar = document.createElement('div');
      bar.className = 'feat6-bar';

      var btn = document.createElement('button');
      btn.className = 'btn-sm feat6-btn';
      btn.textContent = '🔗 web-сессия';
      btn.title = 'Одноразовый URL для входа в web-версию hh.ru без пароля';

      var statusEl = document.createElement('span');
      statusEl.className = 'feat6-status';

      (function (idx_, block_, btn_, statusEl_) {
        btn_.addEventListener('click', function () { onOpen(idx_, block_, btn_, statusEl_); });
      })(idx, block, btn, statusEl);

      bar.appendChild(btn);
      bar.appendChild(statusEl);
      block.appendChild(bar);
    }
  }

  // ── декорирование блоков ОСНОВНЫХ аккаунтов в #acc-cookies-list ───────────
  // buildAccCookiesList (app.js) рисует блок на каждый аккаунт: имя,
  // textarea#ck-ta-<idx>, flex-строка с кнопкой updateAccCookies(<idx>) и
  // span#ck-st-<idx>. Кнопку инжектим в ту же flex-строку.

  // idx temp-сессий (для них эндпоинт вернёт 404 — кнопку не ставим,
  // если snapshot доступен; иначе backend вернёт ошибку, это тоже ок).
  function tempIdxSet(snap) {
    var accs = (snap && snap.accounts) || null;
    if (!accs && typeof State !== 'undefined' && State && State.lastSnapshot) {
      accs = State.lastSnapshot.accounts || [];
    }
    var set = {};
    (accs || []).forEach(function (a) {
      if (a && a.temp) set[a.idx] = true;
    });
    return set;
  }

  function decorateAccCookies(snap) {
    var list = document.getElementById('acc-cookies-list');
    if (!list) return;
    var skip = tempIdxSet(snap);
    // Блок ищем по textarea#ck-ta-<idx> (сам блок без id).
    var tas = list.querySelectorAll('textarea[id^="ck-ta-"]');
    for (var i = 0; i < tas.length; i++) {
      var ta = tas[i];
      var m = /^ck-ta-(\d+)$/.exec(ta.id);
      if (!m) continue;
      var idx = parseInt(m[1], 10);
      if (isNaN(idx) || skip[idx]) continue; // temp-сессия — пропускаем
      var block = ta.closest('div');
      if (!block) continue;
      // Идемпотентность: список перерисовывается при смене числа аккаунтов,
      // но при живых блоках кнопку не дублируем.
      if (block.querySelector('.feat6-acc-btn')) continue;

      var btn = document.createElement('button');
      btn.className = 'btn-sm feat6-btn feat6-acc-btn';
      btn.textContent = '🔗 web-сессия';
      btn.title = 'Одноразовый URL для входа в web-версию hh.ru без пароля';

      var statusEl = document.createElement('span');
      statusEl.className = 'feat6-status';

      // Целевой контейнер — flex-строка с кнопкой «Обновить куки»;
      // fallback: сам блок.
      var cookieBtn = block.querySelector('button[onclick*="updateAccCookies("]');
      var target = (cookieBtn && cookieBtn.parentElement) || block;

      (function (idx_, block_, btn_, statusEl_) {
        btn_.addEventListener('click', function () { onOpen(idx_, block_, btn_, statusEl_); });
      })(idx, block, btn, statusEl);

      target.appendChild(btn);
      target.appendChild(statusEl);
    }
  }

  // ── обёртки buildSessList / buildAccCookiesList (index.html/app.js не трогаем) ──

  var orig = window.buildSessList;
  if (typeof orig === 'function' && !orig.__feat6Wrapped) {
    var wrapped = function (snap) {
      var ret = orig.apply(this, arguments);
      try {
        decorate();
      } catch (e) {
        if (window.console) console.warn('[feat6] decorate error:', e);
      }
      return ret;
    };
    wrapped.__feat6Wrapped = true;
    window.buildSessList = wrapped;
  }

  var origAcc = window.buildAccCookiesList;
  if (typeof origAcc === 'function' && !origAcc.__feat6Wrapped) {
    var wrappedAcc = function (snap) {
      var ret = origAcc.apply(this, arguments);
      try {
        decorateAccCookies(snap);
      } catch (e) {
        if (window.console) console.warn('[feat6] decorateAccCookies error:', e);
      }
      return ret;
    };
    wrappedAcc.__feat6Wrapped = true;
    window.buildAccCookiesList = wrappedAcc;
  }

  // Стартовый проход: списки могли быть построены до загрузки этого скрипта.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      injectCss(); decorate(); decorateAccCookies(null);
    });
  } else {
    injectCss();
    decorate();
    decorateAccCookies(null);
  }

  // Публичный API.
  window.Feat6Autologin = { getUrl: getUrl };
})();
