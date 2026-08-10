# HH Bot Dashboard

[![Theme: autoclicker](https://img.shields.io/badge/UI-autoclicker_neon-00f0ff?style=flat-square)](static/css/theme-autoclicker.css)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-39d0d8?style=flat-square&logo=python&logoColor=white)](https://www.python.org)
[![Tests](https://img.shields.io/badge/tests-161_passed-3fb950?style=flat-square)](tests/)
[![Docker](https://img.shields.io/badge/docker-python_3.11--slim-0db7ed?style=flat-square&logo=docker&logoColor=white)](Dockerfile)
[![HH clients](https://img.shields.io/badge/clients-web_%2B_mobile-b967ff?style=flat-square)](app/hh_client_factory.py)

Веб-дашборд для автоматизации hh.ru: массовые отклики, мгновенные LLM-ответы
HR через **WebSocket push** (websocket.hh.ru), заполнение опросников
нейросетью, аудит резюме с конкурентным анализом, рейтинги работодателей с
politeness-индексом + онлайн-статусом HR, smart-фильтрация уже отклонённых
вакансий, OAuth-совместимый канал отправки.

Cyberpunk-интерфейс с моноширинным шрифтом, сканлайнами и неоновыми
HUD-карточками. Реалтайм через WebSocket (300мс tick).

---

## Что нового в refactor/mobile-api

Бот теперь умеет общаться с hh.ru **двумя каналами**: классический
web-flow (cookies hh.ru + `chatik.hh.ru`) и новый **mobile API**
(OAuth Bearer `api.hh.ru`). Что изменилось в ветке `refactor/mobile-api`:

- **Mobile OTP-аутентификация по SMS** — аккаунт подключается через
  официальный мобильный OAuth-флоу (код из SMS), без вытаскивания cookies
  из браузера.
- **Мобильные User-Agent'ы + Android resume endpoint** — запросы в
  OAuth-канале идут с мобильными заголовками, статус резюме читается через
  Android-endpoint.
- **OAuth publishability** — управление видимостью резюме через official API.
- **Phase-0 абстракция `HHClient`** — единый интерфейс клиента
  (`app/hh_client.py`) с двумя реализациями: `WebHHClient` (адаптер поверх
  существующего web-flow) и `MobileHHClient` (OAuth Bearer); выбор —
  `app/hh_client_factory.py::get_client()`.
- **Поле `mode` у аккаунта + `Config.default_client_mode`** —
  `"web" | "mobile" | "auto"` (`auto` = mobile, если есть живой OAuth-токен,
  иначе web).

📖 Как перевести аккаунт на mobile OTP — [`docs/MOBILE_MIGRATION_GUIDE.md`](docs/MOBILE_MIGRATION_GUIDE.md).
Общая схема двух каналов и абстракции — [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Скриншоты

### 📊 Главная — HUD карточки аккаунтов

![Главная](images/01-main.png)

На каждой карточке:
- **Статус-бейдж** с пульсацией (collecting / applying / waiting / limit)
- **HUD stat-boxы** — отклики / тесты / уже / ошибки / интервью с tabular-nums и glow
- **HR-метрики резюме** — просмотры / приглашения за 7 дней
- **LLM-блок** — статус, общий счётчик ответов, размер очереди
- **📤 Последняя попытка** + **✅ удачный отклик** с relative-ago таймером
- **🛑 HH-лимит ETA** — обратный отсчёт до 00:00 МСК когда сбросится квота
- Действия: пауза, очистка discards, авто-подъём резюме, ручной туч

### 📜 Лог событий

![Лог](images/02-log.png)

Журнал событий бота в реалтайме — что собрал, какие отклики прошли, какие
пропуски и почему, ответы LLM, ошибки авторизации, HH-лимиты. Фильтры по
аккаунту и уровню (info / warning / error).

### ✅ Отклики

![Отклики](images/03-applied.png)

История всех отправленных откликов: компания, вакансия, зарплата, время,
аккаунт. Поиск, сортировка, пагинация.

Кнопка **🔁 (похожие)** на каждой строке раскрывает inline-таблицу из 10
похожих вакансий через `api.hh.ru/vacancies/{vid}/similar_vacancies` (до
**36 000+ похожих** на одну исходную). Чипы: 🧪 с тестом, 📝 нужно письмо,
✅ принимают неполные резюме, 🎓 стажировка.

### 🎯 HH Статус — переговоры

![HH Статус](images/04-hh.png)

Все переговоры с интервью-статусом + per-employer politeness (% чтения
откликов работодателем + дни ответа), per-HR онлайн-статус.

### 👁️ Просмотры резюме — sparkline + аудит

![Просмотры и аудит](images/05-views.png)

- **Всего просмотров за всё время** + новые непрочитанные
- **30-day sparkline** — daily breakdown из `graphHistoryViews` SSR
- Список просмотревших работодателей с датой
- **Аудит резюме**: % заполненности, конкуренция по запросам, скилы
  конкурентов с частотой, проблемы по уровню важности
- **🔥 Горячие лиды** — работодатели, готовые пригласить (из
  `/shards/applicant/negotiations/possible_job_offers`)

### 🚀 Ручной отклик

![Ручной отклик](images/06-apply.png)

Точечный отклик: вставляешь URL вакансии, бот собирает форму (включая
опросник, который заполнит LLM или шаблоны), показывает результат.
Удобно для вакансий с тестами.

### 🤖 LLM Авто-ответы

![LLM Ответы](images/07-llm.png)

Таблица переговоров с авто-ответами + чипы **рейтинга работодателя** на
каждой строке:

- ⭐ **общий рейтинг** (зелёный ≥4.3 / жёлтый ≥3.8 / красный <3.8) с
  tooltip-разбивкой по 6 категориям (workplace / team / management /
  career / rest / salary)
- 📖 **politeness** — % чтения откликов работодателем + дни ответа
- 🚫 **last_state** (DISCARD / INVITE / RESPONSE / INTERVIEW)
- 👁 viewed_by_opponent (HR увидел/нет) + 📬 непрочитанные у HR
- 🟢 **HR online сейчас** / 🟠 был вчера / 🔴 неделю назад
- 📪 inbox_off (работодатель отключил входящие)

Источники: `employer_reviews/proxy_components/small_widget`,
`applicantEmployerPoliteness`, `applicantEmployerManagersActivity` —
смерджены backend'ом в один endpoint per vacancy.

### ⚙️ Настройки

![Настройки](images/08-settings.png)

Все параметры бота на одной вкладке (разделы collapsible):

- **Браузерные сессии** — добавление через cURL/cookie-string или
  вручную; редактирование кук с горячим обновлением (без рестарта)
- **Параметры бота** — слайдеры: страниц на URL, пауза, размер пакета,
  мин. зарплата, дневной лимит, авто-пауза при ошибках, интервал LLM
- **Фильтры** — заголовки (include / exclude tags), формат работы
  (полный/удалёнка/гибкий/сменный/вахта), регион
- **LLM-профили** — несколько провайдеров с fallback/round-robin,
  системный промпт, чекбоксы (use resume / cover letter / fill
  questionnaire / auto-send), one-click setup
- **🎯 Диагностика** — на главной: бейдж с red-flags + сменой
  `jobSearchStatus` через `/shards/user_statuses/job_search_status`
- **JSON-редактор + бэкап** — единый файл со всеми config + accounts
  + browser_sessions + oauth_tokens; защита от затирания

---

## Что умеет

### 🔥 Реалтайм-канал

- **WebSocket push** через `wss://websocket.hh.ru/ws/connect` — бот
  получает событие `chat_message_create` мгновенно (HR написал → бот
  отвечает через 1-2с), вместо 5-минутного polling
- Reconnect-логика как у HH-фронта: до 120 попыток, backoff 2-30с,
  ping 180с
- Fallback на polling если WS недоступен

### 🤖 LLM auto-reply

- **DeepSeek / OpenAI / Anthropic / OpenRouter / любой OpenAI-compat API**
- Multi-profile: fallback (попробовать по очереди) или round-robin
- Persona по полу соискателя (female / male / neutral) — корректные
  склонения в ответах
- Контекст: резюме (если включено) + история чата (последние 8 сообщений)
- Защита от prompt-injection (явное предупреждение системному промпту)
- **Smart robot-recruiter button picker** — если HH прислал кнопки
  «Да / Нет», бот их распознаёт и жмёт правильную (heuristic + LLM
  fallback для неоднозначных случаев)
- **LLM_PROXY** — отдельный прокси только для LLM-трафика, hh.ru
  остаётся напрямую (актуально для РФ-серверов)

### 🎯 Стратегические фильтры (экономят токены / лимит)

- **DISCARD-фильтр** — если HH помечает вакансию `userLabelsForVacancies:
  DISCARD` (работодатель уже отказал), бот не повторяется. На реальной
  выборке экономит ~16% откликов в день
- **chat_write_possibility=DISABLED фильтр** — 15% чатов в выборке
  имели его, бот не тратит LLM-токены на гарантированный отказ
- **Title keyword filters** — include/exclude по словам в заголовке
- **Salary / schedule / region** — стандартные
- **Auto-pause** — при `consecutive_errors >= N` или HH-лимите (с
  авто-сбросом в 00:00 МСК)

### 📊 Конкурентная аналитика

- **Рейтинг работодателей** — `employer_reviews/proxy_components/small_widget`,
  6 категорий, топ-преимущества, число отзывов; кэш 24ч
- **Politeness индекс** — `applicantEmployerPoliteness` SSR-поле:
  % чтения откликов + дни ответа per employer
- **HR online-статус** — `applicantEmployerManagersActivity` per HR-hhid
- **Topic state** — viewedByOpponent, conversationUnreadByEmployerCount,
  lastState, inboxAvailabilityState
- **Аудит резюме** — конкуренция по запросам (вакансий / соискателей),
  скилы топ-конкурентов, проблемы заполнения

### 📈 Resume tracking

- **18 000+ просмотров всего времени** + 30-day sparkline
- Кто просмотрел (компания + дата) — последние 50
- Авто-подъём резюме раз в 4 часа через `/applicant/resumes/touch`
- HH-инвайты — `userStats.new-applicant-invitations` (отдельным счётчиком)

### 🔐 OAuth-совместимый канал

- Опт-ин через `chat_use_oauth: true`: бот сначала пробует официальный
  `POST api.hh.ru/common/chats/{id}/messages` с Bearer-токеном
  (`is_automated: true`), fallback на reverse-engineered
  `chatik.hh.ru/api/send`. ToS-compliant путь
- `_oauth_apply` для откликов через official API (опц.)

### 🛠 Инфраструктура

- **Backup/restore** — единый JSON со всем (config + accounts +
  browser_sessions + oauth_tokens), защита от затирания непустых
  полей пустыми (нужен `?force=1` для перезаписи)
- **Региональный поддомен** — `<region>.hh.ru` для поиска/откликов
  (SSRF-защита regex'ом)
- **JSON-редактор** — прямая правка raw config через UI
- **161 unit-тест**, atomic-writes через filelock

---

## Быстрый старт

### Docker (рекомендуется)

```bash
git clone https://github.com/Vlad9572324/hh.ru-clicker.git
cd hh.ru-clicker
docker-compose up -d
```

→ открыть http://localhost:8000

Compose поднимает два сервиса: `hh-bot` (сам бот, `build: .`, точка входа
`python web_app.py`) и `singbox` — sidecar-прокси (VLESS+Reality → MSK IP),
в который заворачивается весь hh.ru-трафик (`HH_PROXY`). Для прокси нужен
конфиг `data/singbox/config.json`; если его нет, бот стартует, но hh.ru
запросы пойдут через нерабочий прокси.

### Локально (Python)

```bash
git clone https://github.com/Vlad9572324/hh.ru-clicker.git
cd hh.ru-clicker
pip install -r requirements.txt
python web_app.py
```

→ открыть http://localhost:8000

### Доступ из локальной сети + API-ключ

```bash
KEY=$(uuidgen | tr -d -)
HH_BOT_HOST=0.0.0.0 HH_BOT_UNSAFE_EXPOSE=1 HH_BOT_API_KEY=$KEY python web_app.py
echo "Открой http://<host>:8000/?key=$KEY"
```

Без `HH_BOT_API_KEY` бот **не пустит** в режиме LAN-exposure. С ключом —
фронт сам подставит его во все API/WS вызовы.

---

## Первый запуск

1. **Браузерная сессия**: Настройки → Браузерные сессии →
   «➕ Добавить сессию из браузера». Открой hh.ru в браузере, скопируй
   любой запрос как cURL (F12 → Network → правая кнопка → Copy as cURL),
   вставь в форму. Бот вытащит cookies, проверит сессию, найдёт твои
   резюме.

2. **Поисковые URL**: Настройки → 🔗 Пул поисковых запросов. Вставь
   URL поиска со страницы hh.ru/search/vacancy, или жми **✨ Подсказки**
   — бот предложит запросы из аудита твоего резюме с конкуренцией по
   каждому.

3. **(Опц.) LLM**: Настройки → 🤖 LLM → **⚡ Быстрая настройка** —
   вставь API-ключ, нажми Enter. Бот сам определит провайдера
   (OpenAI / DeepSeek / Anthropic / Groq / Gemini / HuggingFace),
   подставит base_url + model, включит auto-send.

4. **Запустить**: На главной нажми **▶ Запустить** на карточке сессии.
   Бот начнёт собирать вакансии, отвечать на чаты в реалтайме через WS.

5. **Диагностика**: На карточке появится жёлтый бейдж если HH видит
   что-то не так (например `jobSearchStatus=not_looking_for_job` —
   HR в чатах видит «не ищу работу», и % ответов падает). Клик →
   one-click фикс.

---

## Конфигурация

Все настройки в `data/config.json`, редактируются через GUI или JSON-editor.

### Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `HH_BOT_HOST` | `127.0.0.1` | Интерфейс сервера |
| `HH_BOT_PORT` | `8000` | Порт |
| `HH_BOT_UNSAFE_EXPOSE` | (пусто) | `=1` чтобы разрешить host вне loopback |
| `HH_BOT_API_KEY` | (пусто) | API-ключ (обязателен при LAN-exposure) |
| `HH_BOT_ALLOWED_ORIGINS` | (пусто) | Доп. хосты в WS Origin whitelist |
| `HH_CHATIK_BASE` | `https://chatik.hh.ru` | Chatik base (allowlist) |
| `LLM_PROXY` | (пусто) | Прокси **только** для LLM-трафика |

### `LLM_PROXY`

РФ-сервер → hh.ru работает напрямую (нужен РФ-IP), но LLM-провайдеры
(OpenAI и т.п.) недоступны. Глобальный `HTTPS_PROXY` завернул бы и
hh.ru. `LLM_PROXY` разделяет: LLM через прокси, hh.ru напрямую.

```bash
LLM_PROXY="http://user:pass@1.2.3.4:8080" python web_app.py
# Или socks5 (нужен pip install httpx[socks] PySocks):
LLM_PROXY="socks5://user:pass@1.2.3.4:1080" python web_app.py
```

В Docker — `environment:` сервиса. Через прокси идут чат-вызовы и
проверка ключа (`/api/llm_detect`). Реализация:
[`app/llm.py`](app/llm.py#L51) (`_make_openai_client`) +
[`app/routes/llm.py`](app/routes/llm.py) (`_llm_proxies`).

### Региональный поддомен

`config.hh_region` (через UI или JSON):

- пусто → `https://hh.ru` для всех запросов
- `syktyvkar` → `https://syktyvkar.hh.ru` для поиска/откликов/переговоров
- OAuth и chatik **всегда** на основном домене

---

## Структура проекта

```
hh.ru-clicker/
├── web_app.py              # entrypoint: FastAPI + uvicorn
├── app/
│   ├── config.py           # CONFIG + hh_base() + load/save
│   ├── state.py            # AccountState
│   ├── storage.py          # кэши applied/tests/interviews
│   ├── manager.py          # BotManager, workers, snapshot
│   ├── hh_api.py           # HTTP-headers, parse_search_page,
│   │                       #   parse_apply_strategy_meta (autoResponse +
│   │                       #   chatWritePossibility + hh_labels)
│   ├── hh_apply.py         # отклики, popup-классификатор, опросники
│   ├── hh_chat.py          # chatik API + ChatikWSClient (WS push)
│   ├── hh_resume.py        # парсинг резюме, аудит, конкуренция,
│   │                       #   диагностика, set_job_search_status
│   ├── hh_negotiations.py  # politeness, HR activity, employer rating,
│   │                       #   similar_vacancies, topics_by_vid
│   ├── llm.py              # OpenAI-compat клиент, robot button picker
│   ├── questionnaire.py    # парсинг и заполнение анкет
│   ├── oauth.py            # HH OAuth токены, send_chat_message_oauth
│   ├── hh_client.py        # HHClient — абстрактный интерфейс (Phase 0)
│   ├── hh_client_web.py    # WebHHClient — web-flow (cookies) адаптер
│   ├── hh_client_mobile.py # MobileHHClient — mobile-flow (OAuth Bearer)
│   ├── hh_client_factory.py # get_client(): выбор web/mobile по mode
│   ├── logging_utils.py    # log_debug, _is_login_page
│   ├── instances.py        # singleton bot
│   └── routes/
│       ├── __init__.py     # FastAPI + lifespan + middleware
│       ├── core.py         # /, /ws, broadcast_loop
│       ├── accounts.py     # /api/account/{idx}/...
│       ├── sessions.py     # /api/session/...
│       ├── apply.py        # /api/apply/...
│       ├── llm.py          # /api/llm_*
│       ├── data.py         # /api/applied, /api/interviews, ...
│       ├── settings.py     # /api/raw/config, /api/backup
│       └── debug.py        # /api/debug/...
├── static/
│   ├── index.html          # SPA
│   ├── css/
│   │   ├── style.css       # базовая тёмная тема
│   │   └── theme-autoclicker.css  # cyberpunk-overlay (опц.)
│   └── js/app.js           # vanilla JS (~5000 строк)
├── docs/
│   ├── hh_openapi.yaml     # public HH OpenAPI spec (106 paths, 1.2 МБ)
│   ├── HH_OPENAPI_KEY_FINDINGS.md
│   └── HH_API_MAP.md       # reverse-engineered API + SSR fields
├── data/                   # gitignored
│   ├── config.json
│   ├── accounts.json
│   ├── browser_sessions.json
│   ├── applied_vacancies.json
│   ├── interviews.json
│   ├── oauth_tokens.json
│   ├── llm_log.jsonl
│   └── debug.log
├── tests/                  # pytest, 161 тест
├── images/                 # README screenshots (replayed via Playwright)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Технологии

| Компонент | Стек |
|---|---|
| Backend | Python 3.10+, FastAPI, uvicorn, aiohttp, requests |
| Frontend | Vanilla JS + WebSocket (300мс tick), no framework |
| LLM | OpenAI SDK + httpx (optional proxy) |
| HH API | reverse-engineered `chatik.hh.ru` + `websocket.hh.ru` WS push + 106-path public OpenAPI |
| OAuth | hh.ru OAuth2 (Android-app credentials) |
| Тесты | pytest, 161 unit-тест |
| Деплой | Docker + docker-compose |

---

## Требования

- **Python 3.10+** (для локального запуска)
- **Активная сессия hh.ru** — нужны cookies `hhtoken`, `_xsrf`, `crypted_id`,
  `hhul` (бот сам достаёт `hhuid` / `crypted_hhuid` при первом запросе)
- **API-ключ LLM-провайдера** — опционально, только для авто-ответов и
  заполнения опросников

---

## Безопасность и приватность

- `data/` в `.gitignore` — личные cookies и API-ключи не попадают в репо
- Бэкап содержит реальные cookies/ключи — храни как пароль, не публикуй
- `HH_BOT_API_KEY` защищает дашборд при LAN-exposure
- WebSocket Origin-проверка отбрасывает CSWSH-атаки
- CSP-заголовки на статике
- Redact-логи: hhtoken / API-ключи никогда не пишутся в `debug.log`
- Скриншоты в `images/` сгенерированы Playwright'ом с агрессивной
  PII-маскировкой (имена → рандом-пул фейков, телефоны → `•••`,
  чаты blur 4px, raw config-textareas замаскированы)

---

## Документация

Документация по рефакторингу и эксплуатации — в `docs/`:

- [`docs/MOBILE_MIGRATION_GUIDE.md`](docs/MOBILE_MIGRATION_GUIDE.md) — как
  перевести аккаунт с cookies на mobile OTP-аутентификацию (пошагово).
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — устройство бота: два
  канала (web/mobile), абстракция `HHClient`, workers, realtime.
- [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) — REST/WS endpoint'ы
  дашборда (`/api/*`, `/ws`).
- [`docs/CONFIG_REFERENCE.md`](docs/CONFIG_REFERENCE.md) — справочник
  `data/config.json`, env-переменных и поля `mode` у аккаунтов.
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — типовые проблемы:
  лимиты HH, captcha, OAuth, прокси.
- [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) — как вносить изменения:
  тесты, стиль, процесс.
- [`CHANGELOG.md`](CHANGELOG.md) — история изменений по версиям.

---

## Reverse-engineering

В [`docs/`](docs/) лежит документация по reverse-engineered HH API:

- [`hh_openapi.yaml`](docs/hh_openapi.yaml) — полная public OpenAPI spec
  (106 paths, скачана с `api.hh.ru/openapi/specification/public`)
- [`HH_OPENAPI_KEY_FINDINGS.md`](docs/HH_OPENAPI_KEY_FINDINGS.md) — ключевые
  находки: webhook-API (HR-only), `/common/chats` для applicant OAuth,
  `/negotiations/{nid}/test/solution`, dev.hh.ru ecosystem
- [`HH_API_MAP.md`](docs/HH_API_MAP.md) — карта 230+ endpoint'ов и SSR-полей
  с примечаниями где работают cookies vs OAuth

---

## Лицензия

Личный проект. Использование на свой страх и риск. HH.ru может изменить
ToS — бот может перестать работать, попасть в shadow-ban и т.д.
