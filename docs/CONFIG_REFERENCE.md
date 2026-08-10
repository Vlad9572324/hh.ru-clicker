# CONFIG_REFERENCE — полный справочник конфигурации

> Scope: `app/config.py` (класс `Config`), файл данных `data/config.json`.
> Ветвь `refactor/mobile-api`, состояние включает uncommitted Phase 0
> (поле `default_client_mode` + docstring-схема поля `mode`).
> Все дефолты/типы взяты из class-атрибутов `Config`, поведение — из grep по usage.

---

## 1. Где живёт конфигурация и как редактируется

**In-memory:** singleton `CONFIG = Config()` (`app/config.py`). Все поля — class-атрибуты,
mutable в runtime (без рестарта).

**На диске:** `data/config.json` (chmod 0600 — внутри могут быть `llm_api_key` и PII
в `letter_templates`). Запись: `save_config()` — атомарный write+rename через
`.tmp`, сериализуется под `_config_write_lock`, исполняется в фоне через
`app.storage._schedule_save` (fallback — daemon-thread).

**Что персистится:** `save_config()` пишет `data = {k: getattr(CONFIG, k) for k in _CONFIG_KEYS}`
плюс явные дописи остальных полей (templates, lists, llm_*). **Инвариант: поле,
которого нет ни в `_CONFIG_KEYS`, ни в явных дописях `save_config()`, на диск
не попадает.** Сейчас все 56 полей класса покрыты (37 через `_CONFIG_KEYS`,
остальные — явными строками в `save_config()`).

**Загрузка:** `load_config()` при старте (`Bot.start`, `app/manager.py:327`).
Для ключей `_CONFIG_KEYS` — коэрсия `type(old_val)(data[k])` (невалидное значение
пропускается с warning в debug-log); для list/str/bool-полей — отдельные
`isinstance`-проверки. Спецвалидация при загрузке: `default_client_mode`
приводится к lower/strip и вне `{web, mobile, auto}` сбрасывается в `"auto"`.
Миграция: если `llm_profiles` пуст, но задан legacy `llm_api_key` — создаётся
один профиль `{"name": "Основной", ...}`.

**Способы редактирования:**

| Способ | Механизм |
|---|---|
| UI дашборда (один ключ) | `POST /api/settings` `{key, value}` (`app/routes/settings.py:60`) — принимает только ключи из `_CONFIG_KEYS`, строгий `_safe_cast` к типу текущего значения (bool/int/float/str/list/dict), затем `save_config()`. Этим же путём идут smart-filter контролы UI и websocket/командный путь `set_config` в `app/routes/core.py:~150` |
| UI дашборда (bulk raw-editor) | `GET /api/raw/config` / `POST /api/raw/config` (`app/routes/settings.py:91,102`) — принимает `_CONFIG_KEYS` + списки (`url_pool`, `allowed_schedules`, `title_*_keywords`, `questionnaire_templates`, `letter_templates`, `llm_profiles`) + все `llm_*`-ключи. Защита: пустой list/string не затирает непустое текущее значение без `?force=1` (anti-stale-state) |
| Backup/restore | `GET/POST /api/backup` (`app/routes/settings.py`) — бандл `config.json` + `accounts.json` + `browser_sessions.json` + `oauth_tokens.json`; restore делает live-reload `load_config()`/`load_accounts()` |
| Напрямую в файле | Правка `data/config.json` при остановленном приложении (при работе — будет перезаписан фоновым `save_config()` на любое изменение) |

---

## 2. Env overrides

Env-переменные в проекте **есть**, но полноценный override поверх Config-полей
только один:

| Env | Отношение к Config | Где |
|---|---|---|
| `HH_PROXY` | **Override для `hh_proxy_url`**: `app/hh_http.py:42` читает env при импорте; `Bot.start` (`app/manager.py:~334`) применяет сохранённый `CONFIG.hh_proxy_url` через `set_proxy()` только если env пуст. Env всегда приоритет (docker-compose override) | `app/hh_http.py`, `app/manager.py` |

Остальные env-переменные не имеют Config-аналога (конфигурируются только через env):

| Env | Default | Назначение |
|---|---|---|
| `LLM_PROXY` | `""` | Прокси для исходящих LLM-запросов (`app/llm.py:120`, `app/routes/llm.py:26`). Config-поля для него нет |
| `HH_IMPERSONATE` | `chrome124` | curl_cffi impersonate-профиль для fingerprint HH (`app/hh_http.py:37`) |
| `HH_CHATIK_BASE` | `https://chatik.hh.ru` | Base URL reverse-engineered chatik API (`app/hh_chat.py:21`) |
| `HH_OAUTH_CLIENT_ID` / `HH_OAUTH_CLIENT_SECRET` | Встроенные креды из публичного APK HH | OAuth-приложение для mobile-токенов (`app/oauth.py:22-29`) |
| `HH_OAUTH_CLIENT_ID_2` / `HH_OAUTH_CLIENT_SECRET_2` | `""` | Второй OAuth client (fallback) (`app/oauth.py:31-32`) |
| `HH_BOT_API_KEY` | `""` (auth выключен) | X-API-Key защита не-GET эндпоинтов дашборда (`app/routes/__init__.py:85`, `core.py:107`) |
| `HH_BOT_ALLOWED_ORIGINS` | `""` | Доп. CORS origins (`app/routes/core.py:65`) |

**Вывод:** вся пользовательская конфигурация — только через `data/config.json` /
UI-эндпоинты; env — инфраструктурные настройки (прокси, OAuth-креды, auth дашборда).

---

## 3. Reference всех полей Config (56)

Формат: `default` → поведение + основной consumer. «state.» = per-account
`AccountState` (`app/state.py`), «manager» = `app/manager.py` (воркеры циклов).

### 3.1 Режим клиента (Phase 0)

| Поле | Тип | Default | Описание |
|---|---|---|---|
| `default_client_mode` | str | `"auto"` | Режим HH-клиента по умолчанию для аккаунтов/temp-сессий **без** поля `mode`. Подробно — [§4](#4-default_client_mode-и-поле-mode-аккаунта) |

### 3.2 Цикл работы, тайминги, лимиты

| Поле | Тип | Default | Описание / где используется |
|---|---|---|---|
| `pages_per_url` | int | `40` | Страниц поиска на URL при сборе (20 вакансий/стр). Дефолт для новых записей `url_pool` и per-account `url_pages` fallback (`manager:202,1973,2058`) |
| `max_concurrent` | int | `20` | База семафора параллельного сбора: реально `asyncio.Semaphore(CONFIG.max_concurrent * 3)` (`manager:2035-2040`) — т.е. фактическая конкурентность ×3 |
| `response_delay` | int | `1` | Секунд сна между откликами (`time.sleep` в apply-цикле, `manager:1586-1587,1842`) |
| `pause_between_cycles` | int | `60` | Секунд паузы между циклами сбора аккаунта (`manager:1859-1862`, wait на `_stop_event`) |
| `limit_check_interval` | int | `30` | Минут до повторной проверки после HH-лимита: `state.limit_reset_time = now + N мин` (`manager:1100,1711,1771`) |
| `resume_touch_interval` | int | `4` | ⚠️ **Dead field**: персистится, но backend его не читает — интервал авто-поднятия резюме захардкожен `timedelta(hours=4)` в `manager:1063,1071`. Совпадение дефолта 4 с хардкодом — случайное, код поле не читает |
| `batch_responses` | int | `3` | Размер пакета откликов в apply-фазе (`manager:1479`) |
| `daily_apply_limit` | int | `0` | Жёсткий дневной лимит откликов бота (0 = без лимита). По достижении — пауза до 00:00, `paused_reason="limit"` (`manager:1505-1509`) |
| `auto_pause_errors` | int | `5` | Авто-пауза аккаунта после N ошибок подряд (0 = выкл), `paused_reason="auto_errors"` (`manager:_check_auto_pause:534-545`) |
| `stop_on_hh_limit` | bool | `True` | При HH-лимите (429-путь): True = полная остановка аккаунта без перепроверок; False = периодическая перепроверка (`manager:1754`) |
| `hh_daily_limit` | int | `200` | Порог pre-flight по фактическому счётчику HH (откликов на резюме в день). ⚠️ Неочевидно: в коде везде `CONFIG.hh_daily_limit or 200` (`manager:708,1514`) — **0 не выключает, а откатывает к 200**, несмотря на инлайн-комментарий «0 = выкл». При `state.hh_today_applies >= порога` — hard-stop до 00:00 МСК |

### 3.3 Фильтры вакансий (сбор)

| Поле | Тип | Default | Описание / где используется |
|---|---|---|---|
| `min_salary` | int | `0` | Мин. зарплата, руб (0 = без фильтра). Вакансии без зарплаты (`sal is None`) фильтруются при `>0` (`manager:1375-1384`) |
| `allowed_schedules` | list[str] | `[]` | Форматы работы: `"fullDay"`, `"remote"`, `"flexible"`, `"shift"`, `"flyInFlyOut"`. Пустой список = все форматы. Сравнение через set-intersection (`manager:1371-1373`) |
| `title_include_keywords` | list[str] | `[]` | Whitelist заголовков (пустой = все). Регистронезависимое вхождение подстроки (`manager:1287-1303`) |
| `title_exclude_keywords` | list[str] | `[]` | Blacklist заголовков, та же механика; exclude проверяется после include (`manager:1292-1306`) |
| `skip_inconsistent` | bool | `False` | Pre-check каждой вакансии перед откликом через `_check_vacancy_before_apply` — пропуск при несовпадении опыта (`manager:1526-1530`) |
| `filter_agencies` | bool | `False` | Добавляет `&label=not_from_agency` к поисковому URL. ⚠️ Взаимоисключающий с `filter_low_competition` — `elif`: при обоих True побеждает low-competition (`manager:2051-2054`) |
| `filter_low_competition` | bool | `False` | Добавляет `&label=low_performance` (вакансии с малым числом откликов, server-side фильтр HH) (`manager:2051-2052`) |
| `search_period_days` | int | `0` | 0 = все время; 1-30 → `&search_period=N` в поисковом URL (`manager:2055-2056`) |

### 3.4 Employer rating и quality gates

| Поле | Тип | Default | Описание / где используется |
|---|---|---|---|
| `min_employer_rating` | float | `0.0` | 0.0 = выкл. Рейтинг работодателя через `fetch_employer_rating` (OAuth `/employers/{eid}/reviews`); применяется только если в meta есть `employer_id`. Работодатели с `reviews_count < min_employer_reviews` не блокируются (`manager:1347-1361`) |
| `min_employer_reviews` | int | `3` | Мин. число отзывов, с которого включается rating-фильтр |
| `min_recommendations_percent` | int | `0` | 0 = выкл; мин. % «рекомендую работодателя» (`manager:1358-1361`) |
| `skip_auto_response_vacancies` | bool | `False` | Lazy-enrichment через OAuth `GET /vacancies/{vid}`: пропуск вакансий с `auto_response=true` (массовые auto-feed). Enrichment запускается только если включён хотя бы один из трёх флагов этого блока (`manager:1327-1340`) |
| `prefer_quick_responses` | bool | `False` | Вакансии с `quick_responses_allowed=true` приоритизируются в начало очереди (`manager:1401`) |
| `accredited_it_only` | bool | `False` | Пропуск вакансий где `accredited_it_employer=false` (`manager:1343`) |

### 3.5 LLM: провайдеры и промпты

| Поле | Тип | Default | Описание / где используется |
|---|---|---|---|
| `llm_enabled` | bool | `False` | Глобальный master-switch автоответов в чатах. Работает в AND с per-account `state.llm_enabled` (`manager:306`) |
| `llm_auto_send` | bool | `False` | True = LLM-ответ реально отправляется; False = только логирование черновика |
| `llm_use_cover_letter` | bool | `True` | Включать `acc["letter"]` в контекст LLM (`manager:2376`) |
| `llm_use_resume` | bool | `True` | Включать текст резюме в системный промпт (`manager:2378`) |
| `llm_use_quick_replies` | bool | `True` | ⚠️ Реальное поведение отличается от инлайн-комментария: HH quick_replies используются **только когда своего LLM нет** (`_has_own_llm` = api_key/профили/openclaw), как замена, с ranking-эвристикой; при наличии LLM он всегда первый (`manager:2495-2520`) |
| `llm_api_key` | str | `""` | Legacy одиночный ключ. Используется только как fallback когда нет ни одного enabled-профиля с ключом (`app/llm.py:326-331`); при загрузке мигрирует в `llm_profiles` |
| `llm_base_url` | str | `https://api.openai.com/v1` | OpenAI-compatible endpoint (legacy fallback / дефолт миграции профиля) |
| `llm_model` | str | `gpt-4o-mini` | Модель legacy fallback; снапшотится в UI-статус (`manager:931`) |
| `llm_applicant_gender` | str | `"female"` | Грамматический род ответов. `applicant_gender_forms()` (`app/config.py`) принимает алиасы: male/m/masculine/мужской; neutral/n/неважно/нейтральный; остальное = female. Влияет на instruction в промпте, тексты «готов(а)» и дефолтный ответ опросника |
| `llm_profiles` | list | `[]` (class-атрибут `None`, инициализируется `CONFIG.llm_profiles = []` после класса) | Список `{name, api_key, base_url, model, enabled}` — мультипровайдерность (`app/llm.py`) |
| `llm_profile_mode` | str | `"fallback"` | `"fallback"` = профили по очереди до первого успеха; `"roundrobin"` = ротация с fallthrough на ошибках (`app/llm.py:381-449`) |
| `llm_openclaw_enabled` | bool | `False` | Включает локальный CLI-agent backend (subprocess `openclaw`). ⚠️ Проверяется **раньше** профилей: при enabled ответ идёт только через openclaw (`app/llm.py:373-374,588`) |
| `llm_openclaw_agent` | str | `"main"` | Имя агента для openclaw-команды |
| `llm_openclaw_model` | str | `""` | Модель, передаваемая в openclaw (пусто = дефолт CLI) |
| `llm_openclaw_timeout` | int | `120` | Таймаут subprocess, сек |
| `llm_system_prompt` | str | см. ниже | Базовый системный промпт автоответов. Дефолт: «Ты помощник соискателя работы. Отвечай вежливо и кратко (2-4 предложения) на сообщения от HR и работодателей. Пиши от первого лица. Соглашайся на предложенное время собеседования или уточни детали. Не используй слишком формальный язык.» |
| `llm_check_interval` | int | `5` | Период проверки чатов/статусов LLM, минуты. Эффективный минимум 2 мин: сервер `max(N*60, 120)` (`manager:2771,2831`), UI `Math.max(cfg, 2)` |
| `llm_ws_push_enabled` | bool | `True` | Push-триггер от wss://websocket.hh.ru: мгновенная внеплановая проверка чата при событии (rate-limit 10с/аккаунт) (`manager:289-294`) |
| `llm_fill_questionnaire` | bool | `False` | Использовать LLM для заполнения опросников при отклике (`app/hh_apply.py`, `manager`) |

### 3.6 Отклики: OAuth, тесты, письма

| Поле | Тип | Default | Описание / где используется |
|---|---|---|---|
| `use_oauth_apply` | bool | `False` | Глобально применять через OAuth API вместо web-cookies. OR-комбинируется с per-account `state.use_oauth`; `state.degraded_mode` форсирует OAuth независимо от флагов (`manager:1577,1785,2083`) |
| `auto_apply_tests` | bool | `False` | Автопрохождение опросников при отклике. OR с per-account `state.apply_tests` (`manager:1286,1674`) |
| `hh_ai_letter_first_try` | bool | `True` | Перед шаблоном пробовать HH-Pro AI письмо `POST /shards/hhpro_ai_letter` — 1 бесплатное на пару (resumeHash, vacancyId) даже без подписки (`app/hh_apply.py:259-263`) |
| `related_vacancies_enabled` | bool | `True` | Раз в цикл сбора: `GET /shards/vacancy/related_vacancies?vacancyId=<seed>` (seed = последняя applied аккаунта) — рекомендательный фид HH (`manager:1193-1196`) |
| `chat_use_oauth` | bool | `False` | Отправка в чатах: сначала официальный `POST api.hh.ru/.../messages` (Bearer, `is_automated: true`), fallback на reverse-engineered chatik. ⚠️ При мёртвых cookies (нет `hhtoken`) OAuth-путь пробуется независимо от флага (`app/hh_chat.py:437-457`) |

### 3.7 Опросники

| Поле | Тип | Default | Описание / где используется |
|---|---|---|---|
| `questionnaire_templates` | list | `[]` | `[{keywords: [...], answer: "..."}]`. Матчинг: первый шаблон, чьё keyword встретился в тексте вопроса (lower, substring) (`app/questionnaire.py:14-22`) |
| `questionnaire_default_answer` | str | `"Готова рассказать подробнее на собеседовании."` | ⚠️ Неочевидно: если значение совпадает со встроенным дефолтом, `questionnaire_default_answer()` возвращает **гендер-адаптивную** форму («Готов…»/«Готов(а)…» по `llm_applicant_gender`); кастомное значение используется как есть |

### 3.8 Сеть, регион, пулы и шаблоны

| Поле | Тип | Default | Описание / где используется |
|---|---|---|---|
| `hh_proxy_url` | str | `""` | Прокси к hh.ru (`socks5h://…` / `http://user:pass@host:port`), обход DDoS-Guard soft-ban. Env `HH_PROXY` приоритетнее (§2). Применяется в `Bot.start` через `hh_http.set_proxy()` |
| `hh_region` | str | `""` | Региональный поддомен: `"syktyvkar"` → `https://syktyvkar.hh.ru` через `hh_base()`/`hh_url()` (апплай/поиск/резюме). Валидация `^[a-z0-9][a-z0-9-]{0,40}$` (anti-SSRF). OAuth и chatik всегда основной домен (`app/config.py:hh_base`) |
| `url_pool` | list | `[]` | Глобальный пул поисковых URL: элементы `{url, pages}` либо plain-строки (legacy, нормализуются `_url_entry()` с `pages=pages_per_url`). Используется когда у аккаунта нет своих `urls` (`manager:1119`); resume-URL аккаунта авто-добавляется в пул. Кэш `_url_pages_map` инвалидируется в `save_config()` |
| `letter_templates` | list | 1 шаблон «Стандартное» | `[{name, text}]` шаблоны сопроводительных писем; плейсхолдеры `[ИМЯ]`, `[t.me: @username]`, `[📞 телефон]`. Выдаются в снапшот UI и в apply-путь (`manager:917`) |

---

## 4. `default_client_mode` и поле `mode` аккаунта

Цель рефакторинга mobile-API. Единственная точка выбора реализации клиента —
`app/hh_client_factory.py::get_client(account: dict) -> HHClient`
(`app/hh_client.py` — ABC доменного клиента; не путать с `app.hh_http.HHClient` —
это низкоуровневая транспортная обёртка).

### Разрешение режима (код factory)

```python
mode = (account.get("mode") or getattr(CONFIG, "default_client_mode", "auto") or "auto").strip().lower()
```

**Приоритет: `account["mode"]` > `CONFIG.default_client_mode` > `"auto"`** (falsy-fallback
по цепочке). Пустая строка в `mode` аккаунта трактуется как отсутствие поля.
Неизвестное значение mode (опечатка и т.п.) трактуется как `"web"` (fallthrough).

### Семантика значений

| Значение | Реализация | Поведение |
|---|---|---|
| `"web"` | `WebHHClient` (`app/hh_client_web.py`) | Cookies hh.ru, существующий web-flow |
| `"mobile"` | `MobileHHClient` (`app/hh_client_mobile.py`) | OAuth Bearer через api.hh.ru |
| `"auto"` (дефолт) | dynamic | `MobileHHClient`, если для `resume_hash` аккаунта есть **живой** OAuth-токен: `app.oauth.get_oauth_status(resume_hash)["has_token"]` (= `expires_at > now`, поиск по ключу `resume_hash` или composite `resume_hash::<account_key>`); иначе `WebHHClient` |

### Валидация при загрузке

`load_config()`: `str(data["default_client_mode"]).strip().lower()`; значения вне
`{web, mobile, auto}` → `"auto"`. Поле в `_CONFIG_KEYS` → редактируется через
`POST /api/settings` (`_safe_cast` к str) и raw-editor.

### Где применяется

`get_client()` принимает любой account-подобный dict — различий между основным
аккаунтом и temp-сессией нет. Также используется в debug-эндпоинте
(`app/routes/debug.py:159,179` — показывает `acc.get("mode", "")` и выбранный клиент).

---

## 5. Связанные данные: accounts.json и browser_sessions.json

### `data/accounts.json` — основные аккаунты

`load_accounts()`/`save_accounts()` в `app/config.py` (модуль-level `accounts_data: list`).
Запись: отбрасываются **только** ключи с префиксом `_` (runtime-объекты вроде
`_cookies_lock`) — всё остальное, включая `mode`, персистится как есть (chmod 0600).

Структура аккаунта (создание: `app/routes/accounts.py:431-440`):

| Поле | Назначение |
|---|---|
| `name`, `short`, `color` | Отображение в UI (`short` уникален) |
| `resume_hash` | **Ключ для всего**: OAuth-токены в `data/oauth_tokens.json` привязаны к нему; им определяется auto/mobile-режим в `"auto"` |
| `cookies` | Только auth-cookie (`_AUTH_COOKIE_KEYS`: `hhtoken`, `_xsrf`, …) |
| `letter` | Сопроводительное письмо аккаунта (контекст LLM, дефолт для новых temp-сессий с тем же resume_hash) |
| `urls`, `url_pages` | Per-account поисковые URL и pages-override (приоритет над `url_pool`/`pages_per_url`) |
| `use_oauth` | Per-account OAuth toggle для откликов (OR с `use_oauth_apply`) |
| `apply_tests` | Per-account автопрохождение тестов (OR с `auto_apply_tests`) |
| **`mode`** | **Optional, Phase 0**: `"web"`\|`"mobile"`\|`"auto"`; отсутствует → `default_client_mode`. Сохраняется автоматически (нет `_`-префикса) |

### `data/browser_sessions.json` — temp-сессии

`load_browser_sessions()`/`save_browser_sessions()` в `app/storage.py`
(in-memory `bot.temp_sessions`). Запись: `deepcopy` + удаление только
`_raw_cookie_line`/`raw_cookie_line` — поле `mode` персистится автоматически.

Структура (создание: `app/routes/sessions.py:210-224`): тот же account-подобный
формат — `name` (суффикс 🌐), `short`, `color:"yellow"`, `resume_hash`,
`all_resumes`, `letter`, `cookies` (auth-only), `urls: []`, `_raw_cookie_line`
(in-memory only). Дубли по паре (resume_hash, hhtoken) отклоняются.
PATCH `/api/session/{idx}` обновляет `letter` (и другие поля) с live-sync в
`bot.temp_states`. **Поле `mode` принимается с той же семантикой, что и у
аккаунтов** — `get_client()` не различает типы dict'ов.

### `data/oauth_tokens.json` (смежный)

`{resume_hash | resume_hash::account_key: {access_token, refresh_token, expires_at}}`
(`app/oauth.py`). Именно `expires_at` определяет `has_token` в auto-режиме.
Входит в backup-бандл наравне с config/accounts/sessions.
