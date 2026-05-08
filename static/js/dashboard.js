// ── i18n ──────────────────────────────────────────────────────
let lang = localStorage.getItem('hh-lang') || 'ru';

const T = {
  ru: {
    // Вкладки
    tab_main: '📊 Главная',
    tab_log: '📜 Лог',
    tab_applied: '✅ Отклики',
    tab_tests: '🧪 Тесты',
    tab_db: '📂 База',
    tab_hh: '🎯 HH Статус',
    tab_views: '👁️ Просмотры',
    tab_apply: '🚀 Отклик',
    tab_settings: '⚙️ Настройки',
    // Шапка
    hdr_found: 'найдено',
    hdr_replies: 'откликов',
    hdr_in_db: 'в базе',
    hdr_tests: 'тестов',
    hdr_new_views: 'новых просм.',
    hdr_new_inv: 'новых приглаш.',
    hdr_shows: 'показов',
    btn_pause: '⏸ Пауза',
    btn_resume: '▶ Продолжить (все)',
    // Статусные бейджи
    status_idle: 'ОЖИДАНИЕ',
    status_collecting: 'СБОР ВАКАНСИЙ',
    status_applying: 'ОТПРАВКА ОТКЛИКОВ',
    status_limit: 'ЛИМИТ',
    status_waiting: 'ПАУЗА',
    status_checking: 'ПРОВЕРКА ЛИМИТА',
    status_inactive: 'НЕАКТИВНА',
    status_all_paused: '⏸ ВСЕ НА ПАУЗЕ',
    status_acc_paused: '⏸ НА ПАУЗЕ',
    // Подписи карточек
    stat_replies: 'Отклики',
    stat_tests: 'Тесты',
    stat_surveys: '📝 Опросы',
    stat_already: 'Уже',
    stat_errors: 'Ошибки',
    stat_salary: '💰 Зарплата',
    stat_interviews: '🎯 Интервью',
    stat_new_inv: '📬 Новые',
    card_waiting: 'Ожидание...',
    card_hh_loading: '⏳ Загружаю HH данные...',
    card_sending: 'Отправка...',
    btn_acc_pause: '⏸ Пауза аккаунта',
    btn_acc_resume: '▶ Продолжить',
    btn_acc_global_pause: '⏸ Глобальная пауза',
    btn_resume_touch: '📤 Поднять резюме',
    btn_clear_discards: '🗑️ Очистить дискарды',
    btn_launch: '▶ Запустить',
    btn_delete: '✕ Удалить',
    card_apply_tests: 'Откликаться на вакансии с тестом',
    letter_section: '✉️ Письмо',
    url_section: '🔗 URL поиска',
    btn_save: '💾 Сохранить',
    btn_apply_url: '💾 Применить',
    cookies_expired_badge: '⚠️ Куки протухли! Обновите куки',
    errs_in_row: 'ошибок подряд',
    // Глобальная статистика
    gs_session: '📊 Сессия',
    gs_found: '🔍 Найдено',
    gs_applied: '✅ Отклики',
    gs_tests: '🧪 Тесты',
    gs_errors: '❌ Ошибки',
    gs_in_db: '💾 В базе',
    gs_in_db_tests: '🧪 Тест.',
    sidebar_recent: '📬 Последние отклики',
    recent_empty: 'Ожидание откликов...',
    no_accounts: 'Нет аккаунтов. Добавьте аккаунт в настройках ⚙️',
    // Статистика резюме
    rs_views: 'просм. (7д)',
    rs_shows: 'показов',
    rs_inv: 'приглаш.',
    rs_raise_in: 'поднять через',
    rs_raises_avail: 'поднятий доступно',
    // Вкладка лога
    log_search_ph: '🔍 Поиск...',
    log_all_accs: 'Все аккаунты',
    log_all: 'Все',
    // Вкладка откликов
    applied_title: '✅ Отклики',
    applied_search_ph: '🔍 Поиск по названию / компании...',
    applied_all_accs: 'Все аккаунты',
    applied_only_named: 'Только с названием',
    col_date: 'Дата',
    col_account: 'Аккаунт',
    col_vacancy: 'Вакансия',
    col_company: 'Компания',
    col_salary: 'Зарплата',
    btn_show_more: 'Показать ещё',
    shown_of: 'показано',
    shown_of2: 'из',
    // Вкладка тестов
    tests_title: '🧪 Вакансии с тестами',
    col_applied_yn: 'Откликнулись',
    col_link: 'Ссылка',
    // Вкладка базы
    db_title: '📂 База вакансий',
    db_search_ph: '🔍 Название / компания / ID...',
    db_all_statuses: 'Все статусы',
    db_status_sent: '✅ Откликнулись',
    db_status_test_passed: '📝 Тест пройден',
    db_status_test_pending: '🧪 Тест не пройден',
    db_all_accs: 'Все аккаунты',
    col_status: 'Статус',
    col_accounts: 'Аккаунты',
    // HH-статус
    hh_interviews: 'Интервью',
    hh_viewed: 'Просмотрено',
    hh_discards: 'Отказы',
    hh_not_viewed: 'Не просм.',
    hh_updated: 'Обновлено:',
    hh_inv_list: '📋 Приглашения на интервью:',
    hh_offers: '🏢 Возможные предложения:',
    hh_no_data: 'Нет данных',
    hh_loading: '⏳ Загружаю данные HH...',
    // Вкладка просмотров
    views_7d: 'Просмотров резюме (7д)',
    views_new: 'Новых просмотров',
    views_shows: 'Показов в поиске',
    views_invitations: 'Приглашений (7д)',
    views_inv_new: 'Новых приглашений',
    views_loading: 'Загружаю историю просмотров...',
    btn_load_history: '↻ Загрузить историю',
    views_no_data: 'Нет данных (обновите через 15 мин)',
    col_employer: 'Компания',
    // Вкладка ручного отклика
    apply_title: '🚀 Ручной отклик',
    apply_desc: 'Введите ссылку или ID вакансии — бот проверит, нужен ли опрос, покажет вопросы и отправит отклик.',
    apply_label_acc: 'Аккаунт',
    apply_label_vacancy: 'Ссылка на вакансию или ID',
    apply_vacancy_ph: 'https://hh.ru/vacancy/130334718 или просто 130334718',
    apply_label_tpl: 'Шаблон письма',
    apply_tpl_ph: '— выбрать шаблон —',
    apply_btn_clear: '✕ Очистить',
    apply_label_letter: 'Сопроводительное письмо',
    apply_letter_ph: 'Сопроводительное письмо (необязательно)',
    apply_btn_check: '🔍 Проверить / Откликнуться',
    // Вкладка настроек
    settings_title: '⚙️ Настройки бота',
    btn_apply_settings: '✅ Применить',
    settings_applied: '✅ Настройки применены',
    // Подписи параметров настроек
    lbl_pages_per_url: 'Страниц на URL',
    hint_pages_per_url: 'Сколько страниц результатов загружать для каждого поискового запроса',
    lbl_response_delay: 'Задержка отклика (с)',
    hint_response_delay: 'Пауза между пачками откликов в секундах',
    lbl_pause_between_cycles: 'Пауза между циклами (с)',
    hint_pause_between_cycles: 'Ожидание после завершения полного цикла обработки вакансий',
    lbl_batch_responses: 'Размер пачки откликов',
    hint_batch_responses: 'Сколько откликов отправлять параллельно',
    lbl_limit_check_interval: 'Интервал проверки лимита (м)',
    hint_limit_check_interval: 'Как часто проверять сброс дневного лимита откликов',
    lbl_min_salary: 'Минимальная зарплата (₽)',
    hint_min_salary: 'Пропускать вакансии с зарплатой ниже указанной (0 = без фильтра)',
    lbl_auto_pause_errors: 'Авто-пауза при ошибках',
    hint_auto_pause_errors: 'Авто-пауза аккаунта после N ошибок подряд (0 = выключено)',
    // Разделы настроек
    sec_main_accounts: '👤 Основные аккаунты',
    sec_main_accounts_desc: 'Добавляйте и редактируйте основные аккаунты. Изменения сохраняются в data/accounts.json.',
    sec_url_pool: '🔗 Пул поисковых запросов',
    sec_url_pool_desc: 'Добавьте URL-адреса поиска вакансий — они появятся как чекбоксы на карточке каждого аккаунта.',
    sec_letters: '✉️ Шаблоны писем',
    sec_letters_desc: 'Создайте именованные шаблоны — они появятся в выпадающем списке на каждой карточке аккаунта.',
    sec_questionnaire: '📝 Шаблонные ответы на опросы',
    sec_questionnaire_desc: 'Когда вакансия требует опрос — бот автоматически заполнит его.',
    sec_cookies: '🔑 Обновить куки аккаунтов',
    sec_sessions: '🌐 Браузерные сессии',
    // Форма аккаунта
    acc_field_name: 'Имя (полное)',
    acc_field_short: 'Короткое имя',
    acc_field_color: 'Цвет',
    acc_ph_name: 'Иван (основной)',
    acc_ph_short: 'основной',
    acc_cookies_label: 'Cookies (cURL или строка)',
    btn_add: '✅ Добавить',
    btn_add_account: '＋ Добавить аккаунт',
    btn_add_url: '＋ Добавить URL',
    btn_save_pool: '💾 Сохранить пул',
    btn_add_template: '＋ Добавить шаблон',
    btn_save_templates: '💾 Сохранить шаблоны',
    // Анкеты
    q_keywords_ph: 'опыт, работа, QA',
    q_keywords_label: 'Ключевые слова (через запятую)',
    q_answer_label: 'Ответ',
    q_default_label: 'Ответ по умолчанию (если ни один шаблон не подошёл)',
    q_default_ph: 'Готова рассказать подробнее на собеседовании.',
    // Раздел cookies
    ck_desc: 'Вставьте новый cURL или строку cookie: hhtoken=…',
    btn_update_cookies: '🔑 Обновить куки',
    // Сессии
    sess_add: '➕ Добавить сессию из браузера',
    sess_mode_curl: 'cURL / строка',
    sess_mode_manual: 'Вручную',
    sess_curl_desc: 'Самый простой способ — Copy as cURL',
    sess_name_label: 'Имя (необязательно)',
    sess_name_ph: 'Например: Мария',
    sess_letter_label: 'Сопроводительное письмо (необязательно)',
    btn_connect: '🔗 Подключить сессию',
    sess_active: '🟢 активна',
    sess_inactive: '⭕ неактивна',
    // Диалоги подтверждения
    confirm_delete: 'Удалить',
    confirm_cancel: 'Отмена',
    // Горячие клавиши
    shortcuts_title: '⌨️ Горячие клавиши',
    shortcuts_tabs: 'Переключить вкладку',
    shortcuts_pause: 'Пауза / продолжить все',
    shortcuts_help: 'Это окно',
    shortcuts_esc: 'Закрыть это окно',
    btn_close: 'Закрыть',
    // Уведомления
    notif_new_inv: '📬 Новое приглашение — ',
    notif_inv_count_pre: 'Теперь',
    notif_inv_count_mid: 'интервью (+',
    notif_limit: '🚫 Лимит — ',
    notif_limit_body: 'Дневной лимит откликов исчерпан',
    notif_cookies: '⚠️ Куки протухли — ',
    notif_cookies_body: 'Обновите куки в настройках аккаунта',
    // Заголовки страниц
    title_limit: '🚫 ЛИМИТ | HH Bot',
    title_paused: '⏸ Пауза | HH Bot',
    // Тексты диалогов подтверждения
    confirm_del_acc_pre: 'Удалить аккаунт',
    confirm_del_acc_body: 'Воркер будет остановлен.',
    confirm_del_db_pre: 'Удалить',
    confirm_del_db_mid: 'из базы?',
    confirm_del_db_body: 'Бот сможет откликнуться повторно.',
    confirm_del_sess: 'Удалить браузерную сессию?',
  },
  en: {
    // Вкладки
    tab_main: '📊 Main',
    tab_log: '📜 Log',
    tab_applied: '✅ Applied',
    tab_tests: '🧪 Tests',
    tab_db: '📂 Database',
    tab_hh: '🎯 HH Status',
    tab_views: '👁️ Views',
    tab_apply: '🚀 Apply',
    tab_settings: '⚙️ Settings',
    // Шапка
    hdr_found: 'found',
    hdr_replies: 'applied',
    hdr_in_db: 'in DB',
    hdr_tests: 'tests',
    hdr_new_views: 'new views',
    hdr_new_inv: 'new invitations',
    hdr_shows: 'shows',
    btn_pause: '⏸ Pause',
    btn_resume: '▶ Resume (all)',
    // Статусные бейджи
    status_idle: 'IDLE',
    status_collecting: 'COLLECTING',
    status_applying: 'APPLYING',
    status_limit: 'LIMIT',
    status_waiting: 'PAUSED',
    status_checking: 'CHECKING LIMIT',
    status_inactive: 'INACTIVE',
    status_all_paused: '⏸ ALL PAUSED',
    status_acc_paused: '⏸ PAUSED',
    // Подписи карточек
    stat_replies: 'Replies',
    stat_tests: 'Tests',
    stat_surveys: '📝 Surveys',
    stat_already: 'Already',
    stat_errors: 'Errors',
    stat_salary: '💰 Salary',
    stat_interviews: '🎯 Interviews',
    stat_new_inv: '📬 New inv.',
    card_waiting: 'Waiting...',
    card_hh_loading: '⏳ Loading HH data...',
    card_sending: 'Sending...',
    btn_acc_pause: '⏸ Pause account',
    btn_acc_resume: '▶ Resume',
    btn_acc_global_pause: '⏸ Global pause',
    btn_resume_touch: '📤 Raise resume',
    btn_clear_discards: '🗑️ Clear discards',
    btn_launch: '▶ Launch',
    btn_delete: '✕ Delete',
    card_apply_tests: 'Apply to vacancies with test',
    letter_section: '✉️ Letter',
    url_section: '🔗 Search URLs',
    btn_save: '💾 Save',
    btn_apply_url: '💾 Apply',
    cookies_expired_badge: '⚠️ Cookies expired! Update cookies',
    errs_in_row: 'errors in a row',
    // Глобальная статистика
    gs_session: '📊 Session',
    gs_found: '🔍 Found',
    gs_applied: '✅ Applied',
    gs_tests: '🧪 Tests',
    gs_errors: '❌ Errors',
    gs_in_db: '💾 In DB',
    gs_in_db_tests: '🧪 Tests',
    sidebar_recent: '📬 Recent Replies',
    recent_empty: 'Waiting for replies...',
    no_accounts: 'No accounts. Add an account in Settings',
    // Статистика резюме
    rs_views: 'views (7d)',
    rs_shows: 'shows',
    rs_inv: 'invitations',
    rs_raise_in: 'raise in',
    rs_raises_avail: 'raises available',
    // Вкладка лога
    log_search_ph: '🔍 Search...',
    log_all_accs: 'All accounts',
    log_all: 'All',
    // Вкладка откликов
    applied_title: '✅ Applied',
    applied_search_ph: '🔍 Search by title / company...',
    applied_all_accs: 'All accounts',
    applied_only_named: 'Only with title',
    col_date: 'Date',
    col_account: 'Account',
    col_vacancy: 'Vacancy',
    col_company: 'Company',
    col_salary: 'Salary',
    btn_show_more: 'Show more',
    shown_of: 'showing',
    shown_of2: 'of',
    // Вкладка тестов
    tests_title: '🧪 Vacancies with tests',
    col_applied_yn: 'Applied',
    col_link: 'Link',
    // Вкладка базы
    db_title: '📂 Vacancy Database',
    db_search_ph: '🔍 Title / company / ID...',
    db_all_statuses: 'All statuses',
    db_status_sent: '✅ Applied',
    db_status_test_passed: '📝 Test passed',
    db_status_test_pending: '🧪 Test pending',
    db_all_accs: 'All accounts',
    col_status: 'Status',
    col_accounts: 'Accounts',
    // HH-статус
    hh_interviews: 'Interviews',
    hh_viewed: 'Viewed',
    hh_discards: 'Discards',
    hh_not_viewed: 'Not viewed',
    hh_updated: 'Updated:',
    hh_inv_list: '📋 Interview invitations:',
    hh_offers: '🏢 Possible offers:',
    hh_no_data: 'No data',
    hh_loading: '⏳ Loading HH data...',
    // Вкладка просмотров
    views_7d: 'Resume views (7d)',
    views_new: 'New views',
    views_shows: 'Search shows',
    views_invitations: 'Invitations (7d)',
    views_inv_new: 'New invitations',
    views_loading: 'Loading view history...',
    btn_load_history: '↻ Load history',
    views_no_data: 'No data (refresh in 15 min)',
    col_employer: 'Company',
    // Вкладка ручного отклика
    apply_title: '🚀 Manual Apply',
    apply_desc: 'Enter vacancy URL or ID — the bot will check if a survey is required, show questions, and submit the reply.',
    apply_label_acc: 'Account',
    apply_label_vacancy: 'Vacancy URL or ID',
    apply_vacancy_ph: 'https://hh.ru/vacancy/130334718 or just 130334718',
    apply_label_tpl: 'Letter template',
    apply_tpl_ph: '— select template —',
    apply_btn_clear: '✕ Clear',
    apply_label_letter: 'Cover letter',
    apply_letter_ph: 'Cover letter (optional)',
    apply_btn_check: '🔍 Check / Apply',
    // Вкладка настроек
    settings_title: '⚙️ Bot Settings',
    btn_apply_settings: '✅ Apply',
    settings_applied: '✅ Settings applied',
    // Подписи параметров настроек
    lbl_pages_per_url: 'Pages per URL',
    hint_pages_per_url: 'How many result pages to load per search query',
    lbl_response_delay: 'Reply delay (s)',
    hint_response_delay: 'Pause between reply batches in seconds',
    lbl_pause_between_cycles: 'Pause between cycles (s)',
    hint_pause_between_cycles: 'Wait after completing a full vacancy processing cycle',
    lbl_batch_responses: 'Reply batch size',
    hint_batch_responses: 'How many replies to send in parallel',
    lbl_limit_check_interval: 'Limit check interval (m)',
    hint_limit_check_interval: 'How often to check daily reply limit reset',
    lbl_min_salary: 'Minimum salary (₽)',
    hint_min_salary: 'Skip vacancies with salary below specified (0 = no filter)',
    lbl_auto_pause_errors: 'Auto-pause on errors',
    hint_auto_pause_errors: 'Auto-pause account after N consecutive errors (0 = disabled)',
    // Разделы настроек
    sec_main_accounts: '👤 Main Accounts',
    sec_main_accounts_desc: 'Add and edit main accounts. Changes are saved to data/accounts.json.',
    sec_url_pool: '🔗 Search URL Pool',
    sec_url_pool_desc: 'Add search URLs — they will appear as checkboxes on each account card.',
    sec_letters: '✉️ Letter Templates',
    sec_letters_desc: 'Create named templates — they will appear in the dropdown on each account card.',
    sec_questionnaire: '📝 Questionnaire Templates',
    sec_questionnaire_desc: 'When a vacancy requires a survey — the bot will fill it automatically.',
    sec_cookies: '🔑 Update Account Cookies',
    sec_sessions: '🌐 Browser Sessions',
    // Форма аккаунта
    acc_field_name: 'Full name',
    acc_field_short: 'Short name',
    acc_field_color: 'Color',
    acc_ph_name: 'Ivan (main)',
    acc_ph_short: 'main',
    acc_cookies_label: 'Cookies (cURL or string)',
    btn_add: '✅ Add',
    btn_add_account: '＋ Add account',
    btn_add_url: '＋ Add URL',
    btn_save_pool: '💾 Save pool',
    btn_add_template: '＋ Add template',
    btn_save_templates: '💾 Save templates',
    // Анкеты
    q_keywords_ph: 'experience, work, QA',
    q_keywords_label: 'Keywords (comma-separated)',
    q_answer_label: 'Answer',
    q_default_label: 'Default answer (if no template matched)',
    q_default_ph: 'I\'d be happy to share more details at the interview.',
    // Раздел cookies
    ck_desc: 'Paste new cURL or cookie string: hhtoken=…',
    btn_update_cookies: '🔑 Update cookies',
    // Сессии
    sess_add: '➕ Add browser session',
    sess_mode_curl: 'cURL / string',
    sess_mode_manual: 'Manual',
    sess_curl_desc: 'Easiest way — Copy as cURL',
    sess_name_label: 'Name (optional)',
    sess_name_ph: 'e.g.: Maria',
    sess_letter_label: 'Cover letter (optional)',
    btn_connect: '🔗 Connect session',
    sess_active: '🟢 active',
    sess_inactive: '⭕ inactive',
    // Диалоги подтверждения
    confirm_delete: 'Delete',
    confirm_cancel: 'Cancel',
    // Горячие клавиши
    shortcuts_title: '⌨️ Keyboard Shortcuts',
    shortcuts_tabs: 'Switch tab',
    shortcuts_pause: 'Pause / resume all',
    shortcuts_help: 'This window',
    shortcuts_esc: 'Close this window',
    btn_close: 'Close',
    // Уведомления
    notif_new_inv: '📬 New invitation — ',
    notif_inv_count_pre: 'Now',
    notif_inv_count_mid: 'interviews (+',
    notif_limit: '🚫 Limit — ',
    notif_limit_body: 'Daily reply limit reached',
    notif_cookies: '⚠️ Cookies expired — ',
    notif_cookies_body: 'Update cookies in account settings',
    // Заголовки страниц
    title_limit: '🚫 LIMIT | HH Bot',
    title_paused: '⏸ Paused | HH Bot',
    // Тексты диалогов подтверждения
    confirm_del_acc_pre: 'Delete account',
    confirm_del_acc_body: 'Worker will be stopped.',
    confirm_del_db_pre: 'Delete',
    confirm_del_db_mid: 'from DB?',
    confirm_del_db_body: 'Bot will be able to apply again.',
    confirm_del_sess: 'Delete browser session?',
  }
};

function t(key) {
  return (T[lang]?.[key]) ?? (T.ru[key]) ?? key;
}

function applyI18n() {
  document.documentElement.lang = lang;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    const val = t(key);
    // Для th с сортировочными стрелками сохраняем span со стрелкой
    const arrow = el.querySelector('.sort-arrow');
    if (arrow) {
      // Заменяем текст перед span со стрелкой
      const nodes = Array.from(el.childNodes);
      const textNode = nodes.find(n => n.nodeType === Node.TEXT_NODE);
      if (textNode) textNode.textContent = val + ' ';
      else el.insertBefore(document.createTextNode(val + ' '), el.firstChild);
    } else {
      el.textContent = val;
    }
  });
  document.querySelectorAll('[data-i18n-ph]').forEach(el => {
    el.placeholder = t(el.dataset.i18nPh);
  });
  // Пересобираем подписи и подсказки настроек
  document.querySelectorAll('[data-setting-label]').forEach(el => {
    const key = el.dataset.settingLabel;
    const def = SETTINGS_DEF.find(s => s.key === key);
    if (def) {
      const span = el.querySelector('span');
      el.textContent = t(def.labelKey) + ' ';
      if (span) el.appendChild(span);
    }
  });
  document.querySelectorAll('[data-setting-desc]').forEach(el => {
    const key = el.dataset.settingDesc;
    const def = SETTINGS_DEF.find(s => s.key === key);
    if (def) el.textContent = t(def.descKey);
  });
  if (State && State.lastSnapshot) {
    try { renderAll(State.lastSnapshot); } catch(e) {}
  }
}

function toggleLang() {
  lang = lang === 'ru' ? 'en' : 'ru';
  localStorage.setItem('hh-lang', lang);
  document.getElementById('lang-btn').textContent = lang.toUpperCase();
  applyI18n();
}

// ── State ──────────────────────────────────────────────────────
const State = {
  ws: null,
  lastSnapshot: null,
  currentTab: 'main',
  reconnectDelay: 1000,
  reconnectTimer: null,
  logNodeCount: 0,
  MAX_LOG_NODES: 100,
  prevInterviews: {},      // {acc_idx: count} — для браузерных уведомлений
  prevLimitState: {},      // {acc_idx: bool}
  prevCookiesExpired: {},  // {acc_idx: bool}
  compactCards: new Set(), // idx карточек в компактном режиме
  logLevel: '',          // фильтр уровня лога
};
const AppliedSort = { field: 'at', dir: -1 };  // -1=desc 1=asc
const DBSort      = { field: 'at', dir: -1 };

// Описание конфигурации настроек
const SETTINGS_DEF = [
  { key: 'pages_per_url',        labelKey: 'lbl_pages_per_url',        descKey: 'hint_pages_per_url',        min: 5,  max: 100, step: 5  },
  { key: 'response_delay',       labelKey: 'lbl_response_delay',       descKey: 'hint_response_delay',       min: 0,  max: 30,  step: 1  },
  { key: 'pause_between_cycles', labelKey: 'lbl_pause_between_cycles', descKey: 'hint_pause_between_cycles', min: 15, max: 600, step: 15 },
  { key: 'batch_responses',      labelKey: 'lbl_batch_responses',      descKey: 'hint_batch_responses',      min: 1,  max: 10,  step: 1  },
  { key: 'limit_check_interval', labelKey: 'lbl_limit_check_interval', descKey: 'hint_limit_check_interval', min: 5,  max: 120, step: 5  },
  { key: 'min_salary',           labelKey: 'lbl_min_salary',           descKey: 'hint_min_salary',           min: 0,  max: 300000, step: 10000 },
  { key: 'auto_pause_errors',    labelKey: 'lbl_auto_pause_errors',    descKey: 'hint_auto_pause_errors',    min: 0,  max: 20,  step: 1  },
];

// Один раз строим UI настроек
function buildSettings() {
  const grid = document.getElementById('settings-grid');
  grid.innerHTML = '';
  SETTINGS_DEF.forEach(s => {
    const row = document.createElement('div');
    row.className = 'setting-row';
    row.dataset.settingKey = s.key;
    row.innerHTML = `
      <div class="setting-label" data-setting-label="${s.key}">${t(s.labelKey)} <span id="sv-${s.key}">—</span></div>
      <div class="setting-desc" data-setting-desc="${s.key}">${t(s.descKey)}</div>
      <input type="range" id="sr-${s.key}" min="${s.min}" max="${s.max}" step="${s.step}" value="${s.min}"
        oninput="document.getElementById('sv-${s.key}').textContent=this.value">
    `;
    grid.appendChild(row);
  });
}

// ── Letter templates (Settings) ──────────────────────────────
function ltRenderTemplates(templates) {
  const list = document.getElementById('lt-templates-list');
  if (!list) return;
  list.innerHTML = '';
  (templates || []).forEach((t, i) => {
    const row = document.createElement('div');
    row.className = 'q-template-row';
    row.dataset.idx = i;
    row.innerHTML =
      `<button class="q-del-btn" onclick="ltDelTemplate(${i})">✕</button>` +
      `<div style="flex:1">` +
        `<input class="q-keywords-input" placeholder="Название шаблона (напр: IT, Аналитик)" value="${esc(t.name||'')}">` +
        `<textarea class="q-answer-input" rows="3" placeholder="Текст письма...">${esc(t.text||'')}</textarea>` +
      `</div>`;
    list.appendChild(row);
  });
}

function ltAddTemplate() {
  const list = document.getElementById('lt-templates-list');
  if (!list) return;
  const i = list.children.length;
  const row = document.createElement('div');
  row.className = 'q-template-row';
  row.dataset.idx = i;
  row.innerHTML =
    `<button class="q-del-btn" onclick="ltDelTemplate(${i})">✕</button>` +
    `<div style="flex:1">` +
      `<input class="q-keywords-input" placeholder="Название шаблона">` +
      `<textarea class="q-answer-input" rows="3" placeholder="Текст письма..."></textarea>` +
    `</div>`;
  list.appendChild(row);
}

function ltDelTemplate(idx) {
  const list = document.getElementById('lt-templates-list');
  if (!list) return;
  const rows = list.querySelectorAll('.q-template-row');
  if (rows[idx]) rows[idx].remove();
  // Переиндексируем кнопки удаления
  list.querySelectorAll('.q-template-row').forEach((r, i) => {
    r.dataset.idx = i;
    const btn = r.querySelector('.q-del-btn');
    if (btn) btn.onclick = () => ltDelTemplate(i);
  });
}

function ltReadTemplates() {
  const list = document.getElementById('lt-templates-list');
  if (!list) return [];
  return Array.from(list.querySelectorAll('.q-template-row')).map(r => ({
    name: (r.querySelector('.q-keywords-input')?.value || '').trim(),
    text: (r.querySelector('.q-answer-input')?.value || '').trim(),
  })).filter(t => t.name || t.text);
}

function ltSave() {
  const templates = ltReadTemplates();
  sendCmd({ type: 'set_letter_templates', templates });
  const st = document.getElementById('lt-status');
  if (st) { st.textContent = '✅ Сохранено'; setTimeout(() => { st.textContent = ''; }, 3000); }
}

function ltSyncFromSnapshot(snap) {
  const templates = snap?.config?.letter_templates || [];
  ltRenderTemplates(templates);
}

// ── LLM multi-profile ─────────────────────────────────────────
let _llmDetectTimers = {};

function llmProfileAdd(profile) {
  const p = profile || {name: '', api_key: '', base_url: '', model: '', enabled: true};
  const list = document.getElementById('llm-profiles-list');
  const idx = list.children.length;
  const row = document.createElement('div');
  row.className = 'llm-profile-row' + (p.enabled === false ? ' disabled' : '');
  row.dataset.idx = idx;
  row.innerHTML = `
    <div class="llm-profile-row-header">
      <input class="apply-input lp-name" style="font-size:11px;flex:1" placeholder="Название (например: DeepSeek)" value="${esc(p.name||'')}">
      <label style="display:flex;align-items:center;gap:4px;font-size:11px;cursor:pointer;white-space:nowrap">
        <input type="checkbox" class="lp-enabled" ${p.enabled !== false ? 'checked' : ''} style="accent-color:var(--cyan)"> Вкл
      </label>
      <button class="btn-sm" style="color:var(--red);border-color:var(--red);padding:1px 8px" onclick="this.closest('.llm-profile-row').remove();llmProfileReindex()">✕</button>
    </div>
    <div class="llm-profile-fields">
      <div>
        <div style="font-size:10px;color:var(--dim);margin-bottom:2px">API Key</div>
        <input class="apply-input lp-key" type="password" style="font-size:11px" placeholder="sk-..." value="${esc(p.api_key||'')}" oninput="llmProfileDetectDebounce(this)">
      </div>
      <div>
        <div style="font-size:10px;color:var(--dim);margin-bottom:2px">Модель</div>
        <input class="apply-input lp-model" style="font-size:11px" placeholder="gpt-4o-mini" value="${esc(p.model||'')}">
      </div>
    </div>
    <div style="display:flex;gap:6px;align-items:center">
      <div style="flex:1">
        <div style="font-size:10px;color:var(--dim);margin-bottom:2px">Base URL</div>
        <input class="apply-input lp-url" style="font-size:11px" placeholder="https://api.openai.com/v1" value="${esc(p.base_url||'')}">
      </div>
      <div style="display:flex;flex-direction:column;gap:3px;padding-top:14px">
        <button class="btn-sm" onclick="llmProfileDetect(this.closest('.llm-profile-row'))" title="Определить провайдера и загрузить модели">🔍 Определить</button>
        <span class="lp-status" style="font-size:10px;color:var(--dim)"></span>
      </div>
    </div>
  `;
  list.appendChild(row);
}

function llmProfileReindex() {
  document.querySelectorAll('#llm-profiles-list .llm-profile-row').forEach((row, i) => { row.dataset.idx = i; });
}

function llmProfileDetectDebounce(keyInput) {
  const row = keyInput.closest('.llm-profile-row');
  const idx = row.dataset.idx;
  clearTimeout(_llmDetectTimers[idx]);
  _llmDetectTimers[idx] = setTimeout(() => llmProfileDetect(row), 900);
}

async function llmProfileDetect(row) {
  const keyEl = row.querySelector('.lp-key');
  const urlEl = row.querySelector('.lp-url');
  const modelEl = row.querySelector('.lp-model');
  const st = row.querySelector('.lp-status');
  const key = keyEl?.value.trim() || '';
  if (!key || key.length < 8) return;
  if (st) { st.textContent = '⏳...'; st.style.color = 'var(--dim)'; }
  try {
    const res = await fetch('/api/llm_detect', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({api_key: key, base_url: urlEl?.value.trim() || ''})
    });
    const data = await res.json();
    if (!data.ok) {
      if (st) { st.textContent = '❌ ' + (data.error||'').slice(0,40); st.style.color = 'var(--red)'; }
      return;
    }
    if (data.base_url && urlEl && !urlEl.value.trim()) urlEl.value = data.base_url;
    if (data.models?.length) {
      if (modelEl && !modelEl.value.trim()) modelEl.value = data.models[0];
      if (st) { st.textContent = `✅ ${data.models.length} моделей`; st.style.color = 'var(--green)'; }
      llmShowModelPicker(row, data.base_url, data.models);
    } else {
      if (st) { st.textContent = '⚠️ Нет моделей'; st.style.color = 'var(--yellow)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  }
}

function llmShowModelPicker(row, base_url, models) {
  row.querySelector('.lp-model-picker')?.remove();
  const modelEl = row.querySelector('.lp-model');
  const picker = document.createElement('select');
  picker.className = 'apply-input lp-model-picker';
  picker.style.cssText = 'font-size:11px;margin-top:4px;width:100%';
  picker.innerHTML = '<option value="">— выбрать из найденных —</option>' +
    models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
  picker.onchange = () => {
    if (picker.value) { modelEl.value = picker.value; picker.remove(); }
  };
  modelEl.parentElement.appendChild(picker);
}

function llmProfilesRead() {
  const rows = document.querySelectorAll('#llm-profiles-list .llm-profile-row');
  return [...rows].map(row => ({
    name: row.querySelector('.lp-name')?.value.trim() || '',
    api_key: row.querySelector('.lp-key')?.value.trim() || '',
    base_url: row.querySelector('.lp-url')?.value.trim() || '',
    model: row.querySelector('.lp-model')?.value.trim() || '',
    enabled: row.querySelector('.lp-enabled')?.checked ?? true,
  }));
}

async function llmSave(btn) {
  const st = document.getElementById('llm-status');
  if (btn) btn.disabled = true;
  if (st) st.textContent = '⏳ Сохраняю...';
  try {
    const profiles = llmProfilesRead();
    const mode = document.getElementById('llm-profile-mode')?.value || 'fallback';
    // Сохраняем профили отдельно
    await fetch('/api/llm_profiles', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({profiles, mode})
    });
    // Сохраняем остальные настройки через llm_config
    const res = await fetch('/api/llm_config', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        system_prompt: document.getElementById('llm-system-prompt')?.value || '',
        enabled: document.getElementById('llm-enabled')?.checked || false,
        auto_send: document.getElementById('llm-auto-send')?.checked || false,
        use_cover_letter: document.getElementById('llm-use-cover-letter')?.checked ?? true,
        use_resume: document.getElementById('llm-use-resume')?.checked ?? true,
        api_key: profiles[0]?.api_key || '',
        base_url: profiles[0]?.base_url || '',
        model: profiles[0]?.model || '',
      })
    });
    const data = await res.json();
    if (st) { st.textContent = `✅ Сохранено (${profiles.length} профилей)`; st.style.color = 'var(--green)'; }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
    setTimeout(() => { if (st) { st.textContent = ''; st.style.color = ''; } }, 4000);
  }
}

async function llmGlobalToggle(btn) {
  if (btn) btn.disabled = true;
  try {
    const res = await fetch('/api/llm_toggle', {method: 'POST'});
    const data = await res.json();
    _llmUpdateToggleBtn(data.llm_enabled);
  } catch(e) {}
  finally { if (btn) btn.disabled = false; }
}

function _llmUpdateToggleBtn(enabled) {
  const btn = document.getElementById('llm-global-toggle-btn');
  if (!btn) return;
  if (enabled) {
    btn.textContent = '▶️ ВКЛ';
    btn.style.color = 'var(--green)';
    btn.style.borderColor = 'var(--green)';
  } else {
    btn.textContent = '⏸ ВЫКЛ';
    btn.style.color = 'var(--dim)';
    btn.style.borderColor = 'var(--dim)';
  }
}

function syncLlmSettings(snap) {
  const cfg = snap?.config || {};
  const as = document.getElementById('llm-auto-send');
  const cl = document.getElementById('llm-use-cover-letter');
  const ur = document.getElementById('llm-use-resume');
  const fq = document.getElementById('llm-fill-questionnaire');
  const modeEl = document.getElementById('llm-profile-mode');
  if (as && cfg.llm_auto_send !== undefined) as.checked = cfg.llm_auto_send;
  if (cl && cfg.llm_use_cover_letter !== undefined) cl.checked = cfg.llm_use_cover_letter;
  if (ur && cfg.llm_use_resume !== undefined) ur.checked = cfg.llm_use_resume;
  if (fq && cfg.llm_fill_questionnaire !== undefined) fq.checked = cfg.llm_fill_questionnaire;
  if (modeEl && cfg.llm_profile_mode) modeEl.value = cfg.llm_profile_mode;
  // Обновляем глобальную кнопку-переключатель
  if (cfg.llm_enabled !== undefined) _llmUpdateToggleBtn(cfg.llm_enabled);
  // Рендерим профили только при пустом списке, чтобы не затереть пользовательские правки
  const list = document.getElementById('llm-profiles-list');
  if (list && list.children.length === 0 && cfg.llm_profiles?.length) {
    cfg.llm_profiles.forEach(p => llmProfileAdd(p));
  }
  // Заполняем выбор аккаунта для предпросмотра резюме
  const sel = document.getElementById('llm-resume-acc-sel');
  if (sel && snap?.accounts?.length && sel.options.length !== snap.accounts.length) {
    sel.innerHTML = snap.accounts.map(a =>
      `<option value="${a.idx}">${esc(a.short || a.name)}</option>`).join('');
  }
}

// ── LLM resume preview ───────────────────────────────────────
async function llmPreviewResume(btn) {
  const sel = document.getElementById('llm-resume-acc-sel');
  const pre = document.getElementById('llm-resume-preview');
  const st  = document.getElementById('llm-resume-status');
  const idx = sel?.value;
  if (!idx && idx !== 0) return;
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳ Загружаю…'; st.style.color = 'var(--dim)'; }
  try {
    const res = await fetch(`/api/account/${idx}/resume_text`);
    const data = await res.json();
    if (data.ok && data.text) {
      if (pre) { pre.textContent = data.text; pre.style.display = ''; }
      if (st) { st.textContent = `✅ ${data.length} симв.`; st.style.color = 'var(--green)'; }
    } else {
      if (pre) { pre.style.display = 'none'; }
      if (st) { st.textContent = '⚠️ Резюме не удалось извлечь (пустой результат). Проверь куки.'; st.style.color = 'var(--yellow)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── LLM per-account toggle ────────────────────────────────────
function llmToggleAccount(idx, btn) {
  sendCmd({type: 'account_llm', idx});
}

// ── LLM tab: interviews from DB ───────────────────────────────
async function llmInterviewsLoad() {
  if (_llmLoading) return;   // уже идёт запрос — не запускаем параллельный
  _llmLoading = true;
  const acc = document.getElementById('llm-log-acc-filter')?.value || '';
  const statusF = document.getElementById('llm-log-sent-filter')?.value || '';
  let url = `/api/interviews?limit=2000${acc ? '&acc=' + encodeURIComponent(acc) : ''}${statusF ? '&status=' + encodeURIComponent(statusF) : ''}`;
  let rows;
  try {
    const res = await fetch(url);
    rows = await res.json();
    _llmLastDbRefresh = Date.now();
  } catch(e) {
    _llmLoading = false;
    return; // Сетевая ошибка — не трогаем текущее содержимое таблицы
  } finally {
    _llmLoading = false;
  }

  const table = document.getElementById('llm-interviews-table');
  const empty = document.getElementById('llm-interviews-empty');
  const countEl = document.getElementById('llm-log-count');
  const tbody = document.getElementById('llm-interviews-body');
  if (!tbody) return;
  if (countEl) countEl.textContent = rows.length ? `${rows.length} записей` : '';

  if (rows.length === 0) {
    const hasRows = tbody.querySelectorAll('tr').length > 0 &&
                    !tbody.querySelector('tr td[colspan]');
    if (statusF || acc) {
      // Фильтр активен — показываем сообщение, таблицу не прячем
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--dim);padding:12px">Нет записей по выбранному фильтру</td></tr>`;
      if (table) table.style.display = '';
      if (empty) empty.style.display = 'none';
    } else if (!hasRows) {
      // Таблица действительно пуста и раньше была пустой — показываем заглушку
      if (table) table.style.display = 'none';
      if (empty) empty.style.display = '';
    }
    // Если hasRows && нет фильтра — оставляем текущее содержимое (избегаем мигания)
    return;
  }
  if (table) table.style.display = '';
  if (empty) empty.style.display = 'none';

  const statusBadge = s => {
    if (s === 'replied')         return '<span class="llm-sent-badge">✅ Отправлено</span>';
    if (s === 'draft')           return '<span class="llm-draft-badge">📝 Черновик</span>';
    if (s === 'pending_reply')   return '<span style="color:var(--yellow);font-size:11px">⏳ Ждёт</span>';
    if (s === 'chat_closed')     return '<span style="color:var(--dim);font-size:11px">🔒 Закрыт</span>';
    return '<span style="color:var(--dim);font-size:11px">— нет</span>';
  };

  tbody.innerHTML = rows.map(r => {
    const empMsg = esc(r.employer_last_msg || '—').replace(/\n/g, '<br>');
    const botReply = esc(r.llm_reply || '').replace(/\n/g, '<br>');
    const source = esc(r.answer_source || (r.llm_reply ? 'llm' : ''));
    const negLink = r.neg_id
      ? `<a href="https://hh.ru/chat/${r.neg_id}" target="_blank" style="font-size:10px;color:var(--cyan)">🔗</a>` : '';
    const dateStr = (r.last_seen || r.first_seen || '').replace('T', ' ').slice(0, 16);
    return `<tr>
      <td style="font-size:11px;color:var(--dim);white-space:nowrap">${dateStr}</td>
      <td style="font-size:11px;color:${colorVar(r.acc_color||'')}">${esc(r.acc||'')}</td>
      <td style="font-size:11px">${esc(r.employer||'')} ${negLink}</td>
      <td style="font-size:11px;color:var(--dim)">${esc(r.vacancy_title||'')}</td>
      <td class="llm-msg-cell">${empMsg}</td>
      <td class="llm-reply-cell">${botReply}</td>
      <td style="font-size:11px;color:var(--dim)">${source}</td>
      <td>${statusBadge(r.status)}</td>
    </tr>`;
  }).join('');

  // Заполняем фильтр аккаунтов из загруженных данных
  const accSel = document.getElementById('llm-log-acc-filter');
  if (accSel) {
    const known = new Set([...accSel.options].map(o => o.value).filter(Boolean));
    rows.forEach(r => {
      if (r.acc && !known.has(r.acc)) {
        const opt = document.createElement('option');
        opt.value = r.acc; opt.textContent = r.acc;
        accSel.appendChild(opt);
        known.add(r.acc);
      }
    });
  }

  // Статистика по аккаунтам: всегда из полных нефильтрованных данных, поэтому загружаем всё заново
  llmRenderAccStats();
}

async function llmRenderAccStats() {
  const statsEl = document.getElementById('llm-acc-stats');
  if (!statsEl) return;
  let all;
  try {
    const res = await fetch('/api/interviews?limit=2000');
    all = await res.json();
  } catch(e) { return; }

  // Группируем по аккаунту
  const byAcc = {};
  all.forEach(r => {
    const a = r.acc || '?';
    if (!byAcc[a]) byAcc[a] = {acc: a, color: r.acc_color || '', pending: 0, draft: 0, replied: 0, total: 0};
    byAcc[a].total++;
    if (r.status === 'pending_reply') byAcc[a].pending++;
    else if (r.status === 'draft')    byAcc[a].draft++;
    else if (r.status === 'replied')  byAcc[a].replied++;
  });

  statsEl.innerHTML = Object.values(byAcc).map(a => `
    <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:6px;padding:8px 14px;min-width:160px">
      <div style="font-size:12px;font-weight:700;color:${colorVar(a.color)};margin-bottom:6px">${esc(a.acc)}</div>
      <div style="display:flex;gap:10px;font-size:12px">
        <span title="Ждёт ответа">⏳ <b>${a.pending}</b></span>
        <span title="Черновик" style="color:var(--yellow)">📝 <b>${a.draft}</b></span>
        <span title="Отправлено" style="color:var(--green)">✅ <b>${a.replied}</b></span>
      </div>
    </div>`).join('');
}

async function llmRunNow(btn) {
  btn.disabled = true; btn.textContent = '⏳…';
  try {
    await fetch('/api/llm_run_now', {method:'POST'});
    btn.textContent = '✅ Запущено';
    setTimeout(() => { btn.textContent = '▶ Запустить сейчас'; btn.disabled = false; }, 3000);
    setTimeout(() => llmInterviewsLoad(), 8000);
  } catch(e) {
    btn.textContent = '▶ Запустить сейчас'; btn.disabled = false;
  }
}

async function llmResetReplied(btn) {
  if (!confirm('Сбросить историю «уже отвечали» для всех аккаунтов?\n\nБот повторно обработает все чаты работодателей в следующем цикле.')) return;
  const orig = btn.textContent;
  btn.disabled = true; btn.textContent = '⏳…';
  try {
    const r = await fetch('/api/llm_reset_replied', {method:'POST'});
    const data = await r.json();
    btn.textContent = '✅ Сброшено';
    setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 4000);
  } catch(e) {
    btn.textContent = orig; btn.disabled = false;
  }
}

// ── LLM log tab: debug log from WS snapshot + auto-refresh DB ─
let _llmLastDbRefresh = 0;
let _llmDebugHash = '';
let _llmLoading = false;   // Защита: только один запрос одновременно
function _llmUpdateAccToggles(snap) {
  const container = document.getElementById('llm-acc-toggles');
  if (!container || !snap?.accounts) return;
  const accs = snap.accounts;
  // Добавляем недостающие кнопки
  accs.forEach(acc => {
    let btn = document.getElementById(`llm-acc-btn-${acc.idx}`);
    if (!btn) {
      btn = document.createElement('button');
      btn.id = `llm-acc-btn-${acc.idx}`;
      btn.style.cssText = 'padding:4px 10px;border-radius:4px;border:1px solid;cursor:pointer;font-size:11px;background:transparent;transition:color .15s,border-color .15s';
      btn.setAttribute('data-idx', acc.idx);
      btn.onclick = function() { llmToggleAccount(acc.idx, this); };
      container.appendChild(btn);
    }
    // Обновляем подпись и цвет
    const on = acc.llm_enabled !== false;
    btn.textContent = `🤖 ${esc(acc.short || acc.name)}`;
    btn.style.color = on ? colorVar(acc.color || 'green') : 'var(--dim)';
    btn.style.borderColor = on ? colorVar(acc.color || 'green') : 'var(--dim)';
    btn.style.opacity = on ? '1' : '0.5';
    btn.title = on ? 'LLM вкл — нажми чтобы выключить' : 'LLM выкл — нажми чтобы включить';
  });
  // Удаляем устаревшие кнопки
  const idxSet = new Set(accs.map(a => String(a.idx)));
  container.querySelectorAll('[id^="llm-acc-btn-"]').forEach(btn => {
    const i = btn.id.replace('llm-acc-btn-', '');
    if (!idxSet.has(i)) btn.remove();
  });
}

function renderLlmLog(snap) {
  if (!snap) return;

  // Обновляем LLM-переключатели аккаунтов
  _llmUpdateAccToggles(snap);

  // Автообновляем таблицу переговоров из БД каждые 30 секунд
  const now = Date.now();
  if (now - _llmLastDbRefresh > 30000) {
    _llmLastDbRefresh = now;
    llmInterviewsLoad();
  }

  // Обновляем debug log из журнала активности, сохраняя позицию прокрутки
  const debugBox = document.getElementById('llm-debug-log');
  const debugCount = document.getElementById('llm-debug-count');
  if (debugBox && snap.log) {
    const debugEntries = snap.log.filter(e => (e.message || '').includes('🤖') || (e.message || '').includes('LLM'));
    // Пропускаем пересборку, если содержимое не изменилось
    const newHash = debugEntries.map(e => e.time + e.message).join('|');
    if (newHash === _llmDebugHash) return;
    _llmDebugHash = newHash;
    if (debugCount) debugCount.textContent = debugEntries.length ? `(${debugEntries.length})` : '';
    // Сохраняем позицию прокрутки
    const wasAtBottom = debugBox.scrollHeight - debugBox.scrollTop <= debugBox.clientHeight + 4;
    const savedTop = debugBox.scrollTop;
    debugBox.innerHTML = debugEntries.length === 0
      ? '<span style="color:var(--dim)">Нет LLM-записей в логе. Первый запуск через ~15 мин после старта HH-статистики.</span>'
      : debugEntries.map(e => {
          const lvlColor = e.level === 'error' ? 'var(--red)' : e.level === 'warning' ? 'var(--yellow)' : e.level === 'success' ? 'var(--green)' : 'var(--dim)';
          const chatLink = e.neg_id ? `<a href="https://hh.ru/chat/${e.neg_id}" target="_blank" style="color:var(--cyan);text-decoration:none" title="Открыть чат">🔗</a> ` : '';
          return `<div style="line-height:1.5"><span style="color:var(--dim)">${esc(e.time||'')}</span> <span style="color:${colorVar(e.color)}">${esc(e.acc||'')}</span> ${chatLink}<span style="color:${lvlColor}">${esc(e.message||'')}</span></div>`;
        }).join('');
    // Восстанавливаем прокрутку: если были внизу, остаёмся внизу, иначе возвращаем позицию
    if (wasAtBottom) debugBox.scrollTop = debugBox.scrollHeight;
    else debugBox.scrollTop = savedTop;
  }
}

// ── Letter in account cards ───────────────────────────────────
function syncLetterSelects(snap) {
  const templates = snap?.config?.letter_templates || [];
  if (!templates.length) return;
  document.querySelectorAll('[id^="acc-letter-tpl-"]').forEach(sel => {
    const idx = sel.id.replace('acc-letter-tpl-', '');
    const ta = document.getElementById('acc-letter-ta-' + idx);
    const curText = ta?.value || '';
    const matched = templates.findIndex(t => t.text === curText);
    // Пересобираем только если изменилось количество или первый option неверный
    const needsRebuild = sel.options.length !== templates.length + 2 ||
      (templates.length > 0 && sel.options[1]?.text !== templates[0].name);
    if (!needsRebuild) return;
    sel.innerHTML = '<option value="">— пусто —</option>' +
      templates.map((t, i) => `<option value="${i}"${matched===i?' selected':''}>${esc(t.name)}</option>`).join('') +
      '<option value="__custom__"' + (curText && matched === -1 ? ' selected' : '') + '>✏️ Своё</option>';
  });
}

function letterPickTpl(idx) {
  const sel = document.getElementById('acc-letter-tpl-' + idx);
  const ta  = document.getElementById('acc-letter-ta-'  + idx);
  if (!sel || !ta) return;
  const val = sel.value;
  if (val === '' ) { ta.value = ''; return; }
  if (val === '__custom__') { ta.focus(); return; }
  const templates = State.lastSnapshot?.config?.letter_templates || [];
  const tpl = templates[parseInt(val)];
  if (tpl) ta.value = tpl.text;
}

async function letterSave(idx, btn) {
  const ta = document.getElementById('acc-letter-ta-' + idx);
  const st = document.getElementById('acc-letter-st-' + idx);
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳...'; st.style.color = 'var(--dim)'; }
  try {
    const res = await fetch(`/api/account/${idx}/set_letter`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ letter: ta?.value || '' })
    });
    const data = await res.json();
    if (data.ok) {
      if (st) { st.textContent = '✅ Сохранено'; st.style.color = 'var(--green)'; }
      // Обновляем кеш ApplyLetters
      ApplyLetters[idx] = ta?.value || '';
    } else {
      if (st) { st.textContent = '❌ ' + (data.error || 'Ошибка'); st.style.color = 'var(--red)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) { btn.disabled = false; }
    if (st) setTimeout(() => { if (st.textContent !== '') st.textContent = ''; }, 4000);
  }
}

// ── Search URLs section ───────────────────────────────────────
const HH_AREAS = {
  '1':'Москва','2':'Санкт-Петербург','3':'Екатеринбург','4':'Новосибирск',
  '5':'Казань','16':'Нижний Новгород','54':'Краснодар','88':'Россия','1001':'СНГ'
};
const HH_EXP = {
  'noExperience':'без опыта','between1And3':'1–3 года',
  'between3And6':'3–6 лет','moreThan6':'6+ лет'
};
const HH_SCHEDULE = {
  'fullDay':'полный день','shift':'сменный','flexible':'гибкий',
  'remote':'удалённо','flyInFlyOut':'вахта'
};

function parseUrlFilter(url) {
  try {
    const u = new URL(url.startsWith('http') ? url : 'https://' + url);
    const p = u.searchParams;
    const parts = [];

    const text = p.get('text');
    if (text) parts.push('🔍 ' + decodeURIComponent(text.replace(/\+/g,' ')));

    const resume = p.get('resume');
    if (resume && !text) parts.push('📄 По резюме');

    const area = p.get('area');
    if (area) parts.push('📍 ' + (HH_AREAS[area] || 'регион ' + area));

    const exp = p.get('experience');
    if (exp) parts.push('⏱ ' + (HH_EXP[exp] || exp));

    const sal = p.get('salary');
    if (sal) parts.push('💰 от ' + Number(sal).toLocaleString('ru') + '₽');

    const sched = p.get('schedule');
    if (sched) parts.push(HH_SCHEDULE[sched] || sched);

    const role = p.get('professional_role');
    if (role) parts.push('👔 роль ' + role);

    const order = p.get('order_by');
    if (order === 'publication_time') parts.push('🕐 по дате');
    else if (order === 'salary_desc') parts.push('💹 по зарплате↓');

    return parts.length ? parts.join('  ') : '🔗 ' + u.pathname;
  } catch(e) { return url; }
}

// ── URL pool (Settings) ───────────────────────────────────────
function buildPoolRow(item, rowIdx) {
  const url = typeof item === 'string' ? item : (item?.url || '');
  const pages = typeof item === 'object' && item !== null ? (item?.pages ?? '') : '';
  const badge = parseUrlFilter(url);
  return `<div class="url-row" id="pool-row-${rowIdx}">
    <div class="url-badge">${badge}</div>
    <div style="display:flex;gap:4px;align-items:center">
      <input class="apply-input url-input" style="font-size:10px;padding:2px 6px;flex:1"
        value="${esc(url)}" oninput="urlPoolReparse(${rowIdx},this.value)">
      <input type="number" class="apply-input url-pages-input" min="1" max="200"
        style="font-size:10px;padding:2px 4px;width:54px;text-align:center"
        placeholder="стр." title="Глубина поиска (страниц)" value="${esc(String(pages))}">
      <button class="btn-sm" style="padding:2px 7px;color:var(--red);border-color:var(--red)"
        onclick="urlPoolRemoveRow(${rowIdx})">✕</button>
    </div>
  </div>`;
}

function urlPoolReparse(rowIdx, val) {
  const badge = document.querySelector(`#pool-row-${rowIdx} .url-badge`);
  if (badge) badge.textContent = parseUrlFilter(val);
}

function urlPoolRemoveRow(rowIdx) {
  const row = document.getElementById(`pool-row-${rowIdx}`);
  if (row) row.remove();
  document.getElementById('url-pool-rows')?.querySelectorAll('.url-row').forEach((r, i) => {
    r.id = `pool-row-${i}`;
    const inp = r.querySelector('.url-input');
    if (inp) inp.oninput = function() { urlPoolReparse(i, this.value); };
    const btn = r.querySelector('button');
    if (btn) btn.onclick = () => urlPoolRemoveRow(i);
  });
}

function urlPoolAddRow() {
  const container = document.getElementById('url-pool-rows');
  if (!container) return;
  const rowIdx = container.querySelectorAll('.url-row').length;
  const div = document.createElement('div');
  div.innerHTML = buildPoolRow('', rowIdx);
  container.appendChild(div.firstElementChild);
}

async function urlPoolSave(btn) {
  const container = document.getElementById('url-pool-rows');
  if (!container) return;
  const globalPages = State.lastSnapshot?.config?.pages_per_url || 40;
  const urls = Array.from(container.querySelectorAll('.url-row')).map(row => {
    const urlInp = row.querySelector('.url-input');
    const pagesInp = row.querySelector('.url-pages-input');
    const url = urlInp?.value?.trim() || '';
    const pages = parseInt(pagesInp?.value) || globalPages;
    return {url, pages};
  }).filter(u => u.url);
  const st = document.getElementById('url-pool-st');
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳...'; st.style.color = 'var(--dim)'; }
  try {
    sendCmd({type: 'set_url_pool', urls});
    if (st) { st.textContent = `✅ Сохранено (${urls.length} URL)`; st.style.color = 'var(--green)'; }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
    setTimeout(() => { if (st) st.textContent = ''; }, 4000);
  }
}

function urlPoolBuild(snap) {
  const el = document.getElementById('url-pool-rows');
  if (!el || el.dataset.built === 'true') return;
  el.dataset.built = 'true';
  el.innerHTML = '';
  const pool = snap?.config?.url_pool || [];
  pool.forEach((item, i) => {
    const div = document.createElement('div');
    div.innerHTML = buildPoolRow(item, i);
    el.appendChild(div.firstElementChild);
  });
  if (!pool.length) {
    el.innerHTML = '<div style="font-size:11px;color:var(--dim)">Пул пустой — добавьте первый URL</div>';
  }
}

// ── URL selector on account cards ────────────────────────────
function syncAccUrlChecks(snap) {
  const pool = snap?.config?.url_pool || [];
  (snap?.accounts || []).filter(a => !a.temp || a.bot_active).forEach(acc => {
    const container = document.getElementById(`acc-url-checks-${acc.idx}`);
    const wrap = document.getElementById(`acc-url-wrap-${acc.idx}`);
    if (!container || (wrap && wrap.open)) return; // Не перезаписываем, пока пользователь выбирает
    const selected = new Set(acc.urls || []);
    if (!pool.length) {
      container.innerHTML = '<div style="font-size:11px;color:var(--dim)">Пул пустой — добавьте URL в Настройках</div>';
      return;
    }
    const globalPages = State.lastSnapshot?.config?.pages_per_url || 40;
    container.innerHTML = pool.map((item, i) => {
      const url = typeof item === 'string' ? item : (item?.url || '');
      const poolPages = typeof item === 'object' && item?.pages ? item.pages : globalPages;
      // Переопределение аккаунта: 0 = использовать пул/глобальное значение
      const accPages = acc.url_pages?.[url] || '';
      const checked = selected.has(url) ? 'checked' : '';
      const badge = parseUrlFilter(url);
      const urlCount = acc.url_stats?.[url];
      const countInfo = urlCount != null ? `<span style="color:var(--green);font-size:10px;margin-left:4px">→${urlCount}</span>` : '';
      return `<div style="display:flex;align-items:center;gap:6px;margin-bottom:5px">
        <label style="display:flex;align-items:flex-start;gap:5px;cursor:pointer;font-size:11px;flex:1;min-width:0">
          <input type="checkbox" value="${esc(url)}" ${checked} style="margin-top:2px;flex-shrink:0">
          <span style="color:var(--text-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${badge}${countInfo}</span>
        </label>
        <input type="number" class="apply-input acc-url-pages-inp" data-url="${esc(url)}"
          min="1" max="200" placeholder="${poolPages}"
          value="${esc(String(accPages))}"
          title="Глубина для этого URL (пусто = ${poolPages} стр. из пула)"
          style="width:52px;font-size:10px;padding:2px 4px;text-align:center;flex-shrink:0">
      </div>`;
    }).join('');
  });
}

async function urlAccSave(accIdx, btn) {
  const container = document.getElementById(`acc-url-checks-${accIdx}`);
  if (!container) return;
  const urls = Array.from(container.querySelectorAll('input[type=checkbox]:checked'))
    .map(cb => cb.value).filter(Boolean);
  // Собираем переопределения страниц по URL
  const url_pages = {};
  container.querySelectorAll('.acc-url-pages-inp').forEach(inp => {
    const v = parseInt(inp.value);
    if (v > 0) url_pages[inp.dataset.url] = v;
  });
  const st = document.getElementById(`url-acc-st-${accIdx}`);
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳...'; st.style.color = 'var(--dim)'; }
  try {
    const res = await fetch(`/api/account/${accIdx}/set_urls`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({urls, url_pages})
    });
    const data = await res.json();
    if (data.ok) {
      if (st) { st.textContent = `✅ ${data.count} URL`; st.style.color = 'var(--green)'; }
    } else {
      if (st) { st.textContent = '❌ ' + (data.error||'Ошибка'); st.style.color = 'var(--red)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
    setTimeout(() => { if (st) st.textContent = ''; }, 4000);
  }
}

// ── Main accounts management ──────────────────────────────────
const ACC_COLORS = ['cyan','magenta','green','yellow','blue','red'];

async function accDeleteCard(idx, btn) {
  if (!await showConfirm(`Удалить аккаунт <b>#${idx}</b>? Действие необратимо.`)) return;
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`/api/account/${idx}/delete`, {method: 'DELETE'});
    const data = await res.json();
    if (data.ok) {
      const card = document.getElementById('card-' + idx);
      if (card) card.remove();
    } else {
      alert('Ошибка: ' + (data.error || ''));
      if (btn) btn.disabled = false;
    }
  } catch(e) {
    alert('Ошибка: ' + e);
    if (btn) btn.disabled = false;
  }
}

// ── Browser sessions management in Settings ──────────────────
function buildSessList(snap) {
  const el = document.getElementById('sess-list');
  if (!el) return;
  const sessions = (snap?.accounts || []).filter(a => a.temp);
  if (!sessions.length) {
    el.innerHTML = '<div style="font-size:11px;color:var(--dim);margin-bottom:8px">Нет сессий — добавьте первую ниже.</div>';
    return;
  }
  // Пересобираем только если изменилось количество
  if (el.dataset.count === String(sessions.length)) return;
  el.dataset.count = String(sessions.length);
  el.innerHTML = '';
  sessions.forEach(acc => {
    const div = document.createElement('div');
    div.id = `sess-row-${acc.idx}`;
    div.style.cssText = 'margin-bottom:8px;padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:6px';
    div.innerHTML =
      `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">` +
        `<div>` +
          `<span style="font-size:12px;font-weight:600;color:var(--yellow)">${esc(acc.name)}</span>` +
          `<span style="font-size:11px;color:var(--dim);margin-left:8px">${acc.bot_active ? t('sess_active') : t('sess_inactive')}</span>` +
        `</div>` +
        `<div style="display:flex;gap:6px">` +
          (!acc.bot_active ? `<button class="btn-sm" style="color:var(--green);border-color:var(--green)" onclick="sessActivate(${acc.idx},this)">▶ Запустить</button>` : '') +
          `<button class="btn-sm" onclick="sessEditToggle(${acc.idx})">✏️ Изменить</button>` +
          `<button class="btn-sm" style="color:var(--red);border-color:var(--red)" onclick="sessionRemove(${acc.idx})">🗑️</button>` +
        `</div>` +
      `</div>` +
      `<div style="font-size:11px;color:var(--dim)">` +
        `resume_hash: <b style="font-family:monospace;color:var(--text)">${esc((acc.resume_hash||'').slice(0,14))}...</b>` +
      `</div>` +
      `<div id="sess-edit-form-${acc.idx}" style="display:none;margin-top:10px">` +
        `<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">` +
          `<div><div style="font-size:11px;color:var(--dim);margin-bottom:3px">Имя</div>` +
            `<input id="sess-edit-name-${acc.idx}" class="apply-input" style="font-size:11px" value="${esc(acc.name)}"></div>` +
          `<div><div style="font-size:11px;color:var(--dim);margin-bottom:3px">Короткое</div>` +
            `<input id="sess-edit-short-${acc.idx}" class="apply-input" style="font-size:11px" value="${esc(acc.short||'')}"></div>` +
          `<div><div style="font-size:11px;color:var(--dim);margin-bottom:3px">Цвет</div>` +
            `<select id="sess-edit-color-${acc.idx}" class="apply-input" style="font-size:11px">` +
              ACC_COLORS.map(c => `<option value="${c}"${c===(acc.color||'yellow')?' selected':''}>${c}</option>`).join('') +
            `</select></div>` +
          `<div><div style="font-size:11px;color:var(--dim);margin-bottom:3px">resume_hash</div>` +
            `<input id="sess-edit-hash-${acc.idx}" class="apply-input" style="font-size:11px;font-family:monospace" value="${esc(acc.resume_hash||'')}"></div>` +
        `</div>` +
        `<div style="display:flex;gap:8px;align-items:center">` +
          `<button class="btn-sm" onclick="sessProfileSave(${acc.idx},this)">💾 Сохранить</button>` +
          `<span id="sess-edit-st-${acc.idx}" style="font-size:11px;color:var(--dim)"></span>` +
        `</div>` +
      `</div>`;
    el.appendChild(div);
  });
}

async function sessActivate(idx, btn) {
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`/api/session/${idx}/activate`, {method: 'POST'});
    const data = await res.json();
    if (data.ok) {
      const listEl = document.getElementById('sess-list');
      if (listEl) listEl.dataset.count = '';
    } else {
      alert('Ошибка: ' + (data.error || ''));
      if (btn) btn.disabled = false;
    }
  } catch(e) {
    alert('Ошибка: ' + e);
    if (btn) btn.disabled = false;
  }
}

async function touchToggle(idx, el) {
  if (!el) return;
  const wasOn = el.classList.contains('on');
  // оптимистично переключаем сразу
  el.classList.toggle('on', !wasOn);
  el.classList.toggle('off', wasOn);
  const lbl = document.getElementById('acc-touch-label-' + idx);
  if (lbl) lbl.textContent = !wasOn ? '🔁 вкл' : '⏸ выкл';
  try {
    const res = await fetch(`/api/account/${idx}/resume_touch_toggle`, {method: 'POST'});
    if (!res.ok) throw new Error(res.status);
    // финальное состояние придёт через WebSocket
  } catch(e) {
    // откат
    el.classList.toggle('on', wasOn);
    el.classList.toggle('off', !wasOn);
    if (lbl) lbl.textContent = wasOn ? '🔁 вкл' : '⏸ выкл';
  }
}

async function resumeTouchNow(idx, btn) {
  if (btn) { btn.disabled = true; btn.textContent = '⏳ поднимаю...'; btn.style.color = ''; }
  try {
    await fetch(`/api/account/${idx}/resume_touch`, {method: 'POST'});
    // держим disabled — updateCard разблокирует кнопку когда придёт реальный таймер
    if (btn) btn.setAttribute('data-touching', '1');
    // страховка: разблокировать через 15с если WebSocket не пришёл
    setTimeout(() => {
      if (btn && btn.getAttribute('data-touching')) {
        btn.removeAttribute('data-touching');
        btn.disabled = false;
        btn.textContent = '📤 Поднять';
        btn.style.color = '';
      }
    }, 15000);
  } catch(e) {
    if (btn) { btn.textContent = '❌'; btn.style.color = 'var(--red)'; btn.disabled = false; btn.removeAttribute('data-touching'); }
  }
}

function sessEditToggle(idx) {
  const form = document.getElementById(`sess-edit-form-${idx}`);
  if (form) form.style.display = form.style.display === 'none' ? 'block' : 'none';
}

async function sessProfileSave(idx, btn) {
  const st = document.getElementById(`sess-edit-st-${idx}`);
  const body = {
    name:        document.getElementById(`sess-edit-name-${idx}`)?.value.trim(),
    short:       document.getElementById(`sess-edit-short-${idx}`)?.value.trim(),
    color:       document.getElementById(`sess-edit-color-${idx}`)?.value,
    resume_hash: document.getElementById(`sess-edit-hash-${idx}`)?.value.trim(),
  };
  if (btn) btn.disabled = true;
  if (st) { st.textContent = '⏳...'; st.style.color = 'var(--dim)'; }
  try {
    const res = await fetch(`/api/session/${idx}/profile`, {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
    });
    const data = await res.json();
    if (data.ok) {
      if (st) { st.textContent = '✅ Сохранено'; st.style.color = 'var(--green)'; }
      const listEl = document.getElementById('sess-list');
      if (listEl) listEl.dataset.count = '';
    } else {
      if (st) { st.textContent = '❌ ' + (data.error||'Ошибка'); st.style.color = 'var(--red)'; }
    }
  } catch(e) {
    if (st) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  } finally {
    if (btn) btn.disabled = false;
    setTimeout(() => { if (st) st.textContent = ''; }, 4000);
  }
}

// Создаём/обновляем список cookies аккаунтов из snapshot
function buildAccCookiesList(snap) {
  const el = document.getElementById('acc-cookies-list');
  if (!el) return;
  const accs = (snap?.accounts || []);
  if (!accs.length) { el.innerHTML = '<div class="c-dim" style="font-size:12px">Нет аккаунтов</div>'; return; }
  // Пересобираем только если изменилось количество аккаунтов
  if (el.dataset.count === String(accs.length)) return;
  el.dataset.count = String(accs.length);
  el.innerHTML = '';
  accs.forEach(acc => {
    const colorStyle = `color:${colorVar(acc.color || 'text')}`;
    const div = document.createElement('div');
    div.style.cssText = 'margin-bottom:14px;padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:6px';
    div.innerHTML =
      `<div style="font-size:12px;font-weight:600;margin-bottom:6px;${colorStyle}">${esc(acc.name)}</div>` +
      `<textarea id="ck-ta-${acc.idx}" class="apply-input" rows="2" style="font-size:11px;margin-bottom:6px" ` +
        `placeholder="curl 'https://hh.ru/...' -H 'cookie: hhtoken=...' ...&#10;— или: hhtoken=xxx; _xsrf=yyy; hhul=zzz; crypted_id=aaa"></textarea>` +
      `<div style="display:flex;gap:8px;align-items:center">` +
        `<button class="btn-sm" onclick="updateAccCookies(${acc.idx})">${t('btn_update_cookies')}</button>` +
        `<span id="ck-st-${acc.idx}" style="font-size:11px;color:var(--dim)"></span>` +
      `</div>`;
    el.appendChild(div);
  });
}

async function updateAccCookies(idx) {
  const ta = document.getElementById('ck-ta-' + idx);
  const st = document.getElementById('ck-st-' + idx);
  const val = ta?.value.trim();
  if (!val) { st.textContent = '❌ Пусто'; st.style.color = 'var(--red)'; return; }
  st.textContent = '⏳ Обновляю...'; st.style.color = 'var(--dim)';
  try {
    const res = await fetch(`/api/account/${idx}/update_cookies`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cookies: val})
    });
    const data = await res.json();
    if (data.ok) {
      ta.value = '';
      st.textContent = `✅ Обновлено (${(data.keys||[]).length} ключей)`;
      st.style.color = 'var(--green)';
    } else {
      st.textContent = '❌ ' + (data.error || 'Ошибка');
      st.style.color = 'var(--red)';
    }
  } catch(e) {
    st.textContent = '❌ ' + e;
    st.style.color = 'var(--red)';
  }
}

function applySettings() {
  SETTINGS_DEF.forEach(s => {
    const el = document.getElementById('sr-' + s.key);
    if (el) sendCmd({ type: 'set_config', key: s.key, value: Number(el.value) });
  });
  const st = document.getElementById('settings-status');
  st.textContent = t('settings_applied');
  setTimeout(() => { st.textContent = ''; }, 3000);
}

// ── WebSocket ──────────────────────────────────────────────────
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  State.ws = ws;

  ws.onopen = () => {
    document.getElementById('conn-dot').classList.add('connected');
    State.reconnectDelay = 1000;
  };

  ws.onmessage = (ev) => {
    try {
      const snap = JSON.parse(ev.data);
      if (snap.type === 'state_update') {
        State.lastSnapshot = snap;
        try {
          renderAll(snap);
          const dbg = document.getElementById('dbg-err');
          if (dbg) dbg.style.display = 'none';
        } catch (renderErr) {
          const dbg = document.getElementById('dbg-err');
          if (dbg) { dbg.style.display = ''; dbg.textContent = 'JS ERROR: ' + renderErr; }
          console.error('renderAll error:', renderErr);
        }
      }
    } catch (e) { console.error('WS parse error:', e); }
  };

  ws.onclose = () => {
    document.getElementById('conn-dot').classList.remove('connected');
    State.reconnectTimer = setTimeout(() => {
      State.reconnectDelay = Math.min(State.reconnectDelay * 2, 30000);
      connect();
    }, State.reconnectDelay);
  };

  ws.onerror = () => { ws.close(); };
}

function sendCmd(obj) {
  if (State.ws && State.ws.readyState === 1) {
    State.ws.send(JSON.stringify(obj));
  }
}

// ── Rendering ──────────────────────────────────────────────────
function renderAll(snap) {
  renderHeader(snap);
  updateHeaderResumeStats(snap);
  syncLetterSelects(snap);
  syncAccUrlChecks(snap);
  syncLlmSettings(snap);
  updatePageTitle(snap);
  checkNotifications(snap);
  if (State.currentTab === 'main') renderMain(snap);
  else if (State.currentTab === 'log') renderLog(snap);
  else if (State.currentTab === 'hh') renderHH(snap);
  else if (State.currentTab === 'llm') renderLlmLog(snap);
  else if (State.currentTab === 'views') loadViews();
  else if (State.currentTab === 'apply') {
    applyBuildAccountSelect(snap);
  }
  // Отклики, тесты и просмотры рендерятся при переключении вкладки
}

function updatePageTitle(snap) {
  const hasLimit = (snap.accounts || []).some(a => a.status === 'limit');
  const sent = snap.global_stats?.total_sent || 0;
  if (hasLimit) {
    document.title = t('title_limit');
  } else if (snap.paused) {
    document.title = t('title_paused');
  } else if (sent > 0) {
    document.title = `✅ ${sent} откл. | HH Bot`;
  } else {
    document.title = 'HH Bot Dashboard';
  }
}

function checkNotifications(snap) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  (snap.accounts || []).forEach(acc => {
    const prev = State.prevInterviews[acc.idx] ?? acc.hh_interviews;
    if (acc.hh_interviews > prev) {
      sendBotNotification(
        `${t('notif_new_inv')}${acc.short}`,
        `${t('notif_inv_count_pre')} ${acc.hh_interviews} ${t('notif_inv_count_mid')}${acc.hh_interviews - prev})`
      );
    }
    State.prevInterviews[acc.idx] = acc.hh_interviews;
    const wasLimit = State.prevLimitState[acc.idx];
    if (acc.status === 'limit' && !wasLimit) {
      sendBotNotification(`${t('notif_limit')}${acc.short}`, t('notif_limit_body'));
    }
    State.prevLimitState[acc.idx] = acc.status === 'limit';
    // Определение истечения cookies
    const wasExpired = State.prevCookiesExpired[acc.idx];
    if (acc.cookies_expired && !wasExpired) {
      sendBotNotification(`${t('notif_cookies')}${acc.short}`, t('notif_cookies_body'));
    }
    State.prevCookiesExpired[acc.idx] = acc.cookies_expired;
  });
}

function sendBotNotification(title, body) {
  try { new Notification(title, { body, icon: '/favicon.ico' }); } catch(e) {}
}

function fmtUptime(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}ч ${String(m).padStart(2,'0')}м`;
  return `${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
}

function renderHeader(snap) {
  document.getElementById('uptime').textContent = '⏱ ' + fmtUptime(snap.uptime_seconds);
  document.getElementById('global-found').textContent = snap.global_stats.total_found;
  document.getElementById('global-sent').textContent = snap.global_stats.total_sent;
  document.getElementById('storage-total').textContent = snap.global_stats.storage_total;
  document.getElementById('storage-tests').textContent = snap.global_stats.storage_tests;

  const btn = document.getElementById('pause-btn');
  if (snap.paused) {
    btn.textContent = t('btn_resume');
    btn.classList.add('paused');
  } else {
    const pausedAccs = (snap.accounts || []).filter(a => a.paused).length;
    btn.textContent = pausedAccs ? `${t('btn_pause')} (${pausedAccs})` : t('btn_pause');
    btn.classList.remove('paused');
  }
}

// ── Main tab ──
function renderMain(snap) {
  renderAccounts(snap);
  renderGlobalStats(snap);
  renderRecentResponses(snap);
}

const STATUS_MAP = {
  idle:       ['⏸', 'status_idle',       'status-idle'],
  collecting: ['📥', 'status_collecting', 'status-collecting'],
  applying:   ['📤', 'status_applying',   'status-applying'],
  limit:      ['🚫', 'status_limit',      'status-limit'],
  waiting:    ['⏳', 'status_waiting',    'status-waiting'],
  checking:   ['🔍', 'status_checking',   'status-checking'],
  '—':        ['⭕', 'status_inactive',   'status-idle'],
};

function renderAccounts(snap) {
  const grid = document.getElementById('accounts-grid');
  // Пустое состояние — нет аккаунтов
  let emptyEl = document.getElementById('accounts-empty');
  if (!snap.accounts || snap.accounts.length === 0) {
    if (!emptyEl) {
      emptyEl = document.createElement('div');
      emptyEl.id = 'accounts-empty';
      emptyEl.style.cssText = 'grid-column:1/-1;text-align:center;padding:48px 16px;color:var(--dim);font-size:14px';
      emptyEl.innerHTML = `<div style="font-size:32px;margin-bottom:12px">📭</div>${t('no_accounts')}`;
      grid.appendChild(emptyEl);
    }
    return;
  }
  if (emptyEl) emptyEl.remove();
  // Убираем карточки которых больше нет
  const alive = new Set(snap.accounts.map(a => 'card-' + a.idx));
  grid.querySelectorAll('.acc-card').forEach(el => {
    if (el.id && !alive.has(el.id)) el.remove();
  });
  snap.accounts.forEach(acc => {
    let card = document.getElementById('card-' + acc.idx);
    if (!card) {
      card = document.createElement('div');
      card.id = 'card-' + acc.idx;
      card.className = 'acc-card color-' + (acc.color || 'yellow');
      card.innerHTML = buildCardHTML(acc);
      grid.appendChild(card);
    } else {
      card.className = 'acc-card color-' + (acc.color || 'yellow');
      updateCard(card, acc);
    }
  });
}

function buildCardHTML(acc) {
  return `
    <div class="acc-header">
      <div class="acc-name" id="acc-name-${acc.idx}">${acc.name}</div>
      <button class="compact-btn" title="Свернуть/развернуть карточку" onclick="toggleCompact(${acc.idx})">⬜</button>
      <button class="compact-btn" title="Удалить аккаунт" style="color:var(--red);margin-left:2px" onclick="accDeleteCard(${acc.idx}, this)">🗑</button>
      <div class="acc-status-badge status-idle" id="acc-badge-${acc.idx}">⏸ ${t('status_idle')}</div>
    </div>
    <div class="acc-progress"><div class="acc-progress-fill" id="acc-prog-${acc.idx}"></div></div>
    <div class="acc-stats">
      <div class="stat-box" title="Сессия / Всего за всё время">
        <div class="stat-val c-green" id="acc-sent-${acc.idx}">0</div>
        <div class="stat-lbl">${t('stat_replies')} <span style="color:var(--dim);font-size:10px">/ <span id="acc-total-${acc.idx}">0</span></span></div>
      </div>
      <div class="stat-box">
        <div class="stat-val c-magenta" id="acc-tests-${acc.idx}">0</div>
        <div class="stat-lbl">${t('stat_tests')}</div>
      </div>
      <div class="stat-box" id="acc-qsent-box-${acc.idx}" style="display:none">
        <div class="stat-val c-cyan" id="acc-qsent-${acc.idx}">0</div>
        <div class="stat-lbl">${t('stat_surveys')}</div>
      </div>
      <div class="stat-box">
        <div class="stat-val c-blue" id="acc-already-${acc.idx}">0</div>
        <div class="stat-lbl">${t('stat_already')}</div>
      </div>
      <div class="stat-box">
        <div class="stat-val c-red" id="acc-err-${acc.idx}">0</div>
        <div class="stat-lbl">${t('stat_errors')}</div>
      </div>
      <div class="stat-box" id="acc-sal-box-${acc.idx}" style="display:none">
        <div class="stat-val c-yellow" id="acc-sal-${acc.idx}">0</div>
        <div class="stat-lbl">${t('stat_salary')}</div>
      </div>
      <div class="stat-box" id="acc-intrv-box-${acc.idx}" style="display:none">
        <div class="stat-val" style="color:#f0c060" id="acc-intrv-${acc.idx}">0</div>
        <div id="acc-intrv-total-${acc.idx}" style="font-size:10px;color:var(--dim);line-height:1.2"></div>
        <div class="stat-lbl">${t('stat_interviews')}</div>
      </div>
    </div>
    <div class="acc-vacancy" id="acc-vacancy-${acc.idx}">
      <div class="acc-vacancy-title c-dim">${t('card_waiting')}</div>
    </div>
    <div class="acc-meta" id="acc-meta-${acc.idx}"></div>
    <div class="acc-hh-stats" id="acc-hh-${acc.idx}">${t('card_hh_loading')}</div>
    <div class="acc-resume-stats" id="acc-rs-${acc.idx}" style="display:none">
      <span class="acc-resume-stat">👁️ <span id="acc-rs-views-${acc.idx}">0</span> ${t('rs_views')}</span>
      <span class="acc-resume-stat c-cyan">+<span id="acc-rs-vnew-${acc.idx}">0</span> новых</span>
      <span class="acc-resume-stat">🔎 <span id="acc-rs-shows-${acc.idx}">0</span> ${t('rs_shows')}</span>
      <span class="acc-resume-stat c-green">📬 <span id="acc-rs-inv-${acc.idx}">0</span> ${t('rs_inv')}</span>
      <span class="acc-touch-timer c-yellow" id="acc-touch-timer-${acc.idx}" style="display:none"></span>
    </div>
    <div class="acc-history" id="acc-hist-${acc.idx}"></div>
    <div class="acc-event-log" id="acc-elog-${acc.idx}"></div>
    <div id="acc-errbadge-${acc.idx}" style="display:none;font-size:11px;padding:2px 0;margin-bottom:2px"></div>
    <div id="acc-cookiesbadge-${acc.idx}" class="cookies-expired-badge" style="display:none">${t('cookies_expired_badge')}</div>
    <label class="acc-skip-tests${acc.apply_tests ? ' active' : ''}" id="acc-apply-label-${acc.idx}">
      <input type="checkbox" id="acc-apply-cb-${acc.idx}" ${acc.apply_tests ? 'checked' : ''}
        onchange="applyTestsToggle(${acc.idx}, this)">
      ${t('card_apply_tests')}
    </label>
    <div class="acc-actions">
      <button class="btn-sm" id="acc-pause-btn-${acc.idx}"
        onclick="sendCmd({type:'account_pause', idx:${acc.idx}})">${t('btn_acc_pause')}</button>
      <span class="touch-toggle ${acc.resume_touch_enabled !== false ? 'on' : 'off'}" id="acc-touch-toggle-${acc.idx}" onclick="touchToggle(${acc.idx},this)" title="Авто-подъём резюме вкл/выкл">
        <span class="tgl-dot"></span>
        <span>Авто-подъём резюме</span>
        <span id="acc-touch-label-${acc.idx}">${acc.resume_touch_enabled !== false ? '🔁 вкл' : '⏸ выкл'}</span>
      </span>
      <button class="btn-sm" id="acc-touch-btn-${acc.idx}"
        onclick="resumeTouchNow(${acc.idx},this)" title="Поднять резюме прямо сейчас">📤 Сейчас</button>
      <button class="btn-sm"
        onclick="declineDiscards(${acc.idx},this)">${t('btn_clear_discards')}</button>
      <button class="btn-sm llm-toggle-btn llm-on" id="acc-llm-btn-${acc.idx}"
        onclick="llmToggleAccount(${acc.idx},this)" title="Вкл/выкл LLM авто-ответы для этого аккаунта">🤖 ВКЛ</button>
      ${acc.temp && !acc.bot_active ? `<button class="btn-sm" style="color:var(--green);border-color:var(--green)" onclick="sessionActivate(${acc.idx})">${t('btn_launch')}</button>` : ''}
      ${acc.temp ? `<button class="btn-sm" style="color:var(--red);border-color:var(--red)" onclick="sessionRemove(${acc.idx})">${t('btn_delete')}</button>` : ''}
    </div>
    <details class="acc-letter-wrap" id="acc-letter-wrap-${acc.idx}">
      <summary>${t('letter_section')}</summary>
      <div class="acc-letter-body">
        <select id="acc-letter-tpl-${acc.idx}" class="apply-input" style="font-size:11px;padding:3px 6px;margin-bottom:6px"
          onchange="letterPickTpl(${acc.idx})">
          <option value="">— пусто —</option>
          <option value="__custom__">✏️ Своё</option>
        </select>
        <textarea id="acc-letter-ta-${acc.idx}" class="apply-input" rows="3"
          style="font-size:11px" placeholder="Сопроводительное письмо...">${esc(acc.letter||'')}</textarea>
        <div style="display:flex;gap:6px;margin-top:6px;align-items:center">
          <button class="btn-sm" onclick="letterSave(${acc.idx},this)">${t('btn_save')}</button>
          <span id="acc-letter-st-${acc.idx}" style="font-size:11px;color:var(--dim)"></span>
        </div>
      </div>
    </details>
    <details class="acc-letter-wrap" id="acc-url-wrap-${acc.idx}">
      <summary>${t('url_section')}</summary>
      <div class="acc-letter-body">
        <div id="acc-url-checks-${acc.idx}" style="margin-bottom:8px"></div>
        <div style="display:flex;gap:6px;align-items:center">
          <button class="btn-sm" onclick="urlAccSave(${acc.idx},this)">${t('btn_apply_url')}</button>
          <span id="url-acc-st-${acc.idx}" style="font-size:11px;color:var(--dim)"></span>
        </div>
      </div>
    </details>
  `;
}

function updateCard(card, acc) {
  // Статусный бейдж: глобальная пауза перекрывает статус
  const badge = document.getElementById('acc-badge-' + acc.idx);
  if (badge) {
    const globalPaused = State.lastSnapshot?.paused;
    const accPaused = acc.paused;
    if (globalPaused) {
      badge.className = 'acc-status-badge status-idle';
      badge.textContent = t('status_all_paused');
      badge.title = '';
    } else if (accPaused) {
      badge.className = 'acc-status-badge status-idle';
      badge.textContent = t('status_acc_paused');
      badge.title = '';
    } else {
      const [icon, labelKey, cls] = STATUS_MAP[acc.status] || ['❓', null, 'status-idle'];
      badge.className = 'acc-status-badge ' + cls;
      badge.textContent = icon + ' ' + (labelKey ? t(labelKey) : acc.status.toUpperCase());
      if (acc.status_detail) badge.title = acc.status_detail;
    }
  }

  // Статистика резюме block
  const rsBlock = document.getElementById('acc-rs-' + acc.idx);
  if (rsBlock && acc.resume_views_7d > 0) {
    rsBlock.style.display = '';
    setText('acc-rs-views-' + acc.idx, acc.resume_views_7d);
    setText('acc-rs-vnew-' + acc.idx, acc.resume_views_new);
    setText('acc-rs-shows-' + acc.idx, acc.resume_shows_7d);
    setText('acc-rs-inv-' + acc.idx, acc.resume_invitations_7d);
    // Таймер поднятия
    const timerEl = document.getElementById('acc-touch-timer-' + acc.idx);
    if (timerEl) {
      const secs = acc.resume_next_touch_seconds || 0;
      if (secs > 0) {
        const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60);
        timerEl.style.display = '';
        timerEl.textContent = `⏱ ${t('rs_raise_in')} ${h > 0 ? h + 'ч ' : ''}${m}м`;
      } else {
        timerEl.style.display = '';
        timerEl.textContent = `✅ ${acc.resume_free_touches || 0} ${t('rs_raises_avail')}`;
        timerEl.className = 'acc-touch-timer c-green';
      }
    }
  }

  // Переключатель и кнопка автоподнятия
  const touchToggleEl = document.getElementById('acc-touch-toggle-' + acc.idx);
  const touchLabelEl  = document.getElementById('acc-touch-label-' + acc.idx);
  const touchBtn      = document.getElementById('acc-touch-btn-' + acc.idx);
  const autoOn = acc.resume_touch_enabled !== false;
  const m = acc.next_resume_touch ? acc.next_resume_touch.match(/\(([^)]+)\)/) : null;
  const countdown = m && m[1]; // "2ч30м"
  if (touchToggleEl) {
    touchToggleEl.className = 'touch-toggle ' + (autoOn ? 'on' : 'off');
    if (touchLabelEl) {
      if (autoOn) {
        touchLabelEl.textContent = countdown ? `🔁 вкл · через ${countdown}` : '🔁 вкл';
      } else {
        touchLabelEl.textContent = countdown ? `⏸ выкл · было через ${countdown}` : '⏸ выкл';
      }
    }
  }
  if (touchBtn) {
    const touching = touchBtn.getAttribute('data-touching');
    if (touching) {
      if (countdown) {
        touchBtn.removeAttribute('data-touching');
        touchBtn.disabled = false;
        touchBtn.textContent = '📤 Сейчас';
        touchBtn.style.color = '';
      }
    } else if (!touchBtn.disabled) {
      touchBtn.textContent = '📤 Сейчас';
      touchBtn.style.color = '';
    }
  }

  // Статистика
  setText('acc-sent-' + acc.idx, acc.sent);
  setText('acc-total-' + acc.idx, acc.total_applied ?? '');
  setText('acc-tests-' + acc.idx, acc.tests);
  setText('acc-already-' + acc.idx, acc.already_applied);
  setText('acc-err-' + acc.idx, acc.errors);

  // Анкеты sent (show when > 0)
  const qBox = document.getElementById('acc-qsent-box-' + acc.idx);
  if (qBox) {
    const qSent = acc.questionnaire_sent || 0;
    qBox.style.display = qSent > 0 ? '' : 'none';
    setText('acc-qsent-' + acc.idx, qSent);
  }

  // Статистика фильтра зарплаты: показываем только при активном фильтре
  const salBox = document.getElementById('acc-sal-box-' + acc.idx);
  if (salBox) {
    const minSal = acc.min_salary || (State.lastSnapshot && State.lastSnapshot.config && State.lastSnapshot.config.min_salary) || 0;
    salBox.style.display = minSal > 0 ? '' : 'none';
    setText('acc-sal-' + acc.idx, acc.salary_skipped || 0);
  }

  // Блок статистики переговоров HH: свежие за 60 дней крупно, всего мелко
  const intrvBox = document.getElementById('acc-intrv-box-' + acc.idx);
  if (intrvBox) {
    const recent = acc.hh_interviews_recent ?? acc.hh_interviews ?? 0;
    const total  = acc.hh_interviews || 0;
    intrvBox.style.display = total > 0 ? '' : 'none';
    setText('acc-intrv-' + acc.idx, recent);
    const totalEl = document.getElementById('acc-intrv-total-' + acc.idx);
    if (totalEl) totalEl.textContent = total > recent ? `всего ${total}` : '';
  }


  // Прогресс-бар
  const prog = document.getElementById('acc-prog-' + acc.idx);
  if (prog) {
    let pct = 0;
    if (acc.status === 'applying' && acc.total_vacancies > 0) {
      pct = Math.round(acc.current_vacancy_idx / acc.total_vacancies * 100);
      prog.className = 'acc-progress-fill applying';
    } else if (acc.status === 'collecting') {
      pct = 30; // Неопределённая пульсация
      prog.className = 'acc-progress-fill';
    } else if (acc.status === 'limit') {
      pct = 100;
      prog.className = 'acc-progress-fill limit';
    } else {
      pct = 0;
      prog.className = 'acc-progress-fill';
    }
    prog.style.width = pct + '%';
  }

  // Компактный режим карточки
  if (State.compactCards.has(acc.idx)) {
    card.classList.add('compact');
  } else {
    card.classList.remove('compact');
  }

  // Бейдж подряд идущих ошибок
  const errBadge = document.getElementById('acc-errbadge-' + acc.idx);
  if (errBadge) {
    const n = acc.consecutive_errors || 0;
    const threshold = State.lastSnapshot?.config?.auto_pause_errors || 5;
    if (n > 0) {
      errBadge.style.display = '';
      errBadge.textContent = `⚡ ${n} ${t('errs_in_row')}`;
      errBadge.style.color = n >= threshold ? 'var(--red)' : 'var(--yellow)';
    } else {
      errBadge.style.display = 'none';
    }
  }

  // Бейдж истёкших cookies
  const cookiesBadge = document.getElementById('acc-cookiesbadge-' + acc.idx);
  if (cookiesBadge) {
    cookiesBadge.style.display = acc.cookies_expired ? '' : 'none';
  }

  // Текущая вакансия
  const vac = document.getElementById('acc-vacancy-' + acc.idx);
  if (vac) {
    if (acc.current_vacancy_title) {
      vac.innerHTML = `
        <div class="acc-vacancy-title">${esc(acc.current_vacancy_title)}</div>
        <div class="acc-vacancy-company c-dim">@ ${esc(acc.current_vacancy_company)}</div>
      `;
    } else if (acc.status === 'applying') {
      vac.innerHTML = `<div class="acc-vacancy-title c-dim">${t('card_sending')}</div>`;
    } else {
      vac.innerHTML = `<div class="acc-vacancy-title c-dim">${esc(acc.status_detail) || t('card_waiting')}</div>`;
    }
  }

  // Метаданные
  const meta = document.getElementById('acc-meta-' + acc.idx);
  if (meta) {
    const parts = [];
    if (acc.found_vacancies > 0) parts.push(`🔍 ${acc.found_vacancies} найдено`);
    if (acc.next_resume_touch) parts.push(`📤 резюме: ${acc.next_resume_touch}`);
    meta.textContent = parts.join('  ');
  }

  // Статистика HH
  const hh = document.getElementById('acc-hh-' + acc.idx);
  if (hh) {
    if (acc.hh_stats_loading && !acc.hh_stats_updated) {
      hh.textContent = t('card_hh_loading');
    } else if (acc.hh_stats_updated) {
      const recent = acc.hh_interviews_recent ?? acc.hh_interviews ?? 0;
      const total  = acc.hh_interviews || 0;
      const intrvStr = total > recent
        ? `<span style="color:#f0c060">🎯 ${recent}</span><span class="c-dim"> (${total} всего)</span>`
        : `<span style="color:#f0c060">🎯 ${recent}</span>`;
      hh.innerHTML =
        intrvStr + ` ${t('hh_interviews')} &nbsp;` +
        `<span class="c-yellow">👁 ${acc.hh_viewed}</span> ${t('hh_viewed')} &nbsp;` +
        `<span class="c-red">❌ ${acc.hh_discards}</span> ${t('hh_discards')} &nbsp;` +
        `<span class="c-dim">(${acc.hh_stats_updated})</span>`;
    } else {
      hh.textContent = acc.hh_stats_loading ? '⏳ HH...' : '—';
    }
  }

  // История
  const hist = document.getElementById('acc-hist-' + acc.idx);
  if (hist && acc.action_history.length > 0) {
    hist.textContent = acc.action_history.slice(-5).join('  |  ');
  }

  // Журнал событий аккаунта
  const elog = document.getElementById('acc-elog-' + acc.idx);
  if (elog && acc.acc_event_log) {
    if (acc.acc_event_log.length === 0) {
      elog.innerHTML = '';
    } else {
      elog.innerHTML = acc.acc_event_log.map(e => {
        const co = e.company ? ` <span style="color:var(--dim)">@ ${esc(e.company)}</span>` : '';
        const extra = e.extra ? `<div class="acc-elog-extra">${esc(e.extra)}</div>` : '';
        return `<div class="acc-elog-entry">
          <span class="acc-elog-time">${e.time}</span>
          <span class="acc-elog-icon">${e.icon}</span>
          <div class="acc-elog-body">
            <div class="acc-elog-title">${esc(e.title)}${co}</div>
            ${extra}
          </div>
        </div>`;
      }).join('');
    }
  }

  // Чекбокс откликов на тесты
  const skipCb = document.getElementById('acc-apply-cb-' + acc.idx);
  const skipLabel = document.getElementById('acc-apply-label-' + acc.idx);
  if (skipCb && skipCb.checked !== !!acc.apply_tests) skipCb.checked = !!acc.apply_tests;
  if (skipLabel) {
    if (acc.apply_tests) skipLabel.classList.add('active');
    else skipLabel.classList.remove('active');
  }

  // Кнопка паузы: учитываем глобальную паузу
  const pauseBtn = document.getElementById('acc-pause-btn-' + acc.idx);
  if (pauseBtn) {
    const globalPaused = State.lastSnapshot?.paused;
    if (globalPaused) {
      pauseBtn.textContent = t('btn_acc_global_pause');
      pauseBtn.classList.add('paused');
      pauseBtn.disabled = true;
      pauseBtn.title = 'Снимите глобальную паузу в правом верхнем углу';
    } else {
      pauseBtn.disabled = false;
      pauseBtn.title = '';
      if (acc.paused) {
        pauseBtn.textContent = t('btn_acc_resume');
        pauseBtn.classList.add('paused');
      } else {
        pauseBtn.textContent = t('btn_acc_pause');
        pauseBtn.classList.remove('paused');
      }
    }
  }

  // Кнопка-переключатель LLM
  const llmBtn = document.getElementById('acc-llm-btn-' + acc.idx);
  if (llmBtn) {
    const enabled = acc.llm_enabled !== false; // По умолчанию true
    llmBtn.textContent = enabled ? '🤖 ВКЛ' : '🤖 ВЫКЛ';
    llmBtn.classList.toggle('llm-on', enabled);
    llmBtn.classList.toggle('llm-off', !enabled);
  }
}

function renderGlobalStats(snap) {
  const g = snap.global_stats;
  const el = document.getElementById('global-stats-body');
  if (!el) return;
  const rows = [
    [t('gs_found'),    `<span class="c-cyan">${g.total_found}</span>`],
    [t('gs_applied'),  `<span class="c-green">${g.total_sent}</span>`],
    [t('gs_tests'),    `<span class="c-magenta">${g.total_tests}</span>`],
    [t('gs_errors'),   `<span class="c-red">${g.total_errors}</span>`],
    [t('gs_in_db'),    `<span class="c-blue">${g.storage_total}</span>`],
    [t('gs_in_db_tests'), `<span class="c-magenta">${g.storage_tests}</span>`],
  ];
  el.innerHTML = rows.map(([l, v]) =>
    `<div class="global-row"><span class="lbl">${l}</span>${v}</div>`
  ).join('');
}

function renderRecentResponses(snap) {
  const list = document.getElementById('recent-list');
  if (!list) return;
  if (!snap.recent_responses.length) {
    list.innerHTML = `<div class="c-dim" style="padding:8px;font-size:11px">${t('recent_empty')}</div>`;
    return;
  }
  list.innerHTML = snap.recent_responses.slice(0, 15).map(r => {
    const title = r.title ? r.title.substring(0, 35) + (r.title.length > 35 ? '…' : '') : `ID:${r.id}`;
    return `
      <div class="resp-item">
        <span class="resp-time">${r.time}</span>
        <span>${r.icon}</span>
        <div>
          <div class="resp-title">${esc(title)}</div>
          ${r.company ? `<div class="resp-company">@ ${esc(r.company)}</div>` : ''}
        </div>
      </div>
    `;
  }).join('');
}

// ── Log tab ──
function logSetLevel(btn, level) {
  State.logLevel = level;
  document.querySelectorAll('.log-level-btn').forEach(b => {
    const isActive = b.dataset.level === level;
    if (isActive) b.classList.add('active');
    else b.classList.remove('active');
  });
  if (State.lastSnapshot) renderLog(State.lastSnapshot);
}

function logSyncAccFilter(snap) {
  const sel = document.getElementById('log-acc-filter');
  if (!sel) return;
  const current = sel.value;
  const names = [...new Set((snap.accounts||[]).map(a => a.short).filter(Boolean))];
  sel.innerHTML = `<option value="">${t('log_all_accs')}</option>` +
    names.map(n => `<option value="${esc(n)}"${current===n?' selected':''}>${esc(n)}</option>`).join('');
}

function renderLog(snap) {
  if (!snap) return;
  logSyncAccFilter(snap);
  const list = document.getElementById('log-list');
  if (!list || !snap.log) return;

  const search = (document.getElementById('log-search')?.value || '').toLowerCase();
  const accF   = document.getElementById('log-acc-filter')?.value || '';
  const level  = State.logLevel;

  let entries = snap.log;
  if (level)  entries = entries.filter(e => e.level === level);
  if (accF)   entries = entries.filter(e => e.acc === accF);
  if (search) entries = entries.filter(e =>
    (e.message||'').toLowerCase().includes(search) || (e.acc||'').toLowerCase().includes(search)
  );
  entries = entries.slice(0, State.MAX_LOG_NODES);

  const cnt = document.getElementById('log-count');
  if (cnt) cnt.textContent = `${entries.length} записей`;

  const frag = document.createDocumentFragment();
  entries.forEach(entry => {
    const el = document.createElement('div');
    el.className = 'log-item';
    el.innerHTML = `
      <span class="log-time">${entry.time}</span>
      <span class="log-acc" style="color:${colorVar(entry.color)}">${esc(entry.acc)}</span>
      <span class="log-msg log-${entry.level}">${esc(entry.message)}</span>
    `;
    frag.appendChild(el);
  });
  list.innerHTML = '';
  list.appendChild(frag);
}

// ── HH Status tab ──
function renderHH(snap) {
  const content = document.getElementById('hh-content');
  if (!content || !snap.accounts) return;

  content.innerHTML = snap.accounts.filter(acc => !acc.temp || acc.bot_active).map(acc => {
    let body = '';
    if (acc.hh_stats_loading && !acc.hh_stats_updated) {
      body = `<div class="c-dim">${t('hh_loading')}</div>`;
    } else if (!acc.hh_stats_updated) {
      body = `<div class="c-dim">${t('hh_no_data')}</div>`;
    } else {
      // Счётчики
      body += `<div class="hh-counters">
        <div class="hh-counter"><div class="hh-counter-val c-green">${acc.hh_interviews}</div><div class="hh-counter-lbl">${t('hh_interviews')}</div></div>
        <div class="hh-counter"><div class="hh-counter-val c-yellow">${acc.hh_viewed}</div><div class="hh-counter-lbl">${t('hh_viewed')}</div></div>
        <div class="hh-counter"><div class="hh-counter-val c-red">${acc.hh_discards}</div><div class="hh-counter-lbl">${t('hh_discards')}</div></div>
        <div class="hh-counter"><div class="hh-counter-val c-dim">${acc.hh_not_viewed}</div><div class="hh-counter-lbl">${t('hh_not_viewed')}</div></div>
      </div>`;
      body += `<div class="c-dim" style="font-size:11px;margin-bottom:10px">${t('hh_updated')} ${acc.hh_stats_updated}</div>`;

      // Список переговоров
      if (acc.hh_interviews_list && acc.hh_interviews_list.length) {
        body += `<div style="font-weight:700;margin-bottom:6px;color:var(--green)">${t('hh_inv_list')}</div>`;
        body += acc.hh_interviews_list.map(item => {
          const url = item.neg_id ? `https://hh.ru/applicant/negotiations/${item.neg_id}` : '';
          const textEl = url
            ? `<a class="hh-interview-text" href="${url}" target="_blank" rel="noopener">${esc(item.text || '')}</a>`
            : `<span class="hh-interview-text">${esc(item.text || '')}</span>`;
          return `<div class="hh-interview-item">` +
            (item.date ? `<span class="hh-interview-date">${esc(item.date)}</span>` : '') +
            textEl +
            `</div>`;
        }).join('');
      }

      // Возможные офферы
      if (acc.hh_possible_offers && acc.hh_possible_offers.length) {
        body += `<div style="font-weight:700;margin:12px 0 6px;color:var(--yellow)">${t('hh_offers')}</div>`;
        body += acc.hh_possible_offers.map(o =>
          `<div class="hh-offer-item">
            <div class="hh-offer-name">${esc(o.name)}</div>
            <div class="hh-offer-vacs">${o.vacancyNames.slice(0,3).map(n=>esc(n)).join(', ')}</div>
          </div>`
        ).join('');
      }
    }

    const colorStyle = `color:var(--${acc.color === 'magenta' ? 'magenta' : acc.color})`;
    return `
      <div class="hh-account-block">
        <div class="hh-account-title" style="${colorStyle}">${esc(acc.name)}</div>
        ${body}
      </div>
    `;
  }).join('');
}

// ── Applied / Tests tabs ──
// Вкладка откликов state
const AppliedState = { all: [], shown: 0, pageSize: 80 };

async function loadApplied(force) {
  if (!force && AppliedState.all.length) { appliedRender(); return; }
  try {
    const res = await fetch('/api/applied?limit=2000');
    const items = await res.json();
    AppliedState.all = items;
    // Заполняем фильтр аккаунтов
    const sel = document.getElementById('applied-acc-filter');
    const prev = sel.value;
    const accs = [...new Set(items.map(i => i.account).filter(Boolean))].sort();
    sel.innerHTML = `<option value="">${t('applied_all_accs')}</option>` +
      accs.map(a => `<option value="${esc(a)}"${a===prev?' selected':''}>${esc(a)}</option>`).join('');
    appliedRender();
  } catch(e) { console.error('loadApplied', e); }
}

function appliedSort(field) {
  if (AppliedSort.field === field) AppliedSort.dir *= -1;
  else { AppliedSort.field = field; AppliedSort.dir = -1; }
  // Обновляем стрелки в заголовках
  document.querySelectorAll('#panel-applied .sort-th').forEach(th => {
    const f = th.getAttribute('onclick')?.match(/appliedSort\('(\w+)'\)/)?.[1];
    th.classList.toggle('sorted', f === field);
    const arrow = th.querySelector('.sort-arrow');
    if (arrow) arrow.textContent = (f === field) ? (AppliedSort.dir === -1 ? '↓' : '↑') : '↕';
  });
  appliedRender();
}

function appliedRender() {
  const search = (document.getElementById('applied-search')?.value || '').toLowerCase();
  const accF   = document.getElementById('applied-acc-filter')?.value || '';
  const hideEmpty = document.getElementById('applied-hide-empty')?.checked;

  let items = AppliedState.all;
  if (accF)      items = items.filter(i => i.account === accF);
  if (hideEmpty) items = items.filter(i => i.title || i.company);
  if (search)    items = items.filter(i =>
    (i.title||'').toLowerCase().includes(search) ||
    (i.company||'').toLowerCase().includes(search) ||
    (i.vacancy_id||'').includes(search)
  );

  // Сортировка
  const sf = AppliedSort.field, sd = AppliedSort.dir;
  items = [...items].sort((a, b) => {
    let av = a[sf] ?? '', bv = b[sf] ?? '';
    if (typeof av === 'number') return (av - bv) * sd;
    return String(av).localeCompare(String(bv), 'ru') * sd;
  });

  document.getElementById('applied-count').textContent = `(${items.length})`;
  AppliedState.shown = Math.min(AppliedState.pageSize, items.length);
  appliedFillTable(items.slice(0, AppliedState.shown));

  const lm = document.getElementById('applied-loadmore');
  const sh = document.getElementById('applied-shown');
  if (items.length > AppliedState.shown) {
    lm.style.display = 'block';
    sh.textContent = `${t('shown_of')} ${AppliedState.shown} ${t('shown_of2')} ${items.length}`;
    lm._items = items;
  } else {
    lm.style.display = 'none';
  }
}

function appliedShowMore() {
  const lm = document.getElementById('applied-loadmore');
  const items = lm._items || [];
  AppliedState.shown = Math.min(AppliedState.shown + AppliedState.pageSize, items.length);
  appliedFillTable(items.slice(0, AppliedState.shown));
  const sh = document.getElementById('applied-shown');
  if (AppliedState.shown >= items.length) {
    lm.style.display = 'none';
  } else {
    sh.textContent = `${t('shown_of')} ${AppliedState.shown} ${t('shown_of2')} ${items.length}`;
  }
}

function appliedFillTable(items) {
  const tbody = document.getElementById('applied-tbody');
  tbody.innerHTML = items.map(item => {
    const dt = item.at
      ? new Date(item.at).toLocaleString('ru-RU', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})
      : '';
    const acc = (item.account || '').replace(/^(.*?)\s*\((.+?)\)\s*$/, '$2') || item.account || '';
    const sal = item.salary_from || item.salary_to
      ? `${item.salary_from ? item.salary_from.toLocaleString('ru') : '?'} — ${item.salary_to ? item.salary_to.toLocaleString('ru') : '?'}`
      : '';
    const hasTitle = !!(item.title || item.company);
    const titleCell = item.title
      ? `<a href="${esc(item.url)}" target="_blank">${esc(item.title)}</a>`
      : `<a href="${esc(item.url)}" target="_blank" style="color:var(--dim)">hh.ru/vacancy/${esc(item.vacancy_id)}</a>`;
    return `<tr class="${hasTitle ? '' : 'row-no-title'}">
      <td class="c-dim" style="white-space:nowrap">${dt}</td>
      <td style="white-space:nowrap">${esc(acc)}</td>
      <td>${titleCell}</td>
      <td>${esc(item.company || '')}</td>
      <td class="c-green" style="white-space:nowrap">${sal}</td>
    </tr>`;
  }).join('');
}

// ── Vacancy DB tab ───────────────────────────────────────────────
const DBState = { all: [], shown: 0, pageSize: 100 };
const DB_STATUS = {
  sent:         ['✅', 'db_status_sent_lbl',        'c-green'],
  test_passed:  ['📝', 'db_status_test_passed_lbl', 'c-cyan'],
  test_pending: ['🧪', 'db_status_test_pending_lbl','c-magenta'],
};
// Переведённые подписи DB_STATUS
T.ru.db_status_sent_lbl         = 'Откликнулись';
T.ru.db_status_test_passed_lbl  = 'Тест пройден';
T.ru.db_status_test_pending_lbl = 'Не пройден';
T.en.db_status_sent_lbl         = 'Applied';
T.en.db_status_test_passed_lbl  = 'Test passed';
T.en.db_status_test_pending_lbl = 'Not passed';

async function loadDB(force) {
  if (!force && DBState.all.length) { dbRender(); return; }
  try {
    const res = await fetch('/api/vacancies?limit=3000');
    const items = await res.json();
    DBState.all = items;
    // Заполняем фильтр аккаунтов
    const sel = document.getElementById('db-acc-filter');
    const prev = sel.value;
    const accs = [...new Set(items.flatMap(i => i.applied_by || []))].sort();
    sel.innerHTML = `<option value="">${t('db_all_accs')}</option>` +
      accs.map(a => `<option value="${esc(a)}"${a===prev?' selected':''}>${esc(a)}</option>`).join('');
    dbRender();
  } catch(e) { console.error('loadDB', e); }
}

function dbSort(field) {
  if (DBSort.field === field) DBSort.dir *= -1;
  else { DBSort.field = field; DBSort.dir = -1; }
  document.querySelectorAll('#panel-db .sort-th').forEach(th => {
    const f = th.getAttribute('onclick')?.match(/dbSort\('(\w+)'\)/)?.[1];
    th.classList.toggle('sorted', f === field);
    const arrow = th.querySelector('.sort-arrow');
    if (arrow) arrow.textContent = (f === field) ? (DBSort.dir === -1 ? '↓' : '↑') : '↕';
  });
  dbRender();
}

function dbRender() {
  const search  = (document.getElementById('db-search')?.value || '').toLowerCase();
  const statusF = document.getElementById('db-status-filter')?.value || '';
  const accF    = document.getElementById('db-acc-filter')?.value || '';

  let items = DBState.all;
  if (statusF) items = items.filter(i => i.status === statusF);
  if (accF)    items = items.filter(i => (i.applied_by || []).includes(accF));
  if (search)  items = items.filter(i =>
    (i.title||'').toLowerCase().includes(search) ||
    (i.company||'').toLowerCase().includes(search) ||
    (i.vacancy_id||'').includes(search)
  );

  // Сортировка
  const sf = DBSort.field, sd = DBSort.dir;
  items = [...items].sort((a, b) => {
    let av = a[sf] ?? '', bv = b[sf] ?? '';
    if (typeof av === 'number') return (av - bv) * sd;
    return String(av).localeCompare(String(bv), 'ru') * sd;
  });

  document.getElementById('db-count').textContent =
    `(${items.length} из ${DBState.all.length})`;
  DBState.shown = Math.min(DBState.pageSize, items.length);
  dbFillTable(items.slice(0, DBState.shown));

  const lm = document.getElementById('db-loadmore');
  const sh = document.getElementById('db-shown');
  if (items.length > DBState.shown) {
    lm.style.display = 'block';
    sh.textContent = `${t('shown_of')} ${DBState.shown} ${t('shown_of2')} ${items.length}`;
    lm._items = items;
  } else {
    lm.style.display = 'none';
  }
}

function dbShowMore() {
  const lm = document.getElementById('db-loadmore');
  const items = lm._items || [];
  DBState.shown = Math.min(DBState.shown + DBState.pageSize, items.length);
  dbFillTable(items.slice(0, DBState.shown));
  const sh = document.getElementById('db-shown');
  if (DBState.shown >= items.length) lm.style.display = 'none';
  else sh.textContent = `${t('shown_of')} ${DBState.shown} ${t('shown_of2')} ${items.length}`;
}

function dbFillTable(items) {
  const tbody = document.getElementById('db-tbody');
  tbody.innerHTML = items.map(item => {
    const [icon, labelKey, cls] = DB_STATUS[item.status] || ['❓', null, 'c-dim'];
    const label = labelKey ? t(labelKey) : item.status;
    const dt = item.at
      ? new Date(item.at).toLocaleString('ru-RU', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})
      : '';
    const titleCell = item.title
      ? `<a href="${esc(item.url)}" target="_blank">${esc(item.title)}</a>`
      : `<a href="${esc(item.url)}" target="_blank" style="color:var(--dim)">hh.ru/vacancy/${esc(item.vacancy_id)}</a>`;
    const accs = (item.applied_by || [])
      .map(a => `<span style="font-size:10px;background:var(--bg-card2);padding:1px 5px;border-radius:3px">${esc(a.replace(/^.*?\((.+?)\).*$/, '$1') || a)}</span>`)
      .join(' ');
    return `<tr>
      <td><span class="${cls}" style="white-space:nowrap">${icon} ${label}</span></td>
      <td class="c-dim" style="white-space:nowrap">${dt}</td>
      <td>${titleCell}</td>
      <td>${esc(item.company || '')}</td>
      <td>${accs || '<span class="c-dim">—</span>'}</td>
      <td><button class="btn-sm" style="padding:1px 6px;color:var(--red);border-color:var(--red)"
        onclick="dbDelete('${esc(item.vacancy_id)}',this)" title="Удалить из базы">✕</button></td>
    </tr>`;
  }).join('');
}

async function dbDelete(vid, btn) {
  if (!await showConfirm(`${t('confirm_del_db_pre')} <b>${vid}</b> ${t('confirm_del_db_mid')}<br><span style="color:var(--dim);font-size:12px">${t('confirm_del_db_body')}</span>`)) return;
  btn.disabled = true;
  try {
    const res = await fetch(`/api/vacancy/${vid}`, {method:'DELETE'});
    const data = await res.json();
    if (data.ok) {
      DBState.all = DBState.all.filter(i => i.vacancy_id !== vid);
      btn.closest('tr').remove();
      const cnt = document.getElementById('db-count');
      if (cnt) cnt.textContent = `(${DBState.all.length})`;
    } else {
      btn.disabled = false;
    }
  } catch(e) { btn.disabled = false; }
}

async function loadTests() {
  try {
    const res = await fetch('/api/tests?limit=300');
    const items = await res.json();
    const tbody = document.getElementById('tests-tbody');
    document.getElementById('tests-count').textContent = `(${items.length})`;

    tbody.innerHTML = items.map(item => {
      const dt = item.at ? new Date(item.at).toLocaleString('ru-RU', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '';
      // Имя аккаунта: по возможности короткое, без текста в скобках
      const accFull = item.account_name || '';
      const accShort = accFull.replace(/^.*?\((.+?)\).*$/, '$1') || accFull;
      const resumeLink = item.resume_hash
        ? `<a href="https://hh.ru/resume/${item.resume_hash}" target="_blank" style="font-size:11px;color:var(--cyan)">${accShort}</a>`
        : `<span class="c-dim">${esc(accShort) || '—'}</span>`;
      // Список аккаунтов, которые откликались
      const appliedBy = item.applied_by || [];
      const appliedCell = appliedBy.length
        ? `<span style="color:var(--green)">✅ ${appliedBy.map(a => a.replace(/^.*?\((.+?)\).*$/, '$1') || a).join(', ')}</span>`
        : `<span class="c-dim">—</span>`;
      return `<tr>
        <td class="c-dim">${dt}</td>
        <td>${esc(item.title || item.vacancy_id)}</td>
        <td>${esc(item.company)}</td>
        <td>${resumeLink}</td>
        <td>${appliedCell}</td>
        <td><a href="${esc(item.url)}" target="_blank">hh.ru/vacancy/${item.vacancy_id}</a></td>
      </tr>`;
    }).join('');
  } catch(e) {}
}

// ── Tabs switching ──────────────────────────────────────────────
document.getElementById('tabs').addEventListener('click', e => {
  const t = e.target.closest('.tab');
  if (!t) return;
  const tab = t.dataset.tab;
  if (!tab) return;

  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(el => el.classList.remove('active'));
  t.classList.add('active');
  document.getElementById('panel-' + tab).classList.add('active');
  State.currentTab = tab;
  try { localStorage.setItem('hh-tab', tab); } catch(e) {}

  // Сбрасываем флаги сборки вкладок настроек, чтобы при следующем открытии взять свежие данные
  if (tab !== 'settings') {
    const urlEl = document.getElementById('url-pool-rows');
    if (urlEl) urlEl.dataset.built = 'false';
    const sessEl = document.getElementById('sess-list');
    if (sessEl) sessEl.dataset.count = '';
  }

  // Загружаем REST-вкладки при переключении
  if (tab === 'applied') loadApplied();
  else if (tab === 'tests') loadTests();
  else if (tab === 'db') loadDB();
  else if (tab === 'hh' && State.lastSnapshot) renderHH(State.lastSnapshot);
  else if (tab === 'llm') {
    // Перезагружаем таблицу только если данные старше 10 секунд: это предотвращает очистку при быстрых переключениях
    const stale = Date.now() - _llmLastDbRefresh > 10000;
    if (stale) { llmInterviewsLoad(); llmRenderAccStats(); }
    if (State.lastSnapshot) renderLlmLog(State.lastSnapshot);
  }
  else if (tab === 'log' && State.lastSnapshot) renderLog(State.lastSnapshot);
  else if (tab === 'views') loadViews();
  else if (tab === 'apply') {
    if (State.lastSnapshot) applyBuildAccountSelect(State.lastSnapshot);
  }
  else if (tab === 'settings' && State.lastSnapshot) {
    syncSettingsSliders(State.lastSnapshot);
    qSyncFromSnapshot(State.lastSnapshot);
    ltSyncFromSnapshot(State.lastSnapshot);
    buildAccCookiesList(State.lastSnapshot);
    urlPoolBuild(State.lastSnapshot);
    buildSessList(State.lastSnapshot);
  }
});

function syncSettingsSliders(snap) {
  if (!snap.config) return;
  SETTINGS_DEF.forEach(s => {
    const el = document.getElementById('sr-' + s.key);
    const sv = document.getElementById('sv-' + s.key);
    if (el && snap.config[s.key] !== undefined) {
      el.value = snap.config[s.key];
      if (sv) sv.textContent = snap.config[s.key];
    }
  });
}

// ── Helpers ──────────────────────────────────────────────────
function esc(s) {
  if (!s) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function colorVar(color) {
  const map = {
    cyan: 'var(--cyan)',
    magenta: 'var(--magenta)',
    green: 'var(--green)',
    yellow: 'var(--yellow)',
    red: 'var(--red)',
    blue: 'var(--blue)',
  };
  return map[color] || 'var(--text)';
}

// ── Session mode toggle ───────────────────────────────────────
let _sessMode = 'curl';
function sessSetMode(mode) {
  _sessMode = mode;
  document.getElementById('sess-panel-curl').style.display   = mode === 'curl'   ? '' : 'none';
  document.getElementById('sess-panel-manual').style.display = mode === 'manual' ? '' : 'none';
  const btnCurl   = document.getElementById('sess-mode-curl');
  const btnManual = document.getElementById('sess-mode-manual');
  btnCurl.style.background   = mode === 'curl'   ? 'var(--cyan)' : 'transparent';
  btnCurl.style.color        = mode === 'curl'   ? '#000'        : 'var(--dim)';
  btnManual.style.background = mode === 'manual' ? 'var(--cyan)' : 'transparent';
  btnManual.style.color      = mode === 'manual' ? '#000'        : 'var(--dim)';
}

// ── Session Add ───────────────────────────────────────────────
async function sessionAdd() {
  const nameEl   = document.getElementById('session-name');
  const letterEl = document.getElementById('session-letter');
  const st       = document.getElementById('session-status');
  let cookieStr = '';

  if (_sessMode === 'manual') {
    const hhtoken   = document.getElementById('ck-hhtoken')?.value.trim();
    const xsrf      = document.getElementById('ck-xsrf')?.value.trim();
    const hhul      = document.getElementById('ck-hhul')?.value.trim();
    const cryptedId = document.getElementById('ck-crypted-id')?.value.trim();
    if (!hhtoken) { st.textContent = '❌ hhtoken обязателен'; st.style.color = 'var(--red)'; return; }
    if (!xsrf)    { st.textContent = '❌ _xsrf обязателен';   st.style.color = 'var(--red)'; return; }
    const parts = [`hhtoken=${hhtoken}`, `_xsrf=${xsrf}`];
    if (hhul)      parts.push(`hhul=${hhul}`);
    if (cryptedId) parts.push(`crypted_id=${cryptedId}`);
    cookieStr = parts.join('; ');
  } else {
    const ta = document.getElementById('session-cookies');
    cookieStr = ta?.value.trim();
    if (!cookieStr) { st.textContent = '❌ Вставьте строку cookies'; st.style.color = 'var(--red)'; return; }
  }

  st.textContent = '⏳ Проверяю сессию...'; st.style.color = 'var(--dim)';
  try {
    const res = await fetch('/api/session/add', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        cookies: cookieStr,
        name: nameEl?.value.trim() || '',
        letter: letterEl?.value || ''
      })
    });
    const data = await res.json();
    if (data.status === 'ok') {
      st.textContent = '✅ ' + data.message; st.style.color = 'var(--green)';
      // Очищаем оба режима
      const ta = document.getElementById('session-cookies');
      if (ta) ta.value = '';
      ['ck-hhtoken','ck-xsrf','ck-hhul','ck-crypted-id'].forEach(id => {
        const el = document.getElementById(id); if (el) el.value = '';
      });
      if (nameEl)   nameEl.value = '';
      if (letterEl) letterEl.value = '';
    } else {
      st.textContent = '❌ ' + data.message; st.style.color = 'var(--red)';
    }
  } catch(e) {
    st.textContent = '❌ ' + e; st.style.color = 'var(--red)';
  }
}


async function sessionChangeResume(idx, hash) {
  await fetch('/api/session/' + idx, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resume_hash: hash })
  });
  // Обновляем ссылку на резюме в карточке без перерисовки
  const card = document.getElementById('sess-card-' + idx);
  if (card) {
    const link = card.querySelector('a[href*="/resume/"]');
    if (link) link.href = 'https://hh.ru/resume/' + hash;
  }
}

async function sessionSaveLetter(idx) {
  const ta = document.getElementById('sess-letter-' + idx);
  const st = document.getElementById('sess-letter-st-' + idx);
  if (!ta || !st) return;
  st.textContent = '⏳'; st.style.color = 'var(--dim)';
  try {
    const res = await fetch('/api/session/' + idx, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({letter: ta.value})
    });
    const data = await res.json();
    if (data.status === 'ok') {
      st.textContent = '✅ Сохранено'; st.style.color = 'var(--green)';
      // Обновить ApplyLetters чтобы шаблон в дропдауне тоже обновился
      ApplyLetters[idx] = ta.value;
      setTimeout(() => { st.textContent = ''; }, 2000);
    } else {
      st.textContent = '❌ ' + data.message; st.style.color = 'var(--red)';
    }
  } catch(e) {
    st.textContent = '❌ ' + e; st.style.color = 'var(--red)';
  }
}

async function sessionRemove(idx) {
  if (!await showConfirm(t('confirm_del_sess'))) return;
  const card = document.getElementById('card-' + idx);
  if (card) card.remove();
  await fetch('/api/session/' + idx, {method: 'DELETE'});
}

async function sessionRefresh(idx) {
  const res = await fetch('/api/session/' + idx + '/refresh', {method: 'POST'});
  const data = await res.json();
  // Снимок состояния обновится через WebSocket
}

async function sessionActivate(idx) {
  const res = await fetch('/api/session/' + idx + '/activate', {method: 'POST'});
  const data = await res.json();
  if (data.status !== 'ok') {
    alert('Ошибка: ' + data.message);
  }
}

// ── Apply Tab ────────────────────────────────────────────────
const ApplyState = { checking: false, submitting: false, vid: '', accIdx: 0, questions: [] };

const ApplyLetters = {};

function applyBuildAccountSelect(snap) {
  const sel = document.getElementById('apply-account');
  const tpl = document.getElementById('apply-letter-tpl');
  if (!sel || !snap) return;

  (snap.accounts || []).forEach(a => { ApplyLetters[a.idx] = a.letter || ''; });

  // пересоздаём только если изменился состав аккаунтов
  const newKey = (snap.accounts || []).map(a => a.idx + ':' + a.name).join(',');
  if (sel.dataset.builtKey !== newKey) {
    sel.dataset.builtKey = newKey;
    const prev = sel.value;
    sel.innerHTML = (snap.accounts || []).map(a =>
      `<option value="${a.idx}">${esc(a.name)}</option>`
    ).join('');
    if (prev) sel.value = prev;
  }

  // Пересобираем dropdown шаблонов: один option на письмо аккаунта
  if (tpl) {
    const newTplKey = newKey;
    if (tpl.dataset.builtKey !== newTplKey) {
      tpl.dataset.builtKey = newTplKey;
      const prevTpl = tpl.value;
      tpl.innerHTML = `<option value="">— выбрать шаблон —</option>` +
        (snap.accounts || []).map(a =>
          `<option value="${a.idx}">${esc(a.name)}</option>`
        ).join('');
      if (prevTpl) tpl.value = prevTpl;
    }
  }

  // Заполняем textarea письма, если оно пустое или всё ещё содержит письмо по умолчанию
  const ta = document.getElementById('apply-letter');
  if (ta && (!ta.value || Object.values(ApplyLetters).includes(ta.value))) {
    ta.value = ApplyLetters[parseInt(sel.value) || 0] || '';
  }
}

function applyFillLetter(idx) {
  const ta = document.getElementById('apply-letter');
  if (ta) ta.value = ApplyLetters[parseInt(idx)] || '';
  // Синхронизируем selector шаблонов с выбранным аккаунтом
  const tpl = document.getElementById('apply-letter-tpl');
  if (tpl) tpl.value = idx;
}

function applyPickTemplate(idx) {
  if (!idx) return;
  const ta = document.getElementById('apply-letter');
  if (ta && ApplyLetters[parseInt(idx)] !== undefined)
    ta.value = ApplyLetters[parseInt(idx)];
}

function applyShowResult(msg, type) {
  const el = document.getElementById('apply-result');
  el.style.display = '';
  el.className = 'apply-result ' + type;
  el.innerHTML = msg;
}

function applyHideQuestionnaire() {
  document.getElementById('apply-questionnaire').style.display = 'none';
  document.getElementById('apply-questionnaire').innerHTML = '';
}

async function applyCheck() {
  if (ApplyState.checking) return;
  const accIdx = parseInt(document.getElementById('apply-account').value || '0');
  const raw = document.getElementById('apply-vacancy').value.trim();
  if (!raw) { applyShowResult('Введите ссылку или ID вакансии', 'err'); return; }

  ApplyState.checking = true;
  ApplyState.accIdx = accIdx;
  applyHideQuestionnaire();
  applyShowResult('⏳ Проверяю вакансию...', 'info');

  try {
    const letter = document.getElementById('apply-letter')?.value || '';
    const res = await fetch('/api/apply/check', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({account_idx: accIdx, vacancy_id: raw, letter})
    });
    const data = await res.json();
    ApplyState.vid = data.vacancy_id || raw;

    if (data.status === 'sent') {
      applyShowResult(`✅ ${data.message}`, 'ok');
      applyHideQuestionnaire();
    } else if (data.status === 'already') {
      applyShowResult(`🔄 ${data.message}`, 'warn');
    } else if (data.status === 'limit') {
      applyShowResult(`🚫 ${data.message}`, 'err');
    } else if (data.status === 'test_required') {
      ApplyState.questions = data.questions || [];
      applyShowResult(
        `📝 <b>${data.message}</b><br>Проверьте ответы ниже и нажмите «Откликнуться»`,
        'info'
      );
      applyRenderQuestionnaire(data);
    } else {
      applyShowResult(`❌ ${data.message || 'Неизвестная ошибка'}`, 'err');
    }
  } catch(e) {
    applyShowResult('❌ Ошибка запроса: ' + e, 'err');
  } finally {
    ApplyState.checking = false;
  }
}

function applyRenderQuestionnaire(data) {
  const el = document.getElementById('apply-questionnaire');
  el.style.display = '';
  const qs = data.questions || [];

  let html = `
    <hr class="apply-divider">
    <div style="font-size:13px;font-weight:700;margin-bottom:12px">
      📋 Опросник — ${qs.length} вопросов
    </div>

    <div class="apply-q-list">
  `;

  qs.forEach((q, i) => {
    html += `<div class="apply-q-item">
      <div class="apply-q-num">Вопрос ${i+1} из ${qs.length}</div>
      <div class="apply-q-text">${esc(q.text)}</div>
    `;

    if (q.type === 'radio') {
      html += `<div class="apply-radio-opts">`;
      q.options.forEach(opt => {
        const checked = opt.value === q.suggested ? 'checked' : '';
        html += `<label class="apply-radio-opt">
          <input type="radio" name="aq_${q.field}" value="${esc(opt.value)}" ${checked}>
          ${esc(opt.label)}
        </label>`;
      });
      html += `</div>`;
    } else if (q.type === 'textarea') {
      html += `<textarea class="apply-q-answer" id="aq_${q.field}" rows="3">${esc(q.suggested)}</textarea>`;
    }
    html += `</div>`;
  });

  html += `</div>
    <div class="apply-btn-row" style="margin-top:16px">
      <button class="apply-btn" onclick="applySubmit()">🚀 Откликнуться</button>
      <button class="apply-btn-secondary" onclick="applyHideQuestionnaire();applyShowResult('','');document.getElementById('apply-result').style.display='none'">Отмена</button>
      <span id="apply-submit-status" style="font-size:12px;color:var(--dim)"></span>
    </div>
  `;

  el.innerHTML = html;
}

async function applySubmit() {
  if (ApplyState.submitting) return;
  ApplyState.submitting = true;
  const statusEl = document.getElementById('apply-submit-status');
  if (statusEl) statusEl.textContent = '⏳ Отправляю...';

  // Собираем ответы
  const answers = {};
  ApplyState.questions.forEach(q => {
    if (q.type === 'radio') {
      const checked = document.querySelector(`input[name="aq_${q.field}"]:checked`);
      if (checked) answers[q.field] = checked.value;
    } else if (q.type === 'textarea') {
      const ta = document.getElementById('aq_' + q.field);
      if (ta) answers[q.field] = ta.value;
    }
  });

  const letter = document.getElementById('apply-letter')?.value || '';

  try {
    const res = await fetch('/api/apply/submit', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({account_idx: ApplyState.accIdx, vacancy_id: ApplyState.vid, letter, answers})
    });
    const data = await res.json();

    if (data.status === 'sent') {
      applyShowResult(`✅ ${data.message}`, 'ok');
      applyHideQuestionnaire();
    } else if (data.status === 'limit') {
      applyShowResult(`🚫 ${data.message}`, 'err');
    } else {
      applyShowResult(`❌ ${data.message}`, 'err');
    }
    if (statusEl) statusEl.textContent = '';
  } catch(e) {
    applyShowResult('❌ Ошибка: ' + e, 'err');
  } finally {
    ApplyState.submitting = false;
  }
}

// ── Resume Views Tab ────────────────────────────────────────
async function loadViews() {
  const statsRow = document.getElementById('views-stats-row');
  const accsEl = document.getElementById('views-accounts');
  if (!statsRow || !accsEl) return;

  const snap = State.lastSnapshot;
  if (!snap) return;

  // Агрегированная статистика заголовка
  let totalViews = 0, totalViewsNew = 0, totalShows = 0, totalInv = 0, totalInvNew = 0;
  (snap.accounts || []).forEach(a => {
    totalViews += a.resume_views_7d || 0;
    totalViewsNew += a.resume_views_new || 0;
    totalShows += a.resume_shows_7d || 0;
    totalInv += a.resume_invitations_7d || 0;
    totalInvNew += a.resume_invitations_new || 0;
  });

  statsRow.innerHTML = `
    <div class="views-stat-card"><div class="views-stat-val c-cyan">${totalViews}</div><div class="views-stat-lbl">${t('views_7d')}</div></div>
    <div class="views-stat-card"><div class="views-stat-val c-green">+${totalViewsNew}</div><div class="views-stat-lbl">${t('views_new')}</div></div>
    <div class="views-stat-card"><div class="views-stat-val" style="color:var(--dim)">${totalShows}</div><div class="views-stat-lbl">${t('views_shows')}</div></div>
    <div class="views-stat-card"><div class="views-stat-val c-magenta">${totalInv}</div><div class="views-stat-lbl">${t('views_invitations')}</div></div>
    <div class="views-stat-card"><div class="views-stat-val c-green">+${totalInvNew}</div><div class="views-stat-lbl">${t('views_inv_new')}</div></div>
  `;

  // Блоки по аккаунтам
  const existingIds = new Set([...accsEl.querySelectorAll('.views-acc-block')].map(el => el.dataset.idx));
  const snapIds = new Set((snap.accounts || []).map(a => String(a.idx)));
  const needRebuild = [...snapIds].some(id => !existingIds.has(id)) || [...existingIds].some(id => !snapIds.has(id));

  if (needRebuild) {
    accsEl.innerHTML = '';
    for (const acc of (snap.accounts || [])) {
      const block = document.createElement('div');
      block.className = 'views-acc-block';
      block.dataset.idx = String(acc.idx);
      const colorStyle = `color:${colorVar(acc.color)}`;
      block.innerHTML = `
        <div class="views-acc-title">
          <span style="${colorStyle}">${esc(acc.name)}</span>
          <button class="btn-refresh" onclick="loadViewHistory(${acc.idx})">${t('btn_load_history')}</button>
          <button class="btn-sm" onclick="declineDiscards(${acc.idx},this)">🗑️ Очистить дискарды</button>
        </div>
        <div id="views-hist-${acc.idx}"><div class="c-dim" style="font-size:12px;padding:8px 0">⏳ Загружаю...</div></div>
      `;
      accsEl.appendChild(block);
      loadViewHistory(acc.idx);
    }
  } else {
    // повторяем загрузку для тех у кого ещё нет данных и не помечено как loaded
    for (const acc of (snap.accounts || [])) {
      const histEl = document.getElementById('views-hist-' + acc.idx);
      if (histEl && !histEl.dataset.loaded && !histEl.dataset.loading) {
        histEl.dataset.loading = '1';
        loadViewHistory(acc.idx).finally(() => { histEl.removeAttribute('data-loading'); });
      }
    }
  }
}

async function loadViewHistory(idx) {
  const el = document.getElementById('views-hist-' + idx);
  if (!el) return;
  el.innerHTML = '<div class="c-dim" style="font-size:12px;padding:8px 0">⏳ Загружаю...</div>';
  try {
    const res = await fetch(`/api/account/${idx}/resume_views`);
    const data = await res.json();

    // обновляем карточки статов сразу из ответа API не дожидаясь WebSocket
    const s = data.stats || {};
    const statsRow = document.getElementById('views-stats-row');
    if (statsRow && (s.views_7d || s.shows_7d || s.invitations_7d)) {
      statsRow.querySelector('.views-stat-val.c-cyan') && (statsRow.querySelector('.views-stat-val.c-cyan').textContent = s.views_7d || 0);
      const greens = statsRow.querySelectorAll('.views-stat-val.c-green');
      if (greens[0]) greens[0].textContent = '+' + (s.views_new || 0);
      if (greens[1]) greens[1].textContent = '+' + (s.invitations_new || 0);
      const dim = statsRow.querySelector('.views-stat-val[style]');
      if (dim) dim.textContent = s.shows_7d || 0;
      const magenta = statsRow.querySelector('.views-stat-val.c-magenta');
      if (magenta) magenta.textContent = s.invitations_7d || 0;
    }

    el.dataset.loaded = '1'; // помечаем — больше не ретраить
    const history = data.history || [];
    if (!history.length) {
      el.innerHTML = `<div class="c-dim" style="font-size:12px;padding:8px 0">${t('views_no_data')}</div>`;
      return;
    }
    el.innerHTML = `
      <table class="views-table">
        <thead><tr><th>${t('col_date')}</th><th>${t('col_employer')}</th><th>${t('col_vacancy')}</th></tr></thead>
        <tbody>
          ${history.map(h => `<tr>
            <td class="c-dim">${esc(h.date)}</td>
            <td><a href="https://hh.ru/employer/${esc(h.employer_id)}" target="_blank">${esc(h.name)}</a></td>
            <td class="c-dim">${esc(h.vacancy)}</td>
          </tr>`).join('')}
        </tbody>
      </table>
    `;
  } catch(e) {
    el.innerHTML = '<div class="c-red" style="font-size:12px">Ошибка загрузки</div>';
    // не ставим loaded — пусть retry при следующем тике
  }
}

async function declineDiscards(idx, btn) {
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = '⏳ Обрабатываю...';
  try {
    const res = await fetch(`/api/account/${idx}/decline_discards`, {method:'POST'});
    const data = await res.json();
    btn.textContent = `✅ Отклонено: ${data.declined || 0}`;
    setTimeout(() => { btn.disabled = false; btn.textContent = t('btn_clear_discards'); }, 4000);
  } catch(e) {
    btn.textContent = '❌ Ошибка';
    setTimeout(() => { btn.disabled = false; btn.textContent = t('btn_clear_discards'); }, 3000);
  }
}

async function applyTestsToggle(idx, cb) {
  try {
    const res = await fetch(`/api/account/${idx}/apply_tests`, {method:'POST'});
    const data = await res.json();
    if (!data.ok) { cb.checked = !cb.checked; return; }
    const label = document.getElementById('acc-apply-label-' + idx);
    if (label) {
      if (data.apply_tests) label.classList.add('active');
      else label.classList.remove('active');
    }
  } catch(e) {
    cb.checked = !cb.checked;
  }
}

// ── JSON Editor ─────────────────────────────────────────────────
const JSON_CONFIG_TEMPLATE = {
  "pages_per_url": 3,
  "max_concurrent": 5,
  "response_delay": 2,
  "pause_between_cycles": 5,
  "limit_check_interval": 30,
  "resume_touch_interval": 4,
  "batch_responses": 5,
  "min_salary": 0,
  "questionnaire_default_answer": "Готова рассказать подробнее на собеседовании.",
  "questionnaire_templates": [
    {"keyword": "ключевое слово вопроса", "answer": "ответ на этот вопрос"}
  ],
  "letter_templates": [
    {"name": "Название шаблона", "text": "Текст сопроводительного письма..."}
  ],
  "url_pool": [
    {"url": "https://hh.ru/search/vacancy?text=QA&area=1&order_by=publication_time&items_on_page=20", "pages": 40}
  ]
};

const JSON_ACCOUNT_TEMPLATE = {
  "name": "Имя (Компания)",
  "short": "Имя",
  "color": "yellow",
  "resume_hash": "ВСТАВЬТЕ_ХЭШ_РЕЗЮМЕ",
  "letter": "",
  "apply_tests": false,
  "urls": [],
  "cookies": {
    "hhtoken": "",
    "_xsrf": "",
    "hhul": "",
    "crypted_id": ""
  }
};

function jsonConfigTemplate() {
  const ta = document.getElementById('json-config-ta');
  const st = document.getElementById('json-config-st');
  ta.value = JSON.stringify(JSON_CONFIG_TEMPLATE, null, 2);
  st.textContent = '📋 Шаблон загружен — отредактируйте и сохраните';
  st.style.color = 'var(--cyan)';
}

function jsonAccountsTemplate() {
  const ta = document.getElementById('json-accounts-ta');
  const st = document.getElementById('json-accounts-st');
  // Если уже есть данные — добавляем новый аккаунт в конец массива
  let arr = [];
  try { arr = JSON.parse(ta.value); if (!Array.isArray(arr)) arr = []; } catch(e) {}
  arr.push(JSON.parse(JSON.stringify(JSON_ACCOUNT_TEMPLATE)));
  ta.value = JSON.stringify(arr, null, 2);
  st.textContent = arr.length > 1
    ? `📋 Добавлен шаблон аккаунта (всего ${arr.length})`
    : '📋 Шаблон загружен — заполните данные и сохраните';
  st.style.color = 'var(--cyan)';
}
async function jsonConfigLoad(btn) {
  btn.disabled = true;
  try {
    const res = await fetch('/api/raw/config');
    const data = await res.json();
    document.getElementById('json-config-ta').value = JSON.stringify(data, null, 2);
    document.getElementById('json-config-st').textContent = '✅ Загружено';
    document.getElementById('json-config-st').style.color = 'var(--green)';
  } catch(e) {
    document.getElementById('json-config-st').textContent = '❌ ' + e;
    document.getElementById('json-config-st').style.color = 'var(--red)';
  }
  btn.disabled = false;
}

async function jsonConfigSave(btn) {
  const ta = document.getElementById('json-config-ta');
  const st = document.getElementById('json-config-st');
  let parsed;
  try { parsed = JSON.parse(ta.value); }
  catch(e) { st.textContent = '❌ Невалидный JSON: ' + e.message; st.style.color = 'var(--red)'; return; }
  btn.disabled = true;
  try {
    const res = await fetch('/api/raw/config', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(parsed)
    });
    const data = await res.json();
    if (data.ok) { st.textContent = '✅ Сохранено'; st.style.color = 'var(--green)'; }
    else { st.textContent = '❌ ' + (data.error || 'Ошибка'); st.style.color = 'var(--red)'; }
  } catch(e) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  btn.disabled = false;
}

async function jsonAccountsLoad(btn) {
  btn.disabled = true;
  try {
    const res = await fetch('/api/raw/accounts');
    const data = await res.json();
    document.getElementById('json-accounts-ta').value = JSON.stringify(data, null, 2);
    document.getElementById('json-accounts-st').textContent = '✅ Загружено';
    document.getElementById('json-accounts-st').style.color = 'var(--green)';
  } catch(e) {
    document.getElementById('json-accounts-st').textContent = '❌ ' + e;
    document.getElementById('json-accounts-st').style.color = 'var(--red)';
  }
  btn.disabled = false;
}

async function jsonAccountsSave(btn) {
  const ta = document.getElementById('json-accounts-ta');
  const st = document.getElementById('json-accounts-st');
  let parsed;
  try { parsed = JSON.parse(ta.value); }
  catch(e) { st.textContent = '❌ Невалидный JSON: ' + e.message; st.style.color = 'var(--red)'; return; }
  if (!Array.isArray(parsed)) {
    st.textContent = '❌ Ожидается массив аккаунтов'; st.style.color = 'var(--red)'; return;
  }
  btn.disabled = true;
  try {
    const res = await fetch('/api/raw/accounts', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(parsed)
    });
    const data = await res.json();
    if (data.ok) { st.textContent = `✅ Сохранено (${data.count} аккаунтов)`; st.style.color = 'var(--green)'; }
    else { st.textContent = '❌ ' + (data.error || 'Ошибка'); st.style.color = 'var(--red)'; }
  } catch(e) { st.textContent = '❌ ' + e; st.style.color = 'var(--red)'; }
  btn.disabled = false;
}

// Обновляем статистику резюме в заголовке
function updateHeaderResumeStats(snap) {
  let totalViewsNew = 0, totalInvNew = 0, totalShows = 0;
  (snap.accounts || []).forEach(a => {
    totalViewsNew += a.resume_views_new || 0;
    totalInvNew += a.resume_invitations_new || 0;
    totalShows += a.resume_shows_7d || 0;
  });
  const hdrEl = document.getElementById('hdr-resume-stats');
  if (hdrEl) {
    hdrEl.style.display = (totalViewsNew > 0 || totalInvNew > 0 || totalShows > 0) ? '' : 'none';
    setText('hdr-views-new', totalViewsNew);
    setText('hdr-inv-new', totalInvNew);
    setText('hdr-shows', totalShows);
  }
}

// ── Questionnaire templates ──────────────────────────────────
function qRenderTemplates(templates) {
  const list = document.getElementById('q-templates-list');
  list.innerHTML = '';
  (templates || []).forEach((tmpl, i) => {
    const row = document.createElement('div');
    row.className = 'q-template-row';
    row.dataset.idx = i;
    row.innerHTML = `
      <button class="q-del" onclick="qDelTemplate(${i})" title="Удалить">✕</button>
      <label>${t('q_keywords_label')} — по ним ищется совпадение с текстом вопроса</label>
      <input type="text" class="q-keywords-input" placeholder="${t('q_keywords_ph')}"
        value="${esc((tmpl.keywords || []).join(', '))}">
      <label>${t('q_answer_label')}</label>
      <textarea class="q-answer-input" rows="3" placeholder="Ваш ответ...">${esc(tmpl.answer || '')}</textarea>
    `;
    list.appendChild(row);
  });
}

// ── Questionnaire presets ─────────────────────────────────────
const Q_PRESETS = {
  universal: {
    default: 'Готова рассказать подробнее на собеседовании.',
    templates: [
      { keywords: ['командировк'],
        answer: 'Да, готова к командировкам.' },
      { keywords: ['переработк', 'сверхурочн', 'задерж'],
        answer: 'Да, готова к переработкам при необходимости.' },
      { keywords: ['ненормированн', 'гибкий график', 'нестандартн'],
        answer: 'Да, рассматриваю.' },
      { keywords: ['вахт'],
        answer: 'Нет, вахтовый метод не рассматриваю.' },
      { keywords: ['ночн смен', 'сменн', 'посменн', '2/2', '3/3'],
        answer: 'Да, рассматриваю сменный график.' },
      { keywords: ['выходн', 'праздник', 'суббот', 'воскресен'],
        answer: 'Да, готова работать в выходные при необходимости.' },
      { keywords: ['почему', 'привлекает', 'хотите работать у нас', 'хотите работать в'],
        answer: 'Меня привлекает стабильная компания, интересные задачи и возможность профессионального роста.' },
      { keywords: ['расскажите о себе', 'опишите себя', 'кто вы'],
        answer: 'Ответственный и целеустремлённый специалист с опытом работы. Быстро обучаюсь, умею работать в команде и самостоятельно. Готова к новым задачам и развитию.' },
      { keywords: ['опыт работ', 'стаж', 'сколько лет'],
        answer: 'Имею опыт работы в данной сфере более 2 лет. Готова рассказать подробнее на собеседовании.' },
      { keywords: ['сильн сторон', 'достоинств', 'преимущест'],
        answer: 'Ответственность, стрессоустойчивость, коммуникабельность и быстрое обучение.' },
      { keywords: ['почему уволил', 'предыдущ', 'прошл место'],
        answer: 'В поиске новых возможностей для профессионального развития.' },
      { keywords: ['зарплат', 'оклад', 'доход', 'вознагражд', 'ожидани', 'желаем'],
        answer: 'От 70 000 рублей. Готова обсудить на собеседовании.' },
      { keywords: ['когда', 'приступить', 'выйти на работу', 'дата выхода', 'готов'],
        answer: 'Готова приступить в течение 2 недель.' },
      { keywords: ['формат работ', 'офис', 'удалённ', 'удален', 'remote', 'гибрид'],
        answer: 'Рассматриваю гибридный и удалённый формат.' },
      { keywords: ['город', 'регион', 'переезд', 'релокац'],
        answer: 'Готова рассмотреть предложение.' },
      { keywords: ['английск', 'english', 'иностранн язык'],
        answer: 'Базовый уровень.' },
      { keywords: ['автомобил', 'машин', 'водительск', 'права кат'],
        answer: 'Нет.' },
      { keywords: ['образован', 'диплом', 'вуз', 'институт', 'университет'],
        answer: 'Высшее.' },
      { keywords: ['обучени', 'курс', 'тренинг'],
        answer: 'Да, готова к обучению и развитию.' },
    ]
  },
  sales: {
    default: 'Готова рассказать подробнее на собеседовании.',
    templates: [
      { keywords: ['командировк'],
        answer: 'Да, готова.' },
      { keywords: ['переработк', 'сверхурочн'],
        answer: 'Да, при необходимости.' },
      { keywords: ['вахт'],
        answer: 'Нет.' },
      { keywords: ['почему', 'привлекает', 'хотите'],
        answer: 'Интересует возможность работать с клиентами, выполнять план и расти в доходе.' },
      { keywords: ['опыт продаж', 'продавал', 'менеджер по продажам'],
        answer: 'Да, есть опыт активных продаж. Умею работать с возражениями и выполнять KPI.' },
      { keywords: ['опыт работ с клиент', 'клиентск'],
        answer: 'Да, есть опыт работы с клиентами: входящие и исходящие звонки, консультации, оформление заказов.' },
      { keywords: ['колл-центр', 'кол центр', 'call center', 'оператор'],
        answer: 'Да, есть опыт работы оператором колл-центра.' },
      { keywords: ['crm', 'срм', '1с', '1c'],
        answer: 'Да, работала с CRM-системами и 1С.' },
      { keywords: ['план', 'kpi', 'ки пи ай', 'выполнени'],
        answer: 'Да, умею работать по плановым показателям и выполняю их.' },
      { keywords: ['стресс', 'конфликт', 'сложн клиент'],
        answer: 'Стрессоустойчива, умею работать со сложными клиентами и находить компромисс.' },
      { keywords: ['зарплат', 'оклад', 'доход', 'ожидани'],
        answer: 'Оклад от 50 000 + % от продаж.' },
      { keywords: ['когда', 'приступить', 'выйти'],
        answer: 'Готова приступить в течение недели.' },
      { keywords: ['формат', 'офис', 'удалённ'],
        answer: 'Рассматриваю офисный и гибридный форматы.' },
      { keywords: ['английск', 'english'],
        answer: 'Базовый.' },
      { keywords: ['обучени', 'тренинг'],
        answer: 'Да, готова к обучению.' },
    ]
  },
  office: {
    default: 'Готова рассказать подробнее на собеседовании.',
    templates: [
      { keywords: ['командировк'],
        answer: 'Нет, командировки не рассматриваю.' },
      { keywords: ['переработк', 'сверхурочн'],
        answer: 'В исключительных случаях готова.' },
      { keywords: ['вахт'],
        answer: 'Нет.' },
      { keywords: ['почему', 'привлекает', 'хотите'],
        answer: 'Привлекает стабильность, официальное оформление и чёткий функционал.' },
      { keywords: ['опыт работ', 'стаж'],
        answer: 'Есть опыт офисной работы: документооборот, работа с оргтехникой, MS Office, координация задач.' },
      { keywords: ['1с', '1c'],
        answer: 'Да, базовый опыт работы в 1С.' },
      { keywords: ['excel', 'word', 'office', 'офис'],
        answer: 'Уверенный пользователь MS Office: Word, Excel, Outlook.' },
      { keywords: ['оргтехник', 'принтер', 'скан'],
        answer: 'Да, умею работать с оргтехникой.' },
      { keywords: ['документооборот', 'делопроизводств'],
        answer: 'Да, есть опыт ведения документооборота и делопроизводства.' },
      { keywords: ['зарплат', 'оклад', 'доход', 'ожидани'],
        answer: 'От 60 000 рублей.' },
      { keywords: ['когда', 'приступить', 'выйти'],
        answer: 'Готова приступить в течение 2 недель.' },
      { keywords: ['формат', 'офис', 'удалённ'],
        answer: 'Предпочтительно офисный или гибридный формат.' },
      { keywords: ['английск', 'english'],
        answer: 'Базовый.' },
      { keywords: ['автомобил', 'права'],
        answer: 'Нет.' },
      { keywords: ['образован'],
        answer: 'Высшее.' },
    ]
  },
  remote: {
    default: 'Готова рассказать подробнее на собеседовании.',
    templates: [
      { keywords: ['командировк'],
        answer: 'Нет, предпочитаю удалённый формат.' },
      { keywords: ['переработк', 'сверхурочн'],
        answer: 'Да, при необходимости готова.' },
      { keywords: ['вахт'],
        answer: 'Нет.' },
      { keywords: ['почему', 'привлекает', 'хотите'],
        answer: 'Привлекает удалённый формат, интересные задачи и возможность развиваться в IT-сфере.' },
      { keywords: ['опыт работ', 'стаж'],
        answer: 'Есть опыт удалённой работы. Умею самостоятельно организовывать рабочий процесс.' },
      { keywords: ['интернет', 'оборудован', 'компьютер', 'пк'],
        answer: 'Да, есть стабильный интернет и необходимое оборудование.' },
      { keywords: ['часовой пояс', 'мск', 'москов'],
        answer: 'Работаю в часовом поясе МСК+0.' },
      { keywords: ['english', 'английск'],
        answer: 'Pre-Intermediate / Базовый.' },
      { keywords: ['python', 'java', 'sql', 'программирован'],
        answer: 'Да, есть базовые знания. Готова развиваться.' },
      { keywords: ['google', 'таблиц', 'notion', 'jira', 'confluence', 'trello'],
        answer: 'Да, работала с Google-сервисами, Notion, Trello.' },
      { keywords: ['зарплат', 'оклад', 'доход', 'ожидани'],
        answer: 'От 70 000 рублей.' },
      { keywords: ['когда', 'приступить', 'выйти'],
        answer: 'Готова приступить в течение недели.' },
      { keywords: ['формат', 'удалённ', 'гибрид'],
        answer: 'Предпочтительно полностью удалённый или гибридный.' },
      { keywords: ['обучени', 'курс'],
        answer: 'Да, готова к обучению за счёт компании.' },
    ]
  }
};

function qLoadPreset(name) {
  const preset = Q_PRESETS[name];
  if (!preset) return;
  if (!confirm(`Загрузить пресет "${name}"? Текущие шаблоны будут заменены.`)) return;
  qRenderTemplates(preset.templates);
  const defEl = document.getElementById('q-default-answer');
  if (defEl) defEl.value = preset.default;
  const st = document.getElementById('q-status');
  st.textContent = `✅ Пресет загружен (${preset.templates.length} шаблонов). Отредактируй и нажми «Сохранить».`;
  st.style.color = 'var(--yellow)';
  setTimeout(() => { st.textContent = ''; st.style.color = ''; }, 6000);
  document.getElementById('q-templates-list')?.scrollIntoView({behavior:'smooth'});
}

function qAddTemplate() {
  const templates = qReadTemplates();
  templates.push({keywords: [], answer: ''});
  qRenderTemplates(templates);
  // Прокручиваем к новой строке
  document.getElementById('q-templates-list').lastElementChild?.scrollIntoView({behavior:'smooth'});
}

function qDelTemplate(idx) {
  const templates = qReadTemplates();
  templates.splice(idx, 1);
  qRenderTemplates(templates);
}

function qReadTemplates() {
  const rows = document.querySelectorAll('#q-templates-list .q-template-row');
  const result = [];
  rows.forEach(row => {
    const kw = row.querySelector('.q-keywords-input')?.value || '';
    const ans = row.querySelector('.q-answer-input')?.value || '';
    result.push({
      keywords: kw.split(',').map(s => s.trim()).filter(Boolean),
      answer: ans
    });
  });
  return result;
}

function qSave() {
  const templates = qReadTemplates();
  const defaultAnswer = document.getElementById('q-default-answer')?.value || '';
  sendCmd({type: 'set_questionnaire', templates, default_answer: defaultAnswer});
  const st = document.getElementById('q-status');
  st.textContent = `✅ Сохранено ${templates.length} шаблонов`;
  setTimeout(() => { st.textContent = ''; }, 3000);
}

function qSyncFromSnapshot(snap) {
  if (!snap || !snap.config) return;
  const templates = snap.config.questionnaire_templates || [];
  const defaultAns = snap.config.questionnaire_default_answer || '';
  qRenderTemplates(templates);
  const el = document.getElementById('q-default-answer');
  if (el && !el._userEdited) el.value = defaultAns;
}

// Помечаем как изменённое пользователем, чтобы не перезаписать при следующем snapshot
document.addEventListener('DOMContentLoaded', () => {
  const el = document.getElementById('q-default-answer');
  if (el) el.addEventListener('input', () => { el._userEdited = true; });
});

// ── Dark confirm dialog ──────────────────────────────────────────
function showConfirm(msg, okLabel = null, cancelLabel = null) {
  if (okLabel === null) okLabel = t('confirm_delete');
  if (cancelLabel === null) cancelLabel = t('confirm_cancel');
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.innerHTML = `
      <div class="confirm-box">
        <p>${msg}</p>
        <div class="confirm-btns">
          <button class="confirm-cancel">${cancelLabel}</button>
          <button class="confirm-ok">${okLabel}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('.confirm-ok').onclick = () => { document.body.removeChild(overlay); resolve(true); };
    overlay.querySelector('.confirm-cancel').onclick = () => { document.body.removeChild(overlay); resolve(false); };
    overlay.onclick = (e) => { if (e.target === overlay) { document.body.removeChild(overlay); resolve(false); } };
  });
}

// ── Compact card mode ──────────────────────────────────────────
function toggleCompact(idx) {
  if (State.compactCards.has(idx)) State.compactCards.delete(idx);
  else State.compactCards.add(idx);
  const card = document.getElementById('card-' + idx);
  if (!card) return;
  if (State.compactCards.has(idx)) {
    card.classList.add('compact');
    card.querySelector('.compact-btn').textContent = '⬜';
    card.querySelector('.compact-btn').title = 'Развернуть карточку';
  } else {
    card.classList.remove('compact');
    card.querySelector('.compact-btn').textContent = '⬜';
    card.querySelector('.compact-btn').title = 'Свернуть карточку';
  }
}

// ── CSV Export ──────────────────────────────────────────────────
function exportCSV(headers, rows, filename) {
  const lines = [
    headers.map(h => '"' + h.replace(/"/g, '""') + '"').join(','),
    ...rows.map(r => r.map(v => '"' + String(v ?? '').replace(/"/g, '""') + '"').join(','))
  ];
  const blob = new Blob(['\uFEFF' + lines.join('\n')], {type: 'text/csv;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

function exportAppliedCSV() {
  if (!AppliedState.all.length) return;
  const headers = ['Дата', 'Аккаунт', 'ID вакансии', 'Название', 'Компания', 'Зарплата от', 'Зарплата до', 'Ссылка'];
  const rows = AppliedState.all.map(i => [
    i.at ? new Date(i.at).toLocaleString('ru-RU') : '',
    i.account || '',
    i.vacancy_id || '',
    i.title || '',
    i.company || '',
    i.salary_from || '',
    i.salary_to || '',
    i.url || `https://hh.ru/vacancy/${i.vacancy_id}`,
  ]);
  exportCSV(headers, rows, `hh_applied_${new Date().toISOString().slice(0,10)}.csv`);
}

function exportDbCSV() {
  if (!DBState.all.length) return;
  const STATUS_LABELS = {sent: 'Откликнулись', test_passed: 'Тест пройден', test_pending: 'Не пройден'};
  const headers = ['Статус', 'Дата', 'ID вакансии', 'Название', 'Компания', 'Аккаунты', 'Ссылка'];
  const rows = DBState.all.map(i => [
    STATUS_LABELS[i.status] || i.status,
    i.at ? new Date(i.at).toLocaleString('ru-RU') : '',
    i.vacancy_id || '',
    i.title || '',
    i.company || '',
    (i.applied_by || []).join('; '),
    `https://hh.ru/vacancy/${i.vacancy_id}`,
  ]);
  exportCSV(headers, rows, `hh_db_${new Date().toISOString().slice(0,10)}.csv`);
}

// ── Keyboard shortcuts ─────────────────────────────────────────
const TAB_KEYS = {'1':'main','2':'log','3':'applied','4':'tests','5':'db','6':'hh','7':'views','8':'apply','9':'settings'};

document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key in TAB_KEYS) {
    const tabEl = document.querySelector(`.tab[data-tab="${TAB_KEYS[e.key]}"]`);
    if (tabEl) tabEl.click();
    return;
  }
  if (e.key === 'p' || e.key === 'P') { sendCmd({type: 'pause_toggle'}); return; }
  if (e.key === '?' || e.key === '/') { toggleShortcutsHelp(); return; }
  if (e.key === 'Escape') { closeShortcutsHelp(); }
});

function toggleShortcutsHelp() {
  if (document.getElementById('shortcuts-overlay')) { closeShortcutsHelp(); return; }
  const el = document.createElement('div');
  el.id = 'shortcuts-overlay';
  el.className = 'shortcuts-overlay';
  el.innerHTML = `
    <div class="shortcuts-box">
      <h3>${t('shortcuts_title')}</h3>
      <table>
        <tr><td>1–9</td><td>${t('shortcuts_tabs')}</td></tr>
        <tr><td>P</td><td>${t('shortcuts_pause')}</td></tr>
        <tr><td>? / /</td><td>${t('shortcuts_help')}</td></tr>
        <tr><td>Esc</td><td>${t('shortcuts_esc')}</td></tr>
      </table>
      <div style="margin-top:14px;text-align:right">
        <button class="confirm-cancel" onclick="closeShortcutsHelp()">${t('btn_close')}</button>
      </div>
    </div>`;
  el.onclick = e => { if (e.target === el) closeShortcutsHelp(); };
  document.body.appendChild(el);
}
function closeShortcutsHelp() {
  const el = document.getElementById('shortcuts-overlay');
  if (el) el.remove();
}

// ── Init ──────────────────────────────────────────────────────
buildSettings();
connect();
// Устанавливаем системный prompt LLM по умолчанию, если он ещё не настроен
const spEl = document.getElementById('llm-system-prompt');
if (spEl && !spEl.value) spEl.value = 'Ты помощник соискателя работы. Отвечай вежливо и кратко (2-4 предложения) на сообщения от HR и работодателей. Пиши от первого лица, женский род. Соглашайся на предложенное время собеседования или уточни детали.';
document.getElementById('lang-btn').textContent = lang.toUpperCase();
// Восстанавливаем последнюю активную вкладку из localStorage
try {
  const savedTab = localStorage.getItem('hh-tab');
  if (savedTab) {
    const tabEl = document.querySelector(`.tab[data-tab="${savedTab}"]`);
    if (tabEl) tabEl.click();
  }
} catch(e) {}
// Запрашиваем разрешение на уведомления браузера
if ('Notification' in window && Notification.permission === 'default') {
  setTimeout(() => Notification.requestPermission(), 3000);
}

// Автозагружаем JSON-редакторы при первом открытии
document.getElementById('json-config-details').addEventListener('toggle', function() {
  if (this.open && !document.getElementById('json-config-ta').value.trim())
    jsonConfigLoad(this.querySelector('button'));
});
document.getElementById('json-accounts-details').addEventListener('toggle', function() {
  if (this.open && !document.getElementById('json-accounts-ta').value.trim())
    jsonAccountsLoad(this.querySelector('button'));
});
