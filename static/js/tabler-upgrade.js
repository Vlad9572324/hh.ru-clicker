/* Progressive Tabler migration for static and snapshot-rendered dashboard controls. */
(() => {
  const themeKey = 'hh-dashboard-theme';

  function setTheme(theme) {
    document.documentElement.dataset.bsTheme = theme;
    localStorage.setItem(themeKey, theme);
    const button = document.getElementById('theme-btn');
    if (button) {
      const dark = theme === 'dark';
      button.textContent = dark ? '☀️ Светлая' : '🌙 Тёмная';
      button.title = dark ? 'Включить светлую тему' : 'Включить тёмную тему';
      button.setAttribute('aria-pressed', String(dark));
    }
  }

  function initTheme() {
    const saved = localStorage.getItem(themeKey);
    const preferred = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    setTheme(saved === 'dark' || saved === 'light' ? saved : preferred);
    document.getElementById('theme-btn')?.addEventListener('click', () => {
      setTheme(document.documentElement.dataset.bsTheme === 'dark' ? 'light' : 'dark');
    });
  }

  function upgrade(root = document) {
    root.querySelectorAll('input.apply-input:not([type="checkbox"]), textarea.apply-input').forEach(el => {
      el.classList.add('form-control');
    });
    root.querySelectorAll('select.apply-input').forEach(el => el.classList.add('form-select'));
    root.querySelectorAll('.btn-sm, .btn-refresh').forEach(el => {
      el.classList.add('btn', 'btn-sm', 'btn-outline-secondary');
    });
    root.querySelectorAll('.applied-table, .db-table').forEach(el => {
      el.classList.add('table', 'table-vcenter', 'table-hover');
    });
    root.querySelectorAll('.acc-actions, .applied-filters, .db-filters, #log-filters').forEach(el => {
      el.classList.add('tabler-control-row');
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    upgrade();
    new MutationObserver(records => {
      for (const record of records) {
        record.addedNodes.forEach(node => {
          if (node.nodeType === Node.ELEMENT_NODE) upgrade(node);
        });
      }
    }).observe(document.body, {childList: true, subtree: true});
  });
})();
