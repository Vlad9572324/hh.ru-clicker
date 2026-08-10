/*
 * feat1_hr_badge.js — HR-ranking badge в списке вакансий (вкладка 📂 База).
 *
 * Грузится ПОСЛЕ app.js. Оборачивает window.dbFillTable (которая рисует
 * строки таблицы #db-tbody) и после отрисовки инжектит в ячейку со ссылкой
 * на вакансию badge:
 *   🟢 живой HR (N мин назад)  — HR активен менее 60 минут
 *   🔴 конвейер (N дн)         — HR давно не активен
 *   ❔ HR?                     — данных нет / backend недоступен
 *
 * Данные лениво подгружаются через /api/vacancy/<vid>/hr_activity:
 * клиентский кэш (Promise per vid) + не более 3 параллельных fetch.
 *
 * Экспорт для других фич: window.HRBadges = {fetch(vid), renderInto(el, data)}.
 */
(function () {
  'use strict';

  // Guard от повторной загрузки скрипта (двойное оборачивание dbFillTable).
  if (window.__feat1HrBadgeLoaded) return;
  window.__feat1HrBadgeLoaded = true;

  const MAX_PARALLEL = 3;
  const _cache = new Map(); // vid -> Promise<data|null>
  const _queue = [];
  let _active = 0;

  // esc() — глобальный helper app.js; fallback чтобы не падать без него.
  const _esc = (typeof window.esc === 'function')
    ? window.esc
    : (s) => String(s === null || s === undefined ? '' : s);

  // <60 мин → «N мин», <48 ч → «N ч», дальше «N дн».
  function fmtDuration(mins) {
    const m = Number(mins);
    if (!Number.isFinite(m) || m < 0) return '';
    if (m < 60) return `${Math.round(m)} мин`;
    const h = Math.floor(m / 60);
    if (h < 48) return `${h} ч`;
    return `${Math.floor(h / 24)} дн`;
  }

  // Очередь с ограничением параллельности (≤ MAX_PARALLEL fetch одновременно).
  function _pump() {
    while (_active < MAX_PARALLEL && _queue.length > 0) {
      const job = _queue.shift();
      _active += 1;
      Promise.resolve()
        .then(job)
        .catch(() => {})
        .then(() => { _active -= 1; _pump(); });
    }
  }

  /**
   * Fetch HR-данных по vid с клиентским кэшем.
   * @param {string|number} vid
   * @returns {Promise<object|null>} payload backend'а или null (нет данных/сети)
   */
  function fetchHr(vid) {
    vid = String(vid === null || vid === undefined ? '' : vid).trim();
    if (!vid) return Promise.resolve(null);
    if (_cache.has(vid)) return _cache.get(vid);
    const p = new Promise((resolve) => {
      _queue.push(() => fetch(`/api/vacancy/${encodeURIComponent(vid)}/hr_activity`)
        .then((r) => (r && r.ok ? r.json() : null))
        .catch(() => null)
        .then((data) => resolve(data && typeof data === 'object' ? data : null)));
    });
    _cache.set(vid, p);
    _pump();
    return p;
  }

  /**
   * Рендер badge в элемент по данным backend'а.
   * data == null / не ok → «❔ HR?».
   */
  function renderInto(el, data) {
    if (!el) return;
    try {
      let cls = 'feat1-hr-badge feat1-hr-badge--unknown';
      let text = '❔ HR?';
      const mins = data ? data.manager_inactive_minutes : null;
      if (data && data.ok === true && data.badge === 'live') {
        cls = 'feat1-hr-badge feat1-hr-badge--live';
        text = `🟢 живой HR (${fmtDuration(mins)} назад)`;
      } else if (data && data.ok === true && data.badge === 'pipeline') {
        cls = 'feat1-hr-badge feat1-hr-badge--pipeline';
        text = `🔴 конвейер (${fmtDuration(mins)})`;
      }
      el.innerHTML = `<span class="${cls}" title="Активность HR по вакансии">${_esc(text)}</span>`;
    } catch (e) { /* badge декоративный — рендер таблицы ломать нельзя */ }
  }

  // vid строки: стабильнее всего из delete-кнопки (data-vid всегда рисуется
  // dbFillTable), fallback — ссылка hh.ru/vacancy/<id>.
  function _rowVid(row) {
    try {
      const btn = row.querySelector('button[data-vid]');
      if (btn) {
        const v = (btn.getAttribute('data-vid') || '').trim();
        if (v) return v;
      }
      const a = row.querySelector('a[href*="/vacancy/"]');
      if (a) {
        const m = String(a.getAttribute('href') || '').match(/vacancy\/(\d+)/);
        if (m) return m[1];
      }
    } catch (e) {}
    return '';
  }

  // Ячейка для инжекта: ячейка со ссылкой hh.ru/vacancy/ (3-я колонка dbFillTable).
  function _badgeCell(row) {
    try {
      const a = row.querySelector('a[href*="/vacancy/"]');
      if (a) {
        const td = a.closest('td');
        if (td) return td;
      }
      if (row.children && row.children.length > 2) return row.children[2];
    } catch (e) {}
    return null;
  }

  function injectBadges() {
    try {
      const tbody = document.getElementById('db-tbody');
      if (!tbody) return;
      const rows = tbody.querySelectorAll('tr');
      for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        if (!row || row.querySelector('.feat1-hr-badge')) continue; // уже инжектнут
        const vid = _rowVid(row);
        if (!vid) continue;
        const cell = _badgeCell(row);
        if (!cell) continue;
        const slot = document.createElement('span');
        slot.className = 'feat1-hr-slot';
        renderInto(slot, null); // пока грузим — «❔ HR?»
        cell.appendChild(slot);
        fetchHr(vid).then((data) => {
          // строку могли перерисовать (innerHTML reset) — обновляем только живую
          if (slot.isConnected) renderInto(slot, data);
        }).catch(() => {});
      }
    } catch (e) { /* никогда не ломать отрисовку таблицы */ }
  }

  // Обёртка dbFillTable (app.js): после отрисовки строк инжектим badge.
  // Флаг на функции — guard от двойного оборачивания.
  if (!(typeof window.dbFillTable === 'function' && window.dbFillTable.__feat1Wrapped)) {
    const _origDbFill = window.dbFillTable;
    const wrapped = function (...args) {
      const r = _origDbFill ? _origDbFill.apply(this, args) : undefined;
      injectBadges();
      return r;
    };
    wrapped.__feat1Wrapped = true;
    window.dbFillTable = wrapped;
  }

  // Если таблица уже была отрисована до загрузки скрипта — подхватываем её.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(injectBadges, 0));
  } else {
    setTimeout(injectBadges, 0);
  }

  window.HRBadges = { fetch: fetchHr, renderInto };
})();
