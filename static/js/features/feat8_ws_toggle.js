/*
 * Feature 8: WebSocket toggle (уточнение inline-скрипта index.html).
 *
 * Загружается ПОСЛЕ <script src="/static/js/app.js"> и ПОСЛЕ inline-скрипта
 * в конце index.html (там объявлены wsRender/wsToggle/wsRefresh/wsFetchStatus
 * и WS_BADGE_COLORS), поэтому только ОБЁРТЫВАЕТ существующие глобальные
 * функции и ИНЖЕКТИТ недостающие элементы — разметку и app.js не меняет.
 *
 * Что добавляет:
 *   1. Глобальный чекбокс #feat8-ws-global-cb («Глобально use_websocket_realtime»)
 *      в секцию #ws-realtime-section: onchange шлёт
 *      sendCmd({type:'set_config', key:'use_websocket_realtime', value: checked}),
 *      состояние синхронизируется из State.lastSnapshot.config.use_websocket_realtime
 *      (обёртки wsRender и renderAll).
 *   2. Точку-индикатор коннекта рядом с #ws-badge-<idx> после каждого рендера:
 *      зелёная = connected; жёлтая = connecting/reconnecting;
 *      красная = error/no_token; серая = disabled/disabled_global/неизвестно.
 *   3. Публичный API: window.WsToggle = { refresh, getStatus }.
 *
 * Ничего не ломает, если секция отсутствует (другая вкладка), State пуст или
 * inline-функции не объявлены; повторная загрузка скрипта идемпотентна
 * (guard на window.__FEAT8_WS_TOGGLE__ + метки на обёртках).
 */
(function () {
  'use strict';

  // Guard от двойной загрузки/двойного оборачивания.
  if (window.__FEAT8_WS_TOGGLE__) return;
  window.__FEAT8_WS_TOGGLE__ = true;

  var DOT_CHAR = '\u25CF'; // ●

  // Последний успешный ответ GET /api/ws/status (ловим обёрткой wsFetchStatus) —
  // источник статусов для индикаторов.
  var lastStatus = null;

  function safe(fn, fallback) {
    try { return fn(); } catch (e) { return fallback; }
  }

  // Обернуть window[name]; orig отсутствует или уже обёрнут — no-op.
  function wrapGlobal(name, makeWrapper) {
    var orig = window[name];
    if (typeof orig !== 'function' || orig.__feat8_wrapped) return;
    var wrapped = makeWrapper(orig);
    try { wrapped.__feat8_wrapped = true; } catch (e) { /* ignore */ }
    window[name] = wrapped;
  }

  // ── Индикаторы коннекта ──────────────────────────────────────────────

  function dotClassForStatus(status) {
    if (status === 'connected') return 'feat8-dot-connected';
    if (status === 'connecting' || status === 'reconnecting') return 'feat8-dot-pending';
    if (status === 'error' || status === 'no_token') return 'feat8-dot-error';
    return 'feat8-dot-off'; // disabled / disabled_global / неизвестно
  }

  function statusForIdx(idx, badgeText) {
    var accs = safe(function () { return lastStatus && lastStatus.accounts; }, null);
    if (accs && accs[idx] && typeof accs[idx].status === 'string' && accs[idx].status) {
      return accs[idx].status;
    }
    return (badgeText || '').trim(); // fallback: текст бейджа = статус
  }

  // Оригинальный wsRender каждый раз перестраивает #ws-acc-list, поэтому
  // точки создаются заново после каждого рендера — дубли невозможны.
  function updateIndicators() {
    var list = document.getElementById('ws-acc-list');
    if (!list) return; // секции нет (другая вкладка) — тихо выходим
    var badges = list.querySelectorAll('[id^="ws-badge-"]');
    for (var i = 0; i < badges.length; i++) {
      var badge = badges[i];
      var idx = badge.id.slice('ws-badge-'.length);
      var status = statusForIdx(idx, badge.textContent);
      var dot = document.createElement('span');
      dot.className = 'feat8-dot ' + dotClassForStatus(status);
      dot.setAttribute('data-feat8-idx', idx);
      dot.title = 'WS-слушатель: ' + (status || 'неизвестно');
      dot.textContent = DOT_CHAR;
      badge.insertAdjacentElement('afterend', dot);
    }
  }

  // ── Глобальный чекбокс use_websocket_realtime ────────────────────────

  function snapshotConfigValue() {
    return safe(function () {
      var snap = window.State && window.State.lastSnapshot;
      return snap && snap.config ? snap.config.use_websocket_realtime : undefined;
    }, undefined);
  }

  // Выставить чекбокс из снапшота, если значение известно (boolean).
  function syncGlobalCheckbox() {
    var cb = document.getElementById('feat8-ws-global-cb');
    if (!cb) return;
    var val = snapshotConfigValue();
    if (typeof val === 'boolean' && cb.checked !== val) cb.checked = val;
  }

  function injectGlobalToggle() {
    var section = document.getElementById('ws-realtime-section');
    if (!section) return; // секции нет — не ломаемся
    if (document.getElementById('feat8-ws-global-cb')) return; // уже инжектнут
    var flagEl = document.getElementById('ws-global-flag');
    var block = (flagEl && flagEl.parentElement) || null; // flex-строка с флагом
    if (!block) return;

    var label = document.createElement('label');
    label.className = 'feat8-global-label';

    var cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.id = 'feat8-ws-global-cb';
    cb.addEventListener('change', function () {
      safe(function () {
        if (typeof window.sendCmd === 'function') {
          window.sendCmd({
            type: 'set_config',
            key: 'use_websocket_realtime',
            value: cb.checked
          });
        }
      }, null);
    });

    var text = document.createElement('span');
    text.className = 'feat8-global-text';
    text.textContent = 'Глобально use_websocket_realtime';

    var hint = document.createElement('span');
    hint.className = 'feat8-global-hint';
    hint.textContent = 'слушатели стартуют после \u25B6 Вкл / рестарта бота';

    label.appendChild(cb);
    label.appendChild(text);
    label.appendChild(hint);

    // Держим кнопку «↻ Обновить» (margin-left:auto) последней в flex-строке.
    var btn = block.querySelector('button');
    if (btn && btn.parentElement === block) {
      block.insertBefore(label, btn);
    } else {
      block.appendChild(label);
    }

    syncGlobalCheckbox();
  }

  // ── Обёртки ───────────────────────────────────────────────────────────

  // Запоминаем последний успешный статус — для индикаторов и WsToggle.
  wrapGlobal('wsFetchStatus', function (orig) {
    return function () {
      return Promise.resolve(orig.apply(this, arguments)).then(function (data) {
        if (data && data.ok && data.accounts) lastStatus = data;
        return data;
      });
    };
  });

  // После оригинального рендера: точки-индикаторы + синхронизация чекбокса.
  wrapGlobal('wsRender', function (orig) {
    return function () {
      return Promise.resolve(orig.apply(this, arguments)).then(function (res) {
        safe(updateIndicators, null);
        safe(syncGlobalCheckbox, null);
        return res;
      });
    };
  });

  // Каждый WS snapshot (renderAll) синхронизирует чекбокс с config'ом —
  // чтобы откат сервером значения был виден без ожидания 15-сек polling'а.
  wrapGlobal('renderAll', function (orig) {
    return function () {
      var res = orig.apply(this, arguments);
      safe(syncGlobalCheckbox, null);
      return res;
    };
  });

  // ── Публичный API ─────────────────────────────────────────────────────

  window.WsToggle = {
    // Совместимо с wsRefresh(btn) из inline-скрипта index.html.
    refresh: function (btn) {
      return typeof window.wsRefresh === 'function' ? window.wsRefresh(btn) : undefined;
    },
    // Promise с ответом GET /api/ws/status.
    getStatus: function () {
      return typeof window.wsFetchStatus === 'function'
        ? window.wsFetchStatus()
        : Promise.resolve({ ok: false, error: 'wsFetchStatus недоступен' });
    }
  };

  // ── Старт ─────────────────────────────────────────────────────────────

  function init() {
    safe(injectGlobalToggle, null);
    safe(syncGlobalCheckbox, null);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init(); // скрипт выполнен после парсинга DOM — инжектим сразу
  }
})();
