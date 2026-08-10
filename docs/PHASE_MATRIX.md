# PHASE_MATRIX — карта методов HHClient × фазы миграции × backends

Roadmap-документ mobile-migration: какой метод абстракции `HHClient`
(`app/hh_client.py`) к какой фазе относится, в каком состоянии его web- и
mobile-реализации, и кто реально вызывает соответствующую операцию в `app/`.

Документ закрывает требование review «consumer → domain operation →
Phase/backend» и фиксирует нумерацию фаз, которой до сих пор не было ни в
одном документе репозитория (нумерация существовала только в текстах
заглушек `MobileHHClient`).

Состояние снято с ветки `refactor/mobile-api` (Phase 0, в работе). Источники —
в конце документа.

---

## 1. Обозначения

**Фазы** (нумерация из заглушек `app/hh_client_mobile.py` и docstring'ов):

| Фаза | Что мигрирует на mobile (OAuth Bearer `api.hh.ru`) |
|---|---|
| **0** | Только абстракция: интерфейс + адаптеры + фабрика. Без миграции боевой логики |
| **1** | Не определено (см. §4) |
| **2** | Переговоры / чаты (группа A без vacancy/employer-метаданных) |
| **3** | Отклики (группа B) + vacancy/employer-метаданные (см. §5) |
| **3.5** | Без новых реализаций: внешние hot-path callers переводятся на фабрику `get_client(acc)` |
| **3.6** | Аудит оставшихся route/API caller-файлов и расширение AST-guard |
| **4** | Резюме / статистика (группа C) |

**Capability-слои интерфейса.** После fix P2 интерфейс разложен на слои
(`app/hh_client.py`):

- `HHClientBase` — общий слой: методы, которые обе реализации имеют (или
  planned-имеют) с одинаковой семантикой. Тип `HHClientBase` **гарантирует
  вызываемость** всех своих методов: группа A, группа B **без**
  `fill_questionnaire`, группа C, группа E.
- `WebOnlyOps` — web-only операции: `fill_questionnaire` (§3).
- `MobileOnlyOps` — mobile-only операции: `fetch_counters` (§3).
- `HHClient = HHClientBase + WebOnlyOps + MobileOnlyOps` — полный контракт,
  сохранён ради backward-compat (фабрика и тайпхинты `-> HHClient` видят
  «полный интерфейс»). Новый код, которому нужна гарантия вызываемости
  конкретного метода, типизируется против `HHClientBase` или нужного
  `*OnlyOps`.

В матрице ниже методы сгруппированы по доменным группам A–E (как в
`HHClientBase`); принадлежность к capability-слою отмечена в строках
`fill_questionnaire` и `fetch_counters`.

**Колонки таблицы:**

- **Web** — состояние в `WebHHClient` (`app/hh_client_web.py`):
  - `делегат` — метод делегирует в существующую web-flow функцию
    (`hh_chat` / `hh_apply` / `hh_negotiations` / `hh_resume` / `oauth`),
    ноль новой логики;
  - `нет` — реализация отсутствует (`NotImplementedError`).
- **Mobile** — состояние в `MobileHHClient` (`app/hh_client_mobile.py`):
  - `да` — реально реализован;
  - `делегат` — делегирует в `app/oauth.py` (Bearer, одинаково для обоих
    клиентов);
  - `заглушка phase N` — `NotImplementedError("phase N: TODO mobile ...")`.
- **Consumer(s)** — фактические call-sites операции в `app/` на текущий
  момент. С Phase 3.5 все внешние hot-path callers web-flow функций
  переведены на фабрику `get_client(acc)` (40 call-site: `manager.py`,
  `routes/accounts.py`, `routes/debug.py`); прямые импорты модульных
  функций остались только для исключений (§3, «Вне матрицы»). Строки
  указаны по состоянию ветки на момент написания и могут плыть при
  рефакторинге.

---

## 2. Матрица

### Группа A — переговоры / чат

| Метод HHClient | Фаза | Web | Mobile | Consumer(s) |
|---|---|---|---|---|
| `fetch_negotiations` | 2 | делегат | да (Phase 2: `mobile_negotiations`, `GET api.hh.ru/negotiations`) | через абстракцию: `routes/debug.py:190` (`/api/debug/neg_ids`); `manager.py:2762` (`fetch_hh_negotiations_stats`) — через `get_client` с Phase 3.5 |
| `fetch_thread` | 2 | делегат | да (Phase 2: `mobile_chat_thread`, `GET api.hh.ru/chats/{id}?limit&order=next`) | `routes/debug.py:216` (`/api/debug/thread`) — через `get_client` с Phase 3.5 |
| `send_message` | 2 | делегат | да (Phase 2: `mobile_send_message`, `POST api.hh.ru/chats/{id}/messages` + idempotency_key) | `manager.py:2429`, `2588` — через `get_client` с Phase 3.5 |
| `fetch_chat_list` | 2 | делегат | да (Phase 2: `mobile_chat_list`, `GET api.hh.ru/chats`, возврат-кортеж как у web) | `manager.py:2175` — через `get_client` с Phase 3.5 |
| `fetch_chat_history` | 2 | делегат | да (Phase 2: `mobile_chat_thread.fetch_chat_history`, тот же конверт чата) | `manager.py:2397`, `2399` — через `get_client` с Phase 3.5 |
| `fetch_quick_replies` | 2 | делегат | да (Phase 2: `mobile_chat_actions`, `PUT .../suggestions/quick_replies?message_id=`) | `manager.py:2509`, `2541` — через `get_client` с Phase 3.5 |
| `send_participant_action` | 2 | делегат | да (Phase 2: `mobile_chat_actions`, `PUT .../participants/action` {action_type: typing\|none}) | `manager.py:2582` (TYPING), `2590` (NONE) — через `get_client` с Phase 3.5 |
| `mark_chat_read` | 2 | делегат | да (Phase 2: `mobile_chat_actions`, `PUT .../messages/last_viewed_id` form message_id) | `manager.py:2581` — через `get_client` с Phase 3.5 |
| `fetch_possible_offers` | 2 | делегат | да (Phase 2: `mobile_neg_meta`, `GET api.hh.ru/vacancies/possible_job_offers`) | `manager.py:2792` — через `get_client` с Phase 3.5 |
| `auto_decline_discards` | 2 | делегат | заглушка phase 2 (decline есть только в web-flow; `FallbackHHClient` прозрачно повторяет через web) | `routes/accounts.py:1120` — через `get_client` с Phase 3.5 |
| `fetch_negotiations_metadata` | 2 | делегат | да (Phase 2: `mobile_neg_meta`, `GET api.hh.ru/negotiations` → topics_by_vid; politeness/activity — только web-SSR) | `routes/accounts.py:182` — через `get_client` с Phase 3.5 |
| `fetch_employer_rating` | **3** ¹ | делегат | заглушка phase 3 | `routes/accounts.py:187`, `219` — через `get_client` с Phase 3.5 |
| `fetch_employer_id_for_vacancy` | **3** ¹ | делегат | заглушка phase 3 | `routes/accounts.py:180` — через `get_client` с Phase 3.5 |
| `fetch_vacancy_owner_hr_hhid` | **3** ¹ | делегат | заглушка phase 3 | `routes/accounts.py:181` — через `get_client` с Phase 3.5 |

¹ Целевая классификация по замечанию review: рейтинг работодателя,
`employer_id` и HR-владелец вакансии — это vacancy/apply-метаданные,
поэтому им **Phase 3**, а не Phase 2. В `app/hh_client_mobile.py` метки
уже перенесены (заглушки `phase 3`, секция «отклики и vacancy-метаданные»);
подробнее — §5.

### Группа B — отклики

| Метод HHClient | Фаза | Web | Mobile | Consumer(s) |
|---|---|---|---|---|
| `submit_response` (async) | 3 | делегат | заглушка phase 3 | `manager.py:1592` (`send_response_async`) — через `get_client(...).submit_response(...)` с Phase 3.5 (`asyncio.gather` сохранён); диспетчизация web/OAuth `manager.py:1577-1597` (`state.use_oauth or CONFIG.use_oauth_apply or state.degraded_mode` → `_oauth_apply`) вне scope Phase 3.5 — функции `app.oauth` не мигрируются |
| `fill_questionnaire` (async) ² | web-only | делегат | заглушка phase 3 | `manager.py:1687` — через `get_client` с Phase 3.5 (mobile-заглушка прозрачно ретраится через web `FallbackHHClient`) |
| `check_vacancy_before_apply` | 3 | делегат | заглушка phase 3 | `manager.py:1529` — через `get_client` с Phase 3.5 |
| `check_limit` | 3 | делегат | заглушка phase 3 | `manager.py:1090` — через `get_client` с Phase 3.5 |
| `touch_resume` | 3 | делегат | заглушка phase 3 | `manager.py:1060` — через `get_client` с Phase 3.5 (web-функция уже OAuth-first внутри: `hh_apply.py:617` → `_oauth_touch_resume`) |
| `fetch_related_vacancies` | 3 | делегат | заглушка phase 3 | `manager.py:1206` — через `get_client` с Phase 3.5 |

² Единственный метод группы B вне `HHClientBase`: входит в capability-слой
`WebOnlyOps`. См. §3 — анкеты являются web-only capability.

### Группа C — резюме

| Метод HHClient | Фаза | Web | Mobile | Consumer(s) |
|---|---|---|---|---|
| `fetch_stats` | 4 | делегат | заглушка phase 4 | `manager.py:2795`; `routes/accounts.py:566` — через `get_client` с Phase 3.5 |
| `fetch_resume` | 4 | делегат | заглушка phase 4 | `manager.py:2381`; `routes/accounts.py:672` — через `get_client` с Phase 3.5; плюс внутренний вызов в `hh_apply` (сопровождает `fill_and_submit_questionnaire`, часть web-flow) |
| `fetch_resume_view_history` | 4 | делегат | заглушка phase 4 | `manager.py:2806`; `routes/accounts.py:562` — через `get_client` с Phase 3.5 |
| `fetch_resume_views_aggregate` | 4 | делегат | заглушка phase 4 | `routes/accounts.py:581` — через `get_client` с Phase 3.5 |
| `analyze_resume` | 4 | делегат | заглушка phase 4 | `routes/accounts.py:697`, `711` — через `get_client` с Phase 3.5 |
| `edit_resume_field` | 4 | делегат | заглушка phase 4 | `routes/accounts.py:904` (clone), `960` (edit) — через `get_client` с Phase 3.5 |
| `set_job_search_status` | 4 | делегат | заглушка phase 4 | `routes/accounts.py:239`; `manager.py:992` — через `get_client` с Phase 3.5 |
| `fetch_account_diagnostics` | 4 | делегат | заглушка phase 4 | `routes/accounts.py:150` — через `get_client` с Phase 3.5 |

### Группа D — счётчики

| Метод HHClient | Фаза | Web | Mobile | Consumer(s) |
|---|---|---|---|---|
| `fetch_counters` ⁴ | 0 | нет (web-аналога `GET /me` не существует) | да (`GET https://api.hh.ru/me?with_user_statuses=true` c Bearer) | production-вызовов нет — метод добавлен как smoke-test абстракции; покрыт `tests/test_hh_client_abstraction.py` |

⁴ Единственный метод группы: входит в capability-слой `MobileOnlyOps`
(вне `HHClientBase`). См. §3.

### Группа E — OAuth-extras (Bearer `api.hh.ru`)

Эти операции **уже** выполняются через официальный API с Bearer-токеном и
делегированием в `app/oauth.py` — одинаково из обоих клиентов. Фаза
миграции неприменима (нечего мигрировать); в матрице для полноты.

| Метод HHClient | Фаза | Web | Mobile | Consumer(s) |
|---|---|---|---|---|
| `fetch_saved_vacancy_searches` | — | делегат | делегат | `manager.py:1124` |
| `fetch_favorited_vacancies` | — | делегат | делегат | `manager.py:1220` |
| `fetch_blacklisted_vacancies` | — | делегат | делегат | `manager.py:1235` |
| `fetch_vacancy_details` | — | делегат | делегат | `manager.py:1332` |
| `fetch_negotiations_today_count` | — | делегат | делегат | `manager.py:1885` |
| `fetch_negotiations_statistic` | — | делегат | делегат | `manager.py:1894` |
| `fetch_resume_status` | — | делегат | делегат | `manager.py:2756` |
| `fetch_employer_rating_oauth` ³ | — | делегат | делегат | `manager.py:1352` (как `oauth.fetch_employer_rating`) |

³ Имя с суффиксом `_oauth`, чтобы не сталкиваться с web-методом
`fetch_employer_rating` (группа A): это две разные реализации одной
сущности — web-scraping (`hh_negotiations.fetch_employer_rating`) и
Bearer (`oauth.fetch_employer_rating`).

Всего в полном контракте `HHClient` 37 методов: A — 14, B — 6
(из них `fill_questionnaire` в `WebOnlyOps`), C — 8, D — 1
(`MobileOnlyOps`), E — 8; в `HHClientBase` — 35.

---

## 3. Capability-исключения (асимметрия web/mobile)

Именно эти два метода стали причиной разложения интерфейса на
capability-слои (`HHClientBase` / `WebOnlyOps` / `MobileOnlyOps`, см. §1):
один ABC смешивал несовместимые capabilities, и тип `HHClient` не
гарантировал вызываемость всех своих методов.

1. **`fill_questionnaire` — web-only, mobile-семантика TBD.** Анкеты/тесты
   при отклике заполняются только web-каналом (cookies +
   `/applicant/vacancy_response/popup`); в OAuth-режиме бот откликается
   «без опросников/тестов» (известное ограничение №6 в
   `docs/MOBILE_MIGRATION_GUIDE.md`). Метод вынесен в `WebOnlyOps`.
   Заглушка в `MobileHHClient` формально помечена `phase 3`, но мобильной
   реализации пока не планируется; fallback-политика для mobile-аккаунтов
   (делегировать в web-flow или оставить `NotImplementedError`) будет
   решена в Phase 3.
2. **`fetch_counters` — mobile-only.** `GET /me?with_user_statuses=true`
   существует только в `api.hh.ru`; web-аналога нет (ближайший суррогат —
   `fetch_account_diagnostics`, но это другая операция). Метод вынесен в
   `MobileOnlyOps`; `WebHHClient` кидает
   `NotImplementedError("phase 0: web-клиент не имеет аналога GET /me")`.
   Потребителей в production пока нет.
3. **OAuth-extras (группа E) работают через Bearer одинаково в обоих
   клиентах** — делегирование в `app/oauth.py`, выбор backend'а на них не
   влияет.

**Вне матрицы** (сознательно не входят в интерфейс клиента; все
перечисленные объекты и после Phase 3.5 остаются прямыми импортами из
модулей — перевода на `get_client` для них нет и не планируется):

- `ChatikWSClient` (`hh_chat.py`) — web-only push-канал (`websocket.hh.ru`),
  мобильного аналога нет;
- `fetch_similar_vacancies` (`hh_negotiations.py`) — публичный `api.hh.ru`
  без аккаунта, глобальный кэш;
- чистые парсеры HTML без HTTP/аккаунта (`parse_hh_lux_ssr`, `parse_ids`,
  `get_headers`, `classify_apply_response`, `_check_chat_locked`, …);
- токен-менеджмент (`_obtain_oauth_token`, `invalidate_oauth_token`,
  `get_oauth_status`, `refresh_oauth_tokens_proactive`) — уровень
  фабрики/авторизации, а не клиентского интерфейса;
- `fetch_rating_by_vacancy` (`hh_negotiations.py`) — мёртвый код: единственный
  мёртвый импорт в `routes/accounts.py:31` удалён в Phase 3.5, вызовов не
  было. В интерфейс не включён.

---

## 4. Roadmap фаз

- **Phase 0 — абстракция (текущая, в работе).** Интерфейс `HHClient`
  («один клиент — один аккаунт», capability-слои §1), `WebHHClient`-адаптер
  (ноль новой логики), skeleton `MobileHHClient` (реально только
  `fetch_counters` + группа E), фабрика `get_client(account)`, настройка
  `CONFIG.default_client_mode`, опциональное поле `mode` у аккаунтов/
  temp-сессий. Боевая логика на абстракцию НЕ переводится (единственное
  исключение — `/api/debug/neg_ids`). Диспетчизация web-vs-OAuth в
  `manager.py` (строки 1577-1597) сохраняется как есть.
- **Phase 1 — не определено.** Ни в коде, ни в документах нет описания
  содержимого фазы 1: заглушки `MobileHHClient` нумеруют
  `phase 2 → phase 3 → phase 4`, перепрыгивая единицу. До появления
  roadmap-решения считаем фазу 1 зарезервированной; ничего с такой меткой
  не существует.
- **Phase 2 — переговоры/чаты (выполнено в ветке `feat/phase2-chats-mobile`).**
  Перевод на mobile API (`app/mobile_*.py`, общий транспорт
  `app/hh_mobile_transport.py`): списки переговоров/чатов, треды, отправка
  сообщений, quick replies, participant actions, mark-read, possible offers,
  метаданные переговоров — 10 из 11 методов группы A. Исключения:
  `auto_decline_discards` (decline существует только в web-flow — остаётся
  заглушкой, `FallbackHHClient` прозрачно повторяет через web) и три метода
  vacancy/employer-метаданных (см. §5, целевая фаза 3). Добавлен auto-fallback
  mobile→web (`app/hh_client_fallback.py`): фабрика при явном `mode="mobile"`
  возвращает `FallbackHHClient`. Боевые потребители (`manager.py`) по-прежнему
  вызывают модульные функции напрямую — перевод на `get_client(...)` вне фазы.
- **Phase 3 — отклики (группа B) + vacancy/employer-метаданные.**
  `submit_response` (целевая mobile-реализация — `oauth._oauth_apply`,
  уже существует), пре-проверка вакансии, лимиты, touch, related vacancies.
  Сюда же целевым образом относятся `fetch_employer_rating`,
  `fetch_employer_id_for_vacancy`, `fetch_vacancy_owner_hr_hhid` (§5).
  `fill_questionnaire` — под вопросом (web-only, §3).
- **Phase 3.5 — внешние hot-path callers → фабрика (выполнено в ветке
  `feat/phase3.5-migrate-callers`).** Без новых реализаций: все внешние
  hot-path callers web-flow функций переведены на `get_client(acc)`
  (`app/hh_client_factory.py`) — **40 call-site в 3 файлах**:
  `app/manager.py` — 22, `app/routes/accounts.py` — 17,
  `app/routes/debug.py` — 1. Сам web-flow не тронут и остаётся
  fallback-реализацией: адаптер `WebHHClient` (`app/hh_client_web.py`) и
  модули `hh_chat.py`/`hh_apply.py`/`hh_negotiations.py`/`hh_resume.py`;
  `mode="mobile"` идёт через `FallbackHHClient(MobileHHClient,
  WebHHClient)` с авто-откатом на web. Проверенные группы без мигрируемых
  вызовов: `routes/{settings,llm,data,core,apply,ws}.py`, `web_app.py`,
  `hh_api.py`, `sessions.py`. Исключения остались прямыми импортами (§3,
  «Вне матрицы»): чистые функции без аккаунта `parse_hh_lux_ssr`
  (6 call-site), `fetch_similar_vacancies`, `_check_chat_locked`,
  `_build_thread_from_chat_item`; класс `ChatikWSClient` (WebSocket
  chatik.hh.ru — в mobile-flow свой push-канал); внутренние кэши/константы
  `_resume_cache`/`_RESUME_CACHE_TTL`/`_JOB_SEARCH_STATUSES`. Мёртвый
  импорт `fetch_rating_by_vacancy` удалён. OAuth-функции `app/oauth.py`
  вне scope фазы. Миграция зафиксирована AST-guard'ом
  `tests/test_phase35_migration.py`.
- **Phase 3.6 — оставшиеся callers (выполнено в ветке
  `feat/phase3.6-remaining-callers`).** Проверены `routes/settings.py`,
  `routes/llm.py`, `routes/data.py`, `routes/core.py`, `routes/sessions.py`,
  `routes/apply.py` и `hh_api.py`. Account-bound web-flow caller найден
  только уже мигрированным в `routes/apply.py`; вызовы `parse_hh_lux_ssr`
  в `routes/sessions.py` и `hh_api.py` остаются прямыми как чистый parser
  без `acc`. Все перечисленные файлы добавлены в покрытие AST-guard.
- **Phase 4 — резюме/статистика (группа C).** Текст резюме, статистика,
  история/агрегаты просмотров, аудит, редактирование полей, статус поиска,
  диагностика аккаунта.

Фаза 0 фиксирует только интерфейс; сроки и состав Phase 1+ вне этого
документа не утверждены.

---

## 5. Переклассификация review: employer-метаданные → Phase 3

Замечание review: `fetch_employer_rating`, `fetch_employer_id_for_vacancy`,
`fetch_vacancy_owner_hr_hhid` по смыслу относятся к **Phase 3**
(vacancy/apply metadata), а не к Phase 2:

- все три обслуживают карточку вакансии/пре-проверку отклика
  (`routes/accounts.py:180-187`), а не переписку;
- мобильные аналоги естественно ложатся на vacancy-endpoint'ы
  `api.hh.ru`, а не на negotiations-endpoint'ы.

В матрице (§2, группа A) указана целевая фаза **3**. В коде
`app/hh_client_mobile.py` переклассификация уже выполнена: заглушки
помечены `phase 3`, методы перенесены в секцию «Phase 3: отклики и
vacancy-метаданные». Доменное группирование в `HHClientBase` при этом не
меняется — методы остаются в группе A (переговоры/чат) как исторически
сложившиеся web-реализации в `hh_negotiations.py`.

---

## 6. Выбор backend'а (фабрика)

Точка выбора — `app/hh_client_factory.py::get_client(account)`. Источники
режима, по приоритету: `account["mode"]` → `CONFIG.default_client_mode`
(дефолт `"auto"`, валидация `web`/`mobile`/`auto` в `load_config()`).
Нормализация устойчива к не-строкам (`_normalize_mode`): не-строка →
`"auto"`; строка вне `{web, mobile, auto}` → `CONFIG.default_client_mode`
по тем же правилам; финальный fallback → `"web"`.

Семантика значений:

| mode | Поведение |
|---|---|
| `"web"` | всегда `WebHHClient` (cookies hh.ru / chatik.hh.ru) |
| `"mobile"` | с Phase 2 — `FallbackHHClient(MobileHHClient, WebHHClient)` (`app/hh_client_fallback.py`): вызовы идут в mobile-flow (OAuth Bearer api.hh.ru), а при fallback-статусах (0/401/403/5xx, см. `app.hh_mobile_transport.is_fallback_status`) или `NotImplementedError` (напр. `auto_decline_discards`) прозрачно повторяются через web-flow |
| `"auto"` | **целевое состояние: `WebHHClient`** — авто-выбор не приводит к mobile; mobile включается осознанно явным `mode="mobile"` |

**Решение (Phase 0, подтверждено в Phase 2):** `auto` → `web`; mobile-клиент
выбирается **только** при явном `mode="mobile"`. С Phase 2 явный mobile
возвращает `FallbackHHClient` поверх `MobileHHClient`, поэтому переключение
безопасно: нереализованные mobile-методы (фаза 3/4) и сбои mobile-авторизации/
сервера автоматически повторяются через проверенный web-flow.

> ⚠️ **(фикс в работе)** На момент написания этого документа фабрика в
> worktree ещё несёт старую семантику `auto`: `MobileHHClient`, если
> `oauth.get_oauth_status(resume_hash)["has_token"]`, иначе `WebHHClient`
> (`app/hh_client_factory.py`). Замена на целевую (`auto` → `web`)
> выполняется параллельно в рамках Phase 0. Показательно, что consumer уже
> движется к целевой семантике: `routes/debug.py::_effective_client_mode`
> резолвит `auto` в `web` с комментарием «Phase 0: "auto" резолвится в
> web-клиент». После вливания фикса в фабрику этот раздел сверить; ряд
> документов описывает старую семантику и может расходиться с фабрикой:
> `docs/ARCHITECTURE.md` §3, `docs/CONFIG_REFERENCE.md` §4,
> `docs/MOBILE_MIGRATION_GUIDE.md` §6, `docs/TROUBLESHOOTING.md`,
> `CHANGELOG.md` [Unreleased], docstring `app/hh_client.py`.

Задел на будущее: поле `mode` сохраняется на диск уже сейчас
(`save_accounts()`/`save_browser_sessions()` пропускают любые ключи без
префикса `_`), но UI-контрола для него в Phase 0 нет — правится через
JSON (`POST /api/raw/accounts`). Перевод боевых потребителей
(`manager.py`, routes) на `get_client(...)` — за пределами Phase 0
(выполнен в Phase 3.5, см. §4).

---

## 7. Источники

- `app/hh_client.py` — интерфейс, capability-слои (группы A–E,
  docstring'и методов);
- `app/hh_client_web.py` — web-делегаты; `app/hh_client_mobile.py` —
  фазовые метки заглушек и реальные реализации;
- `app/hh_client_factory.py`, `app/config.py` (`default_client_mode`,
  схема поля `mode`);
- `app/routes/debug.py` (`api_debug_neg_ids` — единственный
  production-потребитель фабрики; `_effective_client_mode` — целевая
  семантика `auto`), `app/routes/accounts.py`, `app/manager.py` —
  call-sites (проверены grep'ом по ветке);
- `app/oauth.py` — Bearer-функции группы E и уже существующие mobile-пути
  (`_oauth_apply`, `_oauth_touch_resume`, `fetch_negotiation_messages_oauth`);
- `CHANGELOG.md` [Unreleased] — состав Phase 0;
- `docs/MOBILE_MIGRATION_GUIDE.md` — ограничения web-only анкет;
- `docs/ARCHITECTURE.md` §3 — текущая (до фикса) диаграмма выбора режима;
- материалы deep-dive анализа Phase 0 (`phase0_analysis.md`: сигнатуры,
  call-sites, предложение интерфейса, что не включать в HHClient);
- материалы deep-dive анализа Phase 3.5 (`phase35_analysis.md`: таблицы
  call-site, группы файлов, исключения, маппинг web-flow функций на
  методы HHClient).
