// ML-анализ резюме (Настройки → 🧭 Карьера → «🤖 Анализ резюме»).
// Рендерится в существующий контейнер index.html: #analyze-resume-root.
// app.js (State, fetch-патч) загружается до features.
//
// Backend: GET /api/account/{idx}/resume_audit → client.analyze_resume(extra).
//
// mobile-форма ok (app/mobile_resume_analyze.py):
//   {ok: true, resume_id: str, title: str,
//    missing_skills: [str],            // _names(): только непустые строки
//    recommended_duties: [str],        // _names(): только непустые строки
//    subroles: [{id, name: str, main: bool, probability: float}],
//    grade: str|null,                  // "MIDDLE"|... из career_platform/profile
//    current_score: float|null,        // max probability сабролей (0..1)
//    partial: bool,
//    errors: [{endpoint: str, error: str}]}
// mobile-форма ошибки: {ok: false, error: "no_resume_id"|"resume_not_found"|...}
// web-форма (hh_resume._analyze_resume) — ДРУГОЙ состав (рыночный аудит):
// ok:true с произвольными ключами либо {error: "..."} БЕЗ ключа ok.
// Политика рендера: известные ключи mobile-формы — секциями, всё остальное —
// компактным <details> с JSON; рендер не падает на произвольных ключах.
//
// Обязательные id (на них написаны e2e-тесты):
//   #analyze-account — select аккаунтов, #analyze-run — кнопка запуска,
//   #analyze-result — контейнер результата.
// DOMContentLoaded: только рендер контролов, НИКАКИХ сетевых запросов
// (аккаунты из State.lastSnapshot; пока снапшот не пришёл — поллинг).

const AnalyzeResumeState = { initialized: false, loading: false, poll: null, accSig: '' };

(function () {
  'use strict';

  const ROOT_ID = 'analyze-resume-root';

  // Ключи mobile-формы ok-ответа, которые рендерим специальными секциями.
  const KNOWN_KEYS = new Set([
    'ok', 'resume_id', 'title', 'missing_skills', 'recommended_duties',
    'subroles', 'grade', 'current_score', 'partial', 'errors',
  ]);

  // ── helpers ──────────────────────────────────────────────────────

  // Экранирование: esc() из app.js, fallback — свой (app.js грузится раньше,
  // но не полагаемся вслепую). Основной вывод идёт через textContent
  // (safe-by-construction), esc — для мест, где удобнее innerHTML.
  function arEsc(s) {
    if (typeof esc === 'function') return esc(s);
    if (s === null || s === undefined) return '';
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/`/g, '&#96;');
  }

  function arEl(tag, styleText, ...children) {
    const node = document.createElement(tag);
    if (styleText) node.style.cssText = styleText;
    for (const child of children) {
      if (child === null || child === undefined) continue;
      node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
    }
    return node;
  }

  // Имя элемента списка: mobile-парсинг (_item_name) гарантирует str для
  // missing_skills/recommended_duties, но рендер защищён и от dict-элементов
  // (ключи name/string/text) — произвольная форма не должна ронять страницу.
  function arItemName(item) {
    if (typeof item === 'string') return item.trim();
    if (item && typeof item === 'object' && !Array.isArray(item)) {
      for (const key of ['name', 'string', 'text', 'title']) {
        const value = item[key];
        if (typeof value === 'string' && value.trim()) return value.trim();
      }
      try { return JSON.stringify(item); } catch (_) { return String(item); }
    }
    if (item === null || item === undefined) return '';
    return String(item);
  }

  function arAccounts() {
    const snap = (typeof State !== 'undefined' && State) ? State.lastSnapshot : null;
    const accounts = (snap && Array.isArray(snap.accounts)) ? snap.accounts : [];
    return accounts.filter(a => a && typeof a === 'object');
  }

  function arLabel(acc) {
    const idx = acc.idx;
    const num = Number(idx);
    return acc.name || acc.short || acc.email
      || `Аккаунт ${Number.isFinite(num) ? num + 1 : idx}`;
  }

  // ── контролы (без сетевых запросов) ──────────────────────────────

  function arFillAccounts() {
    const select = document.getElementById('analyze-account');
    if (!select) return;
    const accounts = arAccounts();
    const sig = accounts.map(a => String(a.idx)).join(',');
    if (sig === AnalyzeResumeState.accSig) return; // без изменений — не дёргаем DOM
    AnalyzeResumeState.accSig = sig;
    const prev = select.value;
    select.replaceChildren(new Option('Выберите аккаунт', ''));
    accounts.forEach(acc => select.add(new Option(arLabel(acc), String(acc.idx))));
    if (accounts.some(a => String(a.idx) === prev)) select.value = prev;
  }

  function arRenderControls(root) {
    root.replaceChildren();

    const row = arEl('div', 'display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px');
    const label = arEl('label', 'color:var(--dim);font-size:12px', 'Аккаунт');
    label.htmlFor = 'analyze-account';
    const select = document.createElement('select');
    select.id = 'analyze-account';
    select.className = 'apply-input';
    select.style.cssText = 'min-width:160px';
    select.add(new Option('Выберите аккаунт', ''));
    const run = document.createElement('button');
    run.id = 'analyze-run';
    run.type = 'button';
    run.className = 'btn-sm';
    run.style.cssText = 'color:var(--green);border-color:var(--green)';
    run.textContent = '🤖 Анализировать резюме';
    run.addEventListener('click', arRun);
    row.append(label, select, run);

    const result = arEl('div');
    result.id = 'analyze-result';
    result.style.cssText = 'margin-top:4px';

    root.append(row, result);
    arFillAccounts();
  }

  function arInit() {
    if (AnalyzeResumeState.initialized) return;
    const root = document.getElementById(ROOT_ID);
    if (!root) return; // секции нет (например, другой вариант index.html)
    AnalyzeResumeState.initialized = true;
    try {
      arRenderControls(root);
    } catch (e) {
      root.textContent = '';
      const msg = arEl('div', 'color:var(--red);font-size:12px',
        'Не удалось инициализировать блок анализа резюме: ' + ((e && e.message) || e));
      root.appendChild(msg);
    }
    // Поллинг снапшота: WS state_update заполняет State.lastSnapshot позже.
    if (AnalyzeResumeState.poll) clearInterval(AnalyzeResumeState.poll);
    AnalyzeResumeState.poll = setInterval(() => {
      try { arFillAccounts(); } catch (_) { /* не роняем страницу */ }
    }, 2000);
  }

  // ── запуск анализа ───────────────────────────────────────────────

  async function arRun() {
    const btn = document.getElementById('analyze-run');
    const result = document.getElementById('analyze-result');
    if (!btn || !result || AnalyzeResumeState.loading) return;
    const raw = (document.getElementById('analyze-account') || {}).value;
    if (raw === '' || raw === null || raw === undefined || !Number.isFinite(Number(raw))) {
      arRenderError('Сначала выберите аккаунт.');
      return;
    }
    AnalyzeResumeState.loading = true;
    btn.disabled = true;
    const prevLabel = btn.textContent;
    btn.textContent = '⏳ Анализ…';
    try {
      const response = await fetch(`/api/account/${Number(raw)}/resume_audit`);
      let data = null;
      try { data = await response.json(); } catch (_) { data = null; }
      if (!response.ok) {
        const msg = (data && typeof data === 'object' && (data.detail || data.error))
          || `HTTP ${response.status}`;
        arRenderError(msg);
        return;
      }
      if (!data || typeof data !== 'object') { arRenderError('Пустой ответ сервера.'); return; }
      // ok:false (mobile) либо {error} без ok (web-форма / Invalid idx маршрута).
      if (data.ok === false || (data.error && data.ok !== true)) {
        arRenderError(data.error || 'Неизвестная ошибка');
        return;
      }
      arRenderOk(data);
    } catch (e) {
      arRenderError((e && e.message) || 'Не удалось выполнить анализ резюме.');
    } finally {
      AnalyzeResumeState.loading = false;
      btn.disabled = false;
      btn.textContent = prevLabel;
    }
  }

  // ── рендер результата ────────────────────────────────────────────

  function arResultBox() {
    const result = document.getElementById('analyze-result');
    if (result) result.replaceChildren();
    return result;
  }

  function arRenderError(message) {
    const result = arResultBox();
    if (!result) return;
    const box = arEl('div',
      'color:var(--red);border:1px solid var(--red);border-radius:8px;padding:10px 12px;font-size:12px;background:rgba(248,81,73,.07)',
      '❌ ', String(message === null || message === undefined ? 'Ошибка анализа резюме' : message));
    result.appendChild(box);
  }

  function arSectionTitle(text) {
    return arEl('div', 'font-size:11px;font-weight:700;color:var(--dim);text-transform:uppercase;letter-spacing:.4px;margin:10px 0 4px', text);
  }

  function arChip(text, main) {
    const chip = arEl('span',
      `display:inline-block;font-size:11px;padding:3px 9px;border-radius:12px;border:1px solid ${main ? 'var(--green)' : 'var(--border)'};color:${main ? 'var(--green)' : 'inherit'};background:var(--bg-card2)`,
      text);
    return chip;
  }

  function arListSection(title, items) {
    const list = Array.isArray(items) ? items : [];
    const names = list.map(arItemName).filter(n => n);
    const wrap = arEl('div');
    wrap.appendChild(arSectionTitle(title));
    if (!names.length) {
      wrap.appendChild(arEl('div', 'font-size:12px;color:var(--dim)', 'Нет данных.'));
      return wrap;
    }
    const ul = arEl('ul', 'margin:0;padding-left:18px;font-size:12px;display:flex;flex-direction:column;gap:3px');
    names.forEach(n => ul.appendChild(arEl('li', null, n)));
    wrap.appendChild(ul);
    return wrap;
  }

  function arScoreText(score) {
    if (typeof score !== 'number' || !Number.isFinite(score)) return null;
    // current_score — max probability сабролей (0..1); показываем процентом.
    return score <= 1 ? `${Math.round(score * 100)}%` : String(Math.round(score));
  }

  function arRenderOk(data) {
    const result = arResultBox();
    if (!result) return;
    try {
      const wrap = arEl('div', 'border:1px solid var(--border);border-radius:8px;padding:10px 12px;font-size:12px;background:var(--bg-card)');

      // Заголовок резюме + resume_id.
      const titleText = (typeof data.title === 'string' && data.title.trim()) ? data.title.trim() : 'Без названия';
      wrap.appendChild(arEl('div', 'font-size:13px;font-weight:700;margin-bottom:6px', titleText));
      if (data.resume_id !== undefined && data.resume_id !== null && String(data.resume_id).trim() !== '') {
        wrap.appendChild(arEl('div', 'font-size:10px;color:var(--dim);margin-bottom:6px', 'resume_id: ' + String(data.resume_id)));
      }

      // Бейджи: grade (🎯) и current_score (📈).
      const badges = arEl('div', 'display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px');
      let grade = data.grade;
      if (grade && typeof grade === 'object') grade = grade.name || grade.id || null;
      if (grade !== null && grade !== undefined && String(grade).trim() !== '') {
        badges.appendChild(arChip(`🎯 ${String(grade)}`, true));
      }
      const scoreText = arScoreText(data.current_score);
      if (scoreText !== null) badges.appendChild(arChip(`📈 Совпадение: ${scoreText}`, false));
      if (badges.childNodes.length) wrap.appendChild(badges);

      // Саброли — чипы (main подсвечен); probability рядом с именем.
      const subroles = Array.isArray(data.subroles) ? data.subroles : [];
      const subChips = arEl('div', 'display:flex;flex-wrap:wrap;gap:6px');
      subroles.forEach(sub => {
        if (!sub || typeof sub !== 'object') return;
        const name = arItemName(sub);
        if (!name) return;
        const prob = (typeof sub.probability === 'number' && Number.isFinite(sub.probability))
          ? ` · ${Math.round(sub.probability * 100)}%` : '';
        subChips.appendChild(arChip(`${name}${prob}`, Boolean(sub.main)));
      });
      if (subChips.childNodes.length) {
        wrap.appendChild(arSectionTitle('Саброли / грейд'));
        wrap.appendChild(subChips);
      }

      // Списки mobile-формы.
      wrap.appendChild(arListSection('Чего не хватает', data.missing_skills));
      wrap.appendChild(arListSection('Рекомендуемые обязанности', data.recommended_duties));

      // partial: предупреждение + ошибки вспомогательных endpoint'ов.
      if (data.partial) {
        const warn = arEl('div',
          'margin-top:10px;color:var(--yellow);border:1px solid var(--yellow);border-radius:8px;padding:8px 10px;background:rgba(210,153,34,.07)',
          '⚠️ Результат неполный: часть источников недоступна.');
        const errors = Array.isArray(data.errors) ? data.errors : [];
        if (errors.length) {
          const ul = arEl('ul', 'margin:6px 0 0;padding-left:16px;font-size:11px');
          errors.forEach(err => {
            if (err && typeof err === 'object') {
              ul.appendChild(arEl('li', null,
                `${err.endpoint || 'endpoint'}: ${err.error || 'ошибка'}`));
            } else if (err !== null && err !== undefined) {
              ul.appendChild(arEl('li', null, String(err)));
            }
          });
          if (ul.childNodes.length) warn.appendChild(ul);
        }
        wrap.appendChild(warn);
      }

      // Неизвестные ключи (web-форма hh_resume._analyze_resume и др.) —
      // компактный <details> с JSON, чтобы произвольный ответ не терялся
      // и не ронял рендер.
      const extraKeys = Object.keys(data).filter(k => !KNOWN_KEYS.has(k));
      if (extraKeys.length) {
        const details = document.createElement('details');
        details.style.cssText = 'margin-top:10px';
        const summary = document.createElement('summary');
        summary.style.cssText = 'font-size:11px;color:var(--dim);cursor:pointer';
        summary.textContent = `Дополнительные данные (${extraKeys.length})`;
        details.appendChild(summary);
        const pre = document.createElement('pre');
        pre.style.cssText = 'font-size:10px;overflow-x:auto;margin:6px 0 0;padding:8px;background:var(--bg-card2);border:1px solid var(--border);border-radius:6px;white-space:pre-wrap';
        const extra = {};
        extraKeys.forEach(k => { extra[k] = data[k]; });
        try { pre.textContent = JSON.stringify(extra, null, 2); }
        catch (_) { pre.textContent = String(extra); }
        details.appendChild(pre);
        wrap.appendChild(details);
      }

      result.appendChild(wrap);
    } catch (e) {
      // Рендер произвольного ответа не должен кидать uncaught-исключения.
      arRenderError('Не удалось отобразить результат: ' + ((e && e.message) || e));
    }
  }

  // ── bootstrap ────────────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', arInit);
  } else {
    arInit();
  }
})();
