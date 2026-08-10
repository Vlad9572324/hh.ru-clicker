// Badge в header "⭐ Оценить: N" — работодатели, которых юзер может оценить.
// Backend: GET /api/account/{idx}/reviews_to_rate (app/routes/ui_reviews.py →
// app/mobile_employer_reviews.py, mobile GET /employer_reviews/employers_to_rate).
//
// Автозагрузка: НИКАКИХ сетевых запросов на старте. Ждём первый snapshot
// (глобаль State.lastSnapshot из app.js) поллингом ~раз в секунду (до ~10
// попыток), затем ОДИН раз (guard-флаг) последовательно фетчим каждый
// аккаунт. Ошибки глотаются молча — badge остаётся скрыт.
//
// Попап #reviews-to-rate-popup создаётся динамически здесь; рендерится из
// закэшированного ответа (повторный fetch по клику запрещён).
//
// Все fetch/JSON/DOM-операции обёрнуты в try/catch: e2e пишет window
// 'pageerror' и падает на любом uncaught-исключении.
(() => {
  const ReviewsBadge = {
    fetched: false,      // guard: запросы строго один раз на страницу
    attempts: 0,         // счётчик попыток дождаться snapshot
    timer: null,
    total: 0,
    byAccount: [],       // [{name, items: [{employer_name, position, target}]}]
  };

  const TARGET_LABELS = {
    PREVIOUS_EMPLOYER: 'прошлый работодатель',
    CURRENT_EMPLOYER: 'текущий работодатель',
  };

  function badgeEl() { return document.getElementById('reviews-to-rate-badge'); }
  function popupEl() { return document.getElementById('reviews-to-rate-popup'); }

  function ensurePopup() {
    let popup = popupEl();
    if (popup) return popup;
    popup = document.createElement('div');
    popup.id = 'reviews-to-rate-popup';
    popup.style.cssText = [
      'display:none', 'position:fixed', 'top:56px', 'right:16px',
      'z-index:999999', 'min-width:280px', 'max-width:440px', 'max-height:60vh',
      'overflow-y:auto', 'background:var(--bg-card2, #161b22)',
      'border:1px solid var(--border, #30363d)', 'border-radius:8px',
      'box-shadow:0 8px 24px rgba(0,0,0,.5)', 'padding:12px',
      'font-size:12px', 'line-height:1.4', 'color:var(--text, #c9d1d9)',
    ].join(';');
    document.body.appendChild(popup);
    return popup;
  }

  // Рендер из кэша ReviewsBadge.byAccount — только createElement/textContent
  // (никакого innerHTML с данными → нет ни исключений на парсинге, ни XSS).
  function renderPopup() {
    const popup = ensurePopup();
    popup.replaceChildren();

    const header = document.createElement('div');
    header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:8px';
    const title = document.createElement('div');
    title.style.cssText = 'font-weight:600;color:var(--yellow)';
    title.textContent = `⭐ Работодатели для оценки: ${ReviewsBadge.total}`;
    const close = document.createElement('button');
    close.textContent = '✕';
    close.title = 'Скрыть';
    close.style.cssText = 'border:none;background:none;color:var(--dim, #8b949e);cursor:pointer;font-size:14px;padding:0 4px;font-family:inherit';
    close.addEventListener('click', hidePopup);
    header.append(title, close);
    popup.appendChild(header);

    if (!ReviewsBadge.byAccount.length) {
      const empty = document.createElement('div');
      empty.style.cssText = 'color:var(--dim, #8b949e)';
      empty.textContent = 'Нет работодателей для оценки.';
      popup.appendChild(empty);
      return;
    }

    ReviewsBadge.byAccount.forEach(group => {
      const accTitle = document.createElement('div');
      accTitle.style.cssText = 'font-weight:600;margin:8px 0 4px';
      accTitle.textContent = group.name || 'Аккаунт';
      popup.appendChild(accTitle);
      (group.items || []).forEach(it => {
        const row = document.createElement('div');
        row.style.cssText = 'padding:4px 0;border-bottom:1px solid var(--border, #21262d)';
        const name = document.createElement('div');
        name.textContent = (it && it.employer_name) || '—';
        const pos = document.createElement('div');
        pos.style.cssText = 'color:var(--dim, #8b949e)';
        pos.textContent = (it && it.position) || '';
        const target = document.createElement('div');
        target.style.cssText = 'color:var(--dim, #8b949e);font-size:11px;font-style:italic';
        const t = it && it.target;
        target.textContent = TARGET_LABELS[t] || t || '';
        row.append(name, pos, target);
        popup.appendChild(row);
      });
    });
  }

  function showPopup() { renderPopup(); const p = popupEl(); if (p) p.style.display = ''; }
  function hidePopup() { const p = popupEl(); if (p) p.style.display = 'none'; }

  function togglePopup() {
    try {
      const p = ensurePopup();
      if (p.style.display === 'none') showPopup(); else hidePopup();
    } catch (e) { /* не роняем страницу */ }
  }

  // Один проход по аккаунтам, последовательно. Guard ставится ДО await.
  async function fetchForAccounts(accounts) {
    if (ReviewsBadge.fetched) return;
    ReviewsBadge.fetched = true;
    try {
      let total = 0;
      const byAccount = [];
      for (const acc of accounts) {
        const idx = acc && acc.idx;
        if (idx === null || idx === undefined || idx === '') continue;
        try {
          const resp = await fetch(`/api/account/${idx}/reviews_to_rate`);
          const data = await resp.json();  // может бросить на битом JSON — ловим
          if (data && data.ok && Number(data.count) > 0) {
            total += Number(data.count);
            byAccount.push({
              name: acc.name || acc.short || `Аккаунт ${Number(idx) + 1}`,
              items: Array.isArray(data.items) ? data.items : [],
            });
          }
        } catch (e) { /* молча: badge остаётся скрыт */ }
      }
      ReviewsBadge.total = total;
      ReviewsBadge.byAccount = byAccount;
      const badge = badgeEl();
      if (!badge) return;
      if (total > 0) {
        badge.textContent = `⭐ Оценить: ${total}`;
        badge.style.display = '';
      } else {
        badge.style.display = 'none';
      }
    } catch (e) { /* молча */ }
  }

  function stopTimer() {
    if (ReviewsBadge.timer) { clearInterval(ReviewsBadge.timer); ReviewsBadge.timer = null; }
  }

  function tryStart() {
    try {
      ReviewsBadge.attempts += 1;
      const snap = (typeof State !== 'undefined' && State) ? State.lastSnapshot : null;
      const accounts = (snap && Array.isArray(snap.accounts)) ? snap.accounts : [];
      if (!accounts.length) {
        // ~10 попыток (~10с) без accounts — сдаёмся, badge скрыт.
        if (ReviewsBadge.attempts >= 10) stopTimer();
        return;
      }
      stopTimer();
      fetchForAccounts(accounts);
    } catch (e) { stopTimer(); }
  }

  function init() {
    try {
      const badge = badgeEl();
      if (badge && !badge.dataset.reviewsBound) {
        badge.dataset.reviewsBound = '1';
        badge.addEventListener('click', togglePopup);
      }
      ensurePopup();
      if (ReviewsBadge.timer || ReviewsBadge.fetched) return;
      ReviewsBadge.timer = setInterval(tryStart, 1000);
    } catch (e) { /* не роняем страницу */ }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
