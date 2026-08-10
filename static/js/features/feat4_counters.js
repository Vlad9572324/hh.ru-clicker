// feat4_counters.js — extended HH.ru counters в header-dashboard.
//
// Данные: GET /api/account/<idx>/counters_v2 для каждого НЕ-temp аккаунта
// из snapshot'а. Суммы показываются как «💬 N · 📮 N · 👁️ N · 🔔 N».
//
// Автообновление через WebSocket: оборачиваем window.renderHeader(snap) —
// каждый WS-snapshot является триггером, но реальный fetch делается не чаще
// раза в 60 секунд (троттлинг по Date.now); первый раз — сразу.
//
// Загружается ПОСЛЕ app.js. Использует глобалы: esc, State.
// index.html/app.js не правим: CSS подгружается самим скриптом, div
// инжектится в #header после #hdr-resume-stats на DOMContentLoaded.

(function () {
  'use strict';

  // Guard от двойной загрузки / двойного оборачивания.
  if (window.__feat4CountersInstalled) return;
  window.__feat4CountersInstalled = true;

  const REFRESH_MIN_INTERVAL_MS = 60 * 1000; // не чаще раза в 60 секунд
  let lastRefreshAt = 0;
  let refreshInFlight = false;

  const GROUPS = [
    { icon: '💬', key: 'unread_chats', label: 'непрочитанные чаты' },
    { icon: '📮', key: 'unread_negotiations', label: 'непрочитанные переговоры' },
    { icon: '👁️', key: 'new_resume_views', label: 'новые просмотры резюме' },
    { icon: '🔔', key: 'new_notifications', label: 'новые уведомления' },
  ];

  function escSafe(v) {
    return (typeof window.esc === 'function') ? window.esc(v) : String(v);
  }

  function num(v) {
    return (typeof v === 'number' && isFinite(v)) ? v : 0;
  }

  // ── CSS: подгружаем сами, чтобы не трогать index.html ─────────────────
  function injectCss() {
    if (document.getElementById('feat4-counters-css')) return;
    const link = document.createElement('link');
    link.id = 'feat4-counters-css';
    link.rel = 'stylesheet';
    link.href = '/static/css/features/feat4_counters.css';
    document.head.appendChild(link);
  }

  // ── DOM: <div id="feat4-counters"> после #hdr-resume-stats в #header ──
  function ensureEl() {
    let el = document.getElementById('feat4-counters');
    if (el) return el;
    const header = document.getElementById('header');
    if (!header) return null;
    el = document.createElement('div');
    el.id = 'feat4-counters';
    el.className = 'feat4-counters';
    el.style.display = 'none';
    const anchor = document.getElementById('hdr-resume-stats');
    if (anchor && anchor.parentNode === header) {
      anchor.insertAdjacentElement('afterend', el);
    } else {
      header.insertAdjacentElement('beforeend', el);
    }
    return el;
  }

  // ── Рендер сумм (+ разбивка по аккаунтам в title при >1 аккаунте) ─────
  function render(rows) {
    const el = ensureEl();
    if (!el) return;

    const totals = {};
    GROUPS.forEach(g => { totals[g.key] = 0; });
    rows.forEach(row => {
      GROUPS.forEach(g => { totals[g.key] += num(row.counters[g.key]); });
    });

    const anyNonZero = GROUPS.some(g => totals[g.key] > 0);
    if (!anyNonZero) {
      el.style.display = 'none';
      el.innerHTML = '';
      return;
    }

    const multi = rows.length > 1;
    el.innerHTML = GROUPS.map(g => {
      let title = g.label;
      if (multi) {
        title += '\n' + rows.map(r => `${r.name}: ${num(r.counters[g.key])}`).join('\n');
      }
      return `<span class="feat4-counters-group" title="${escSafe(title)}">` +
        `${g.icon} <span class="feat4-counters-val">${totals[g.key]}</span></span>`;
    }).join('<span class="feat4-counters-sep"> · </span>');
    el.style.display = '';
  }

  function fetchOne(idx) {
    return fetch('/api/account/' + encodeURIComponent(idx) + '/counters_v2')
      .then(r => r.json());
  }

  function refresh(snap) {
    if (refreshInFlight) return;
    const accs = ((snap && snap.accounts) || []).filter(a => a && !a.temp);
    if (!accs.length) return; // нет основных аккаунтов — показывать нечего
    refreshInFlight = true;
    Promise.allSettled(accs.map(a => fetchOne(a.idx)))
      .then(settled => {
        const rows = [];
        settled.forEach((s, i) => {
          if (s.status === 'fulfilled' && s.value && s.value.ok && s.value.counters) {
            rows.push({
              idx: accs[i].idx,
              name: accs[i].short || accs[i].name || ('#' + accs[i].idx),
              counters: s.value.counters,
            });
          } else if (s.status === 'rejected') {
            console.debug('feat4-counters: fetch failed idx=' + accs[i].idx, s.reason);
          } else if (s.value && !s.value.ok) {
            console.debug('feat4-counters: endpoint error idx=' + accs[i].idx, s.value.error);
          }
        });
        render(rows);
      })
      .catch(e => console.debug('feat4-counters:', e))
      .finally(() => { refreshInFlight = false; });
  }

  // Троттлинг-триггер: не чаще раза в 60с; первый раз — сразу (lastRefreshAt=0).
  function maybeRefresh(snap) {
    const now = Date.now();
    if (now - lastRefreshAt < REFRESH_MIN_INTERVAL_MS) return;
    lastRefreshAt = now;
    refresh(snap || (window.State && State.lastSnapshot) || {});
  }

  // ── Обёртка window.renderHeader ────────────────────────────────────────
  function wrapRenderHeader() {
    const orig = window.renderHeader;
    if (typeof orig !== 'function' || orig.__feat4Wrapped) return;
    const wrapped = function (snap) {
      const res = orig.apply(this, arguments); // оригинал не блокируем
      try {
        maybeRefresh(snap);
      } catch (e) {
        console.debug('feat4-counters:', e);
      }
      return res;
    };
    wrapped.__feat4Wrapped = true;
    window.renderHeader = wrapped;
  }

  // Скрипт идёт после app.js — renderHeader уже объявлен, оборачиваем сразу,
  // чтобы не пропустить первый snapshot.
  if (typeof window.renderHeader === 'function') wrapRenderHeader();

  document.addEventListener('DOMContentLoaded', () => {
    injectCss();
    ensureEl();
    wrapRenderHeader(); // на случай если app.js зарегистрировал функцию позже
    // Если первый snapshot уже пришёл до нашего DOMContentLoaded — догоняем.
    if (window.State && State.lastSnapshot) maybeRefresh(State.lastSnapshot);
  });
})();
