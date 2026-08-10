// 🎓 Навыки и верификации (Настройки → группа «🧭 Карьера»).
// Рендерит весь markup в готовый контейнер #skills-verifications-root из
// index.html. Файл app.js грузится ДО features: State.lastSnapshot?.accounts
// даёт список аккаунтов, esc() — экранирование. Автозагрузки на старте НЕТ:
// сетевые запросы только по клику «🎓 Загрузить».
const SkillsState = { initialized: false, loading: false };

// Экранирование: глобальная esc() из app.js, если доступна, иначе своя.
function skillsEsc(s) {
  if (typeof esc === 'function') return esc(s);
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function skillsAccounts() {
  return (typeof State !== 'undefined' && State.lastSnapshot && State.lastSnapshot.accounts) || [];
}

// Заполнить #skills-account из свежего снапшота, сохранив выбор, если он
// всё ещё валиден (снапшот приходит асинхронно — обновляем при каждом
// обращении, как hedi.js делает на переключении вкладки).
function skillsPopulateAccounts() {
  const select = document.getElementById('skills-account');
  if (!select) return;
  const accounts = skillsAccounts();
  const prev = String(select.value ?? '');
  select.replaceChildren(new Option('Выберите аккаунт', ''));
  accounts.forEach(acc => select.add(new Option(
    acc.name || acc.short || `Аккаунт ${(acc.idx ?? 0) + 1}`, String(acc.idx))));
  if (accounts.some(acc => String(acc.idx) === prev)) select.value = prev;
}

function skillsSelectedIdx() {
  const select = document.getElementById('skills-account');
  const value = select ? select.value : '';
  if (value === '' || value === null || !Number.isInteger(Number(value))) return null;
  return Number(value);
}

function skillsShowError(msg) {
  const list = document.getElementById('skills-list');
  if (list) list.innerHTML = `<div class="skills-error" style="color:#ff6b6b">${skillsEsc(msg)}</div>`;
}

function skillsRenderMethodItem(m) {
  const objects = Array.isArray(m.verification_objects) ? m.verification_objects : [];
  const obj = objects[0] || {};
  const level = obj.level && obj.level.name ? ` · ${skillsEsc(obj.level.name)}` : '';
  const quiz = m.kak_dela_quiz || {};
  const availability = (m.availability && m.availability.status) || '';
  const skillId = obj.id !== undefined && obj.id !== null ? obj.id : '';
  return `<div class="skill-verify-item" data-skill-id="${skillsEsc(skillId)}"
      style="padding:8px 10px;border:1px solid var(--border,#2c2f3a);border-radius:8px;margin-bottom:6px;cursor:pointer">
    <div class="skill-verify-name" style="font-weight:600">${skillsEsc(m.name || '')}</div>
    <div class="skill-verify-meta" style="font-size:12px;color:var(--dim,#8a8f9d)">
      ${skillsEsc(obj.name || '')}${level} · вопросов: ${skillsEsc(quiz.task_number ?? '?')} ·
      ~${skillsEsc(quiz.estimated_time ?? '?')} сек · ${skillsEsc(availability)}
    </div>
  </div>`;
}

function skillsRenderSkillItem(s) {
  const mark = s.verified ? '✅' : '⬜';
  return `<div class="skill-item" style="padding:4px 0;font-size:13px">
    ${mark} ${skillsEsc(s.name || '')}
    <span style="color:var(--dim,#8a8f9d);font-size:12px"> · ${skillsEsc(s.category || '')}</span>
  </div>`;
}

function skillsRenderResults(methodsData, skillsData) {
  const list = document.getElementById('skills-list');
  if (!list) return;
  const parts = [];
  const errors = [];

  if (methodsData && methodsData.ok !== false) {
    const items = Array.isArray(methodsData.items) ? methodsData.items : [];
    parts.push(`<div class="skills-block" style="margin-bottom:14px">
      <div style="font-weight:700;margin-bottom:8px">🎓 Доступные тесты</div>
      ${items.length ? items.map(skillsRenderMethodItem).join('')
        : '<div style="color:var(--dim,#8a8f9d)">Нет доступных тестов</div>'}
    </div>`);
  } else {
    errors.push(`Доступные тесты: ${(methodsData && methodsData.error) || 'не удалось загрузить'}`);
  }

  if (skillsData && skillsData.ok !== false) {
    const items = Array.isArray(skillsData.items) ? skillsData.items : [];
    parts.push(`<div class="skills-block" style="margin-bottom:14px">
      <div style="font-weight:700;margin-bottom:8px">📋 Мои навыки</div>
      ${items.length ? items.map(skillsRenderSkillItem).join('')
        : '<div style="color:var(--dim,#8a8f9d)">Навыков нет</div>'}
    </div>`);
  } else {
    errors.push(`Мои навыки: ${(skillsData && skillsData.error) || 'не удалось загрузить'}`);
  }

  errors.forEach(msg => parts.push(
    `<div class="skills-error" style="color:#ff6b6b">${skillsEsc(msg)}</div>`));

  list.innerHTML = parts.join('');
}

// Клик по тесту: syllabus навыка в модалку. id навыка берём из
// data-skill-id (это id из verification_objects, НЕ id метода).
async function skillsOpenSyllabus(skillId) {
  const idx = skillsSelectedIdx();
  if (idx === null || skillId === '' || skillId === null) return;
  const modal = document.getElementById('skills-modal');
  const content = document.getElementById('skills-modal-content');
  if (!modal || !content) return;
  modal.style.display = 'block';
  content.innerHTML = '<div style="color:var(--dim,#8a8f9d)">Загружаю программу теста…</div>';
  try {
    const response = await fetch(`/api/account/${idx}/skill_verification/${skillId}`);
    let data = {};
    try { data = await response.json(); } catch (_) { data = {}; }
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    content.innerHTML = skillsRenderSyllabus(data);
  } catch (error) {
    const msg = (error && error.message) || 'Не удалось загрузить программу теста';
    content.innerHTML = `<div class="skills-error" style="color:#ff6b6b">${skillsEsc(msg)}</div>`;
    skillsShowError(msg);
  }
}

function skillsRenderSyllabus(data) {
  const levels = Array.isArray(data.levels) ? data.levels : [];
  const rows = levels.map(lv => {
    const theory = lv.theory || {};
    const content = String(theory.content || '')
      .split('\n').filter(Boolean)
      .map(line => `<div>${skillsEsc(line)}</div>`)
      .join('');
    return `<div class="skill-syllabus-level" style="margin-bottom:12px">
      <div style="font-weight:600;margin-bottom:6px">${skillsEsc(lv.name || '')}</div>
      ${content
        ? `<div class="skill-syllabus-content" style="font-size:12px">${content}</div>`
        : '<div style="color:var(--dim,#8a8f9d)">Программа не указана</div>'}
      <div style="color:var(--dim,#8a8f9d);font-size:12px;margin-top:4px">
        Вопросов: ${skillsEsc(theory.task_number ?? '?')} ·
        ~${skillsEsc(theory.estimated_time ?? '?')} сек
      </div>
    </div>`;
  }).join('');
  return `<h3 style="margin:0 0 12px">${skillsEsc(data.name || '')}</h3>
    ${rows || '<div style="color:var(--dim,#8a8f9d)">Уровней нет</div>'}`;
}

function skillsCloseModal() {
  const modal = document.getElementById('skills-modal');
  if (modal) modal.style.display = 'none';
}

async function skillsLoad() {
  const list = document.getElementById('skills-list');
  const button = document.getElementById('skills-load');
  if (!list || !button || SkillsState.loading) return;
  try {
    skillsPopulateAccounts(); // снапшот мог приехать после рендера
    const idx = skillsSelectedIdx();
    if (idx === null) { skillsShowError('Сначала выберите аккаунт.'); return; }
    SkillsState.loading = true;
    button.disabled = true;
    list.innerHTML = '<div style="color:var(--dim,#8a8f9d)">Загружаю…</div>';
    let methodsResponse = null;
    let skillsResponse = null;
    try {
      [methodsResponse, skillsResponse] = await Promise.all([
        fetch(`/api/account/${idx}/skill_verifications/methods`),
        fetch(`/api/account/${idx}/skill_verifications/skills`),
      ]);
    } catch (networkError) {
      throw new Error((networkError && networkError.message) || 'Сеть недоступна');
    }
    let methodsData = {};
    let skillsData = {};
    try { methodsData = await methodsResponse.json(); } catch (_) { methodsData = {}; }
    try { skillsData = await skillsResponse.json(); } catch (_) { skillsData = {}; }
    if (!methodsResponse.ok && methodsData.ok !== false) {
      methodsData = { ok: false, error: methodsData.error || `HTTP ${methodsResponse.status}` };
    }
    if (!skillsResponse.ok && skillsData.ok !== false) {
      skillsData = { ok: false, error: skillsData.error || `HTTP ${skillsResponse.status}` };
    }
    skillsRenderResults(methodsData, skillsData);
  } catch (error) {
    skillsShowError((error && error.message) || 'Не удалось загрузить верификации');
  } finally {
    SkillsState.loading = false;
    button.disabled = false;
  }
}

function initSkillsPanel() {
  const root = document.getElementById('skills-verifications-root');
  if (!root || SkillsState.initialized) return;
  SkillsState.initialized = true;
  root.innerHTML = `
    <div class="skills-controls" style="display:flex;gap:8px;align-items:center;margin-bottom:10px">
      <select id="skills-account" class="apply-input" style="flex:1"></select>
      <button id="skills-load" type="button">🎓 Загрузить</button>
    </div>
    <div id="skills-list"></div>
    <div id="skills-modal" style="position:fixed;display:none;left:0;top:0;right:0;bottom:0;
        z-index:10000;background:rgba(0,0,0,.6)">
      <div id="skills-modal-body" style="position:relative;margin:8vh auto;max-width:560px;
          max-height:80vh;overflow:auto;background:var(--panel,#1c1e26);
          border:1px solid var(--border,#2c2f3a);border-radius:10px;padding:16px">
        <button id="skills-modal-close" type="button"
            style="position:absolute;top:8px;right:8px">✕</button>
        <div id="skills-modal-content"></div>
      </div>
    </div>`;
  skillsPopulateAccounts();
  document.getElementById('skills-load')?.addEventListener('click', skillsLoad);
  document.getElementById('skills-modal-close')?.addEventListener('click', skillsCloseModal);
  document.getElementById('skills-modal')?.addEventListener('click', e => {
    if (e.target && e.target.id === 'skills-modal') skillsCloseModal();
  });
  document.getElementById('skills-list')?.addEventListener('click', e => {
    const item = e.target && e.target.closest ? e.target.closest('.skill-verify-item') : null;
    if (!item) return;
    skillsOpenSyllabus(item.getAttribute('data-skill-id'));
  });
}

// Рендер на DOMContentLoaded — только пустые контролы, БЕЗ сетевых запросов.
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initSkillsPanel);
} else {
  initSkillsPanel();
}
