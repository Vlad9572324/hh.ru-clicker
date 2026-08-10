# Changelog

Все значимые изменения проекта **hh.ru-clicker** документируются в этом файле.
Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/).

**Схема версионирования:** git-тегов в репозитории нет, поэтому выпуски именуются по
PR/ветке, слитой в `main`; baseline (состояние «до») — `origin/main` (`b3bba5a`, 2026-08-07).
Commit-хэши указаны в скобках.

## [Unreleased] — ветка `feat/phase2-chats-mobile` (в разработке, не закоммичено)

**Phase 2 миграции mobile-API: переговоры/чаты через `api.hh.ru` + auto-fallback.**
Реализованы 10 из 11 mobile-методов группы A (переговоры/чат) и прозрачный
fallback mobile→web при сбоях авторизации/сервера.

### Added

- Общий транспорт mobile-вызовов `app/hh_mobile_transport.py`: Bearer через
  `app.oauth._obtain_oauth_token`, заголовки `ru.hh.android/26.28.1` +
  `x-force-app-access`, единая обработка ошибок (`MobileAPIError`,
  `is_fallback_status` — 0/401/403/5xx).
- Mobile-модули группы A (`app/mobile_*.py`): `mobile_chat_list`
  (`GET /chats`), `mobile_chat_thread` (`GET /chats/{id}`, `fetch_thread` +
  `fetch_chat_history`), `mobile_send_message` (`POST /chats/{id}/messages`,
  idempotency_key), `mobile_chat_actions` (`PUT` quick_replies /
  last_viewed_id / participants/action), `mobile_negotiations`
  (`GET /negotiations`, пагинация), `mobile_neg_meta`
  (`fetch_negotiations_metadata` + `GET /vacancies/possible_job_offers`).
- `app/hh_client_fallback.py` — `FallbackHHClient`: обёртка mobile→web,
  повторяет вызов через `WebHHClient` при fallback-статусах или
  `NotImplementedError` (полный контракт HHClient, sync+async).
- Тесты: `tests/test_hh_mobile_transport.py`, `tests/test_mobile_*.py`
  (по модулям), `tests/test_hh_client_fallback.py`,
  `tests/test_mobile_phase2_integration.py` — все через `responses`,
  без живого HTTP; покрытие новых модулей ≥ 86%.

### Changed

- `app/hh_client_mobile.py`: методы группы A (кроме `auto_decline_discards`)
  делегируют в `app/mobile_*.py` вместо `NotImplementedError`.
- `app/hh_client_factory.py`: `mode="mobile"` возвращает
  `FallbackHHClient(MobileHHClient, WebHHClient)` вместо голого
  `MobileHHClient`; `auto`/`web` без изменений.
- Обновлены `docs/PHASE_MATRIX.md` (матрица, фабрика, roadmap) и тесты
  фабрики/регрессии под новую семантику mobile.

## [Unreleased] — ветка `refactor/mobile-api` (Phase 0)

**Phase 0 рефакторинга mobile-API: абстракция HHClient.** Цель — единая точка доступа
к hh.ru для обоих потоков (web-flow на cookies и mobile-flow на OAuth Bearer) по принципу
«один клиент — один аккаунт». Phase 0 добавляет ТОЛЬКО абстракцию, без миграции боевой
логики на неё.

### Added

- Абстрактный интерфейс `HHClient` (`app/hh_client.py`) — 37 методов в 7 группах:
  переговоры/чат, предложения/работодатели, отклики, резюме, аккаунт и read-endpoint'ы
  официального API. Не путать с одноимённым транспортным классом в `app/hh_http.py`.
- `app/hh_client_web.py` — `WebHHClient`: тонкий адаптер к существующим web-flow
  функциям (`hh_chat`, `hh_apply`, `hh_negotiations`, `hh_resume`, `oauth`), ноль новой логики.
- `app/hh_client_mobile.py` — `MobileHHClient`: mobile-flow через OAuth Bearer `api.hh.ru`;
  реально реализован только `fetch_counters()`, остальные методы — заглушки
  (`NotImplementedError`, «phase N: TODO») до последующих фаз.
- `app/hh_client_factory.py` — `get_client(account)`: выбор реализации по полю `mode`
  аккаунта; неизвестный `mode` трактуется как `web`.
- `tests/test_hh_client_abstraction.py` — тесты абстракции и фабрики.

### Changed

- `app/config.py`: новая настройка `default_client_mode` (`web` | `mobile` | `auto`,
  по умолчанию `auto`) с валидацией при загрузке; задокументирована схема данных:
  аккаунты в `data/accounts.json` и temp-сессии в `data/browser_sessions.json` принимают
  опциональное поле `mode` (сохраняется на диск автоматически). Семантика: `auto` —
  mobile-клиент, если для `resume_hash` есть живой OAuth-токен, иначе web.
- `app/routes/debug.py`: `/api/debug/neg_ids/{idx}` получает negotiations через
  HHClient-фабрику вместо прямого запроса с cookies (web-реализация делегирует в
  `hh_negotiations.fetch_hh_negotiations_stats`).

## [pr20] - 2026-08-10

Мобильная авторизация и унификация Android-идентичности: OTP-вход штатным потоком
Android-клиента HH, импорт OAuth-токенов и браузерных сессий, единый APK-совместимый
User-Agent во всех контурах, перевод статуса/поднятия резюме на Android-endpoint'ы.
13 коммитов поверх baseline `b3bba5a`.

### Added

- **Мобильная OTP-авторизация** (076d238): `app/mobile_auth.py` — двухэтапный OTP-поток
  Android-клиента (запрос SMS/письма → подтверждение кодом) и редактируемая мобильная
  идентичность (пакет и версия приложения, модель устройства, Android release, стабильный
  UUID, шаблон User-Agent, OAuth client credentials; приоритет источников web → env →
  file → default, секреты маскируются в API/UI). Маршруты `/api/mobile-auth/*`
  (`app/routes/mobile_auth.py`): настройки, request-code, verify; форма в web-UI;
  документация в README.
- **Импорт мобильных OAuth-токенов** (076d238): после OTP-входа токены атомарно
  записываются в существующий `data/oauth_tokens.json` для найденных резюме; logout
  мобильного аккаунта сохраняет токены остальных аккаунтов. Браузерные сессии создаются
  через штатный Android autologin-мост (`hhtoken`/`hhuid`/`_xsrf`) с запретом переходов
  на внешние домены.
- **Единый User-Agent модуль** (88ed641): новый `app/user_agent.py` —
  `mobile_user_agent()` (APK-совместимый Android UA из редактируемых настроек, с
  ASCII-фильтрацией как в APK) и `webview_user_agent()` (идентичность WebView:
  desktop-браузер + Android UA, аналог `UserAgentGenerator.a()` из APK); страховочный
  автоинжект Android UA в транспортной обёртке `HH` для любых запросов к hh.ru/hh.kz
  без явно заданного User-Agent.
- **Статус резюме через Android-endpoint** (5a2312d): `fetch_resume_status` читает
  резюме из `GET /resumes/{id}?with_professional_roles&with_creds` (endpoint Android-
  приложения) вместо `/resumes/{rh}/status`; в ответе появились `can_publish_or_update`
  и `next_publish_at`; толерантный парсинг `status`/`progress`/`moderation_note`
  (dict и не-dict варианты).
- **OAuth-fallback публикуемости резюме** (c38c29a): если legacy SSR перестаёт отдавать
  `applicantResumes[].toUpdate`, доступность поднятия берётся из Android-статуса
  (`can_publish_or_update` / `next_publish_at`) — `fetch_resume_stats` дополняется
  этими данными.
- **Серверное время следующей публикации** (5f0da7b): helper
  `_server_next_publish_datetime` — конвертация `next_publish_at` от HH в локальный
  naive-datetime, используемый планировщиком.
- Логгирование обработки вакансий в менеджере: `Processing vacancy {vid}: {title}` (8ff71f3).
- Покрытие тестами: `test_mobile_auth`, `test_mobile_auth_routes`,
  `test_mobile_oauth_import`, `test_oauth_apply_403`, `test_user_agent`,
  `test_oauth_resume_status`, `test_resume_publishability`, `test_resume_touch_schedule`
  (076d238, 88ed641, 5a2312d, c38c29a, 5f0da7b, decaeaf, 890a98d, 1155390).

### Changed

- **Все OAuth-операции представляются Android-приложением** (52fde70): получение и
  refresh токенов, проактивный refresh, OAuth-заголовки и отклики через API отправляют
  настраиваемый Android UA вместо захардкоженных Chrome UA / `hh-clicker/1.0`
  (раньше мобильные credentials использовались только для токенов из OTP-входа).
- Все HH-модули (`hh_api`, `hh_apply`, `hh_chat`, `hh_negotiations`, `hh_resume`,
  `manager`, `oauth`, routes) переведены на общие функции User-Agent из
  `app/user_agent.py` вместо локальных захардкоженных строк (88ed641).
- **Планирование поднятия резюме по серверу** (5f0da7b, c38c29a): перед publish менеджер
  принудительно сверяется с сервером (force-запрос, минуя 5-минутный кэш) и не шлёт
  publish без разрешения HH (сетевая ошибка статуса больше не ведёт к 429); следующее
  время поднятия берётся из серверного `next_publish_at` вместо захардкоженных +4 часов;
  если HH снова сообщил о доступности — автоподъём стартует немедленно, не дожидаясь
  старого расписания; после успешного поднятия устаревшее «1 поднятие доступно»
  скрывается до следующего ответа HH.
- Сохранённые поиски, избранное и чёрный список вакансий запрашиваются по 10 штук на
  страницу вместо 50 (4bfe569).
- UI: улучшена обратная связь при активации сессии — состояние кнопки «⏳ Запуск…»,
  обновление списка по fingerprint (а не count), показ конкретной причины ошибки
  (`message`/`error`/`detail`/HTTP-статус) и восстановление кнопки при неудаче (17d814a).
- Удалён устаревший `requirements-tui.txt`; `apks/` добавлен в `.gitignore` (076d238).

### Fixed

Четыре блокера, найденные в review пр-20:

- **Блокер 1 — event loop** (decaeaf): синхронные запросы к HH в маршрутах mobile-auth
  вынесены в `run_in_threadpool` — request-code/verify больше не блокируют event loop
  FastAPI; verify-поток усилен (материализация настроек даже при дефолтных значениях,
  понятная ошибка при неудачной записи токенов).
- **Блокер 2 — chatik** (41656cc): чаты переведены с чистого Android UA на
  `webview_user_agent()` во всех запросах (cookies, список чатов, история, quick replies,
  действия, mark_read, отправка сообщений, WS) — chatik это web-продукт и требует
  WebView-идентичность.
- **Блокер 3 — кэш настроек** (890a98d): `effective_config()` и `mobile_user_agent()`
  закэшированы (`lru_cache`) с инвалидацией при сохранении/сбросе настроек — раньше
  файлы конфигурации читались с диска на каждый HTTP-запрос.
- **Блокер 4 — тихая потеря токенов** (1155390): `_save_oauth_tokens` возвращает успех
  записи, и `import_mobile_tokens` теперь падает с `MobileAuthError`, если
  `oauth_tokens.json` не удалось сохранить на диск, — раньше ошибка молча проглатывалась.
