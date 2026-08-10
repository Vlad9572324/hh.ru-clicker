// feat3_skills.js — Skills gap badge в карточке аккаунта (feat3).
//
// Грузится ПОСЛЕ app.js. Обёртывает window.updateCard: при первом вызове
// для карточки создаёт секцию с кнопкой «🧠 Skills: что советует HH»,
// при повторных snapshot'ах (~0.3с) секцию НЕ трогает (никакой перерисовки).
// Клик по кнопке → POST /api/account/<idx>/skills_recommend → чипы gap/have
// + ссылка «📝 Открыть редактор резюме».
(function () {
  'use strict';

  // Guard от двойной установки (скрипт могли подключить дважды).
  if (window.__feat3SkillsInstalled) return;
  window.__feat3SkillsInstalled = true;

  // Глобальный esc() из app.js; страховочный fallback если его нет.
  const escFn = (typeof window.esc === 'function')
    ? window.esc
    : (s) => String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  function sectionId(idx) { return 'feat3-skills-' + idx; }

  function chipsHTML(names, cls) {
    return (names || [])
      .map((n) => '<span class="feat3-chip ' + cls + '">' + escFn(n) + '</span>')
      .join('');
  }

  function renderResult(box, data) {
    const gap = Array.isArray(data.gap) ? data.gap : [];
    const have = Array.isArray(data.have) ? data.have : [];
    let html = '';
    if (gap.length === 0) {
      html += '<div class="feat3-line feat3-ok">✅ HH ничего не советует добавлять</div>';
    } else {
      html += '<div class="feat3-line"><span class="feat3-label">HH советует добавить:</span> ' +
        chipsHTML(gap, 'feat3-chip-gap') + '</div>';
    }
    if (have.length > 0) {
      html += '<div class="feat3-line"><span class="feat3-label feat3-dim">Уже есть в профиле:</span> ' +
        chipsHTML(have, 'feat3-chip-have') + '</div>';
    }
    if (data.editor_url) {
      html += '<div class="feat3-line"><a class="feat3-editor-btn" href="' + escFn(data.editor_url) +
        '" target="_blank" rel="noopener">📝 Открыть редактор резюме</a></div>';
    }
    box.innerHTML = html;
  }

  function renderError(box, idx, msg) {
    box.innerHTML =
      '<div class="feat3-line feat3-error">❌ ' + escFn(msg) + '</div>' +
      '<div class="feat3-line"><button type="button" class="feat3-btn" data-feat3-retry="' + idx +
      '">🔄 Попробовать ещё раз</button></div>';
  }

  async function loadSkills(idx, box) {
    box.innerHTML = '<div class="feat3-line feat3-dim">⏳ Считаю...</div>';
    let res;
    try {
      res = await fetch('/api/account/' + idx + '/skills_recommend', { method: 'POST' });
    } catch (e) {
      renderError(box, idx, String(e));
      return;
    }
    let data = {};
    try { data = await res.json(); } catch (_) { /* тело могло быть не JSON */ }
    if (!res.ok || !data.ok) {
      renderError(box, idx, (data && data.error) ? data.error : ('HTTP ' + res.status));
      return;
    }
    renderResult(box, data);
  }

  // Создать секцию в карточке ровно один раз (guard по id).
  function ensureSection(card, acc) {
    const idx = acc && acc.idx;
    if (idx === undefined || idx === null) return;
    if (document.getElementById(sectionId(idx))) return; // уже есть — не трогаем
    const wrap = document.createElement('div');
    wrap.className = 'feat3-skills';
    wrap.id = sectionId(idx);
    wrap.innerHTML =
      '<button type="button" class="feat3-btn feat3-open-btn" data-feat3-open="' + idx +
      '">🧠 Skills: что советует HH</button>' +
      '<div class="feat3-result" data-feat3-box="' + idx + '" style="display:none"></div>';
    card.appendChild(wrap);
  }

  // Делегирование кликов: кнопки секции живут в динамических карточках.
  document.addEventListener('click', (ev) => {
    const target = ev.target;
    if (!target || typeof target.closest !== 'function') return;

    const openBtn = target.closest('[data-feat3-open]');
    if (openBtn) {
      const idx = parseInt(openBtn.getAttribute('data-feat3-open'), 10);
      const box = document.querySelector('[data-feat3-box="' + idx + '"]');
      if (box) {
        openBtn.style.display = 'none';
        box.style.display = 'block';
        loadSkills(idx, box);
      }
      return;
    }

    const retryBtn = target.closest('[data-feat3-retry]');
    if (retryBtn) {
      const idx = parseInt(retryBtn.getAttribute('data-feat3-retry'), 10);
      const box = retryBtn.closest('.feat3-result');
      if (box) loadSkills(idx, box);
    }
  });

  // ── Обёртка window.updateCard ─────────────────────────────────────────
  const origUpdateCard = window.updateCard;
  if (typeof origUpdateCard === 'function') {
    window.updateCard = function (card, acc) {
      const out = origUpdateCard.apply(this, arguments);
      try {
        if (card && acc && acc.idx !== undefined) ensureSection(card, acc);
      } catch (e) {
        if (window.console) console.warn('[feat3-skills]', e);
      }
      return out;
    };
  } else if (window.console) {
    console.warn('[feat3-skills] window.updateCard не найдена — скрипт загружен до app.js?');
  }
})();
