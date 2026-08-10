/*
 * feat2_preflight.js — Pre-flight check «чего не хватает в резюме» перед откликом.
 *
 * Грузится ПОСЛЕ app.js. Не трогает index.html/app.js — оборачивает глобалы:
 *   window.applyCheck  — перед оригиналом делает GET
 *     /api/account/{idx}/vacancy/{vid}/data_inconsistency:
 *       required непустой → badge ⚠️ + Feat2Preflight.blocked=true + НЕ вызывает оригинал;
 *       ok=true (готово/skipped) → badge ✅, затем вызывает оригинал;
 *       ошибка проверки → просто вызывает оригинал без badge.
 *   window.applySubmit — если blocked → warn и return (кнопка заблокирована).
 * blocked сбрасывается при изменении #apply-vacancy / #apply-account
 * и при каждом новом запуске applyCheck.
 */
(function () {
  'use strict';

  // Guard от двойного оборачивания (скрипт может быть подключён повторно).
  if (window.Feat2Preflight && window.Feat2Preflight.installed) return;

  const NS = {
    installed: true,
    blocked: false,
    blockedHumanized: [],
  };
  window.Feat2Preflight = NS;

  function safeEsc(s) {
    return (typeof esc === 'function') ? esc(s) : String(s == null ? '' : s);
  }

  function show(msg, type) {
    if (typeof applyShowResult === 'function') applyShowResult(msg, type);
    const el = document.getElementById('apply-result');
    // applyShowResult перезаписывает className — помечаем badge нашим классом
    // (feat2-preflight.css); оригинальный flow сам сотрёт класс при перерисовке.
    if (el) el.classList.add('feat2-preflight-badge');
  }

  function warnBadge() {
    const items = (NS.blockedHumanized || []).map(safeEsc).join(', ');
    show('⚠️ Резюме не готов — добавь: ' + items, 'warn');
  }

  function resetBlocked() {
    NS.blocked = false;
    NS.blockedHumanized = [];
  }

  function getAccIdx() {
    const sel = document.getElementById('apply-account');
    if (!sel || !sel.options.length) return null;
    const v = parseInt(sel.value, 10);
    return isNaN(v) ? null : v;
  }

  // Поле принимает ссылку или ID — вытаскиваем числовой ID вакансии.
  function extractVacancyId(raw) {
    const s = String(raw || '').trim();
    if (!s) return '';
    const m = s.match(/\/vacancy\/(\d+)/) || s.match(/^(\d+)$/);
    return m ? m[1] : '';
  }

  // ── Обёртка applyCheck ──────────────────────────────────────────────
  const origCheck = window.applyCheck;
  if (typeof origCheck === 'function') {
    window.applyCheck = async function applyCheckWithPreflight() {
      resetBlocked(); // новая проверка всегда снимает старую блокировку

      const accIdx = getAccIdx();
      const vacEl = document.getElementById('apply-vacancy');
      const vid = extractVacancyId(vacEl ? vacEl.value : '');

      // Нет аккаунта/вакансии — preflight невозможен, пусть оригинал
      // покажет свои валидационные ошибки.
      if (accIdx === null || !vid) return origCheck.apply(this, arguments);

      let pf = null;
      try {
        const res = await fetch(
          '/api/account/' + accIdx + '/vacancy/' + vid + '/data_inconsistency'
        );
        pf = await res.json();
      } catch (e) {
        pf = null; // ошибка проверки не блокирует отклик
      }

      if (pf && pf.ok === true && Array.isArray(pf.required) && pf.required.length > 0) {
        NS.blocked = true;
        NS.blockedHumanized = Array.isArray(pf.humanized) && pf.humanized.length
          ? pf.humanized
          : pf.required;
        warnBadge();
        return; // НЕ вызываем оригинал — отклик заблокирован
      }

      if (pf && pf.ok === true) {
        show('✅ Резюме готово к отклику', 'ok');
      }
      // pf.ok !== true (или null) — проверка не удалась, проходим без badge.
      return origCheck.apply(this, arguments);
    };
  }

  // ── Обёртка applySubmit ─────────────────────────────────────────────
  const origSubmit = window.applySubmit;
  if (typeof origSubmit === 'function') {
    window.applySubmit = async function applySubmitWithPreflight() {
      if (NS.blocked) {
        warnBadge();
        return; // кнопка заблокирована
      }
      return origSubmit.apply(this, arguments);
    };
  }

  // ── Сброс блокировки при изменении полей ────────────────────────────
  function bindResets() {
    if (NS._bound) return;
    NS._bound = true;
    const vacEl = document.getElementById('apply-vacancy');
    const accEl = document.getElementById('apply-account');
    if (vacEl) {
      vacEl.addEventListener('input', resetBlocked);
      vacEl.addEventListener('change', resetBlocked);
    }
    if (accEl) {
      accEl.addEventListener('change', resetBlocked);
      accEl.addEventListener('input', resetBlocked);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindResets);
  } else {
    bindResets();
  }
})();
