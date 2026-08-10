# SECURITY FIX №3: Cross-account cookie confusion через общую curl_cffi Session

**Статус:** реализовано в ветке `fix/curl-cffi-per-account-sessions`, ожидает ревью и коммита мейнтейнера.
**Severity:** CRITICAL №3 (по результатам аудита, см. `AUDIT_REPORT.md`).
**Breaking changes:** нет — новые kwargs аддитивные, код без `cookie_jar_key` работает как раньше.

---

## Проблема

Все аккаунты фермы ходили к hh.ru через **один** singleton-клиент `HH = HHClient()`
(`app/hh_http.py`), внутри которого была одна curl_cffi `Session` (`_session_cffi`)
и одна requests `Session` (`_session_req`) — то есть **одна общая cookie jar на все
аккаунты**. Call sites передавали `cookies=acc["cookies"]`, но сессия merges эти
cookies в свой персистентный jar и носит их содержимое между запросами — в том числе
чужих аккаунтов.

### Механика confusion (по шагам)

1. Аккаунт A делает запросы через общий `HH` → его живой `hhtoken` оседает в общей
   cookie jar сессии.
2. Аккаунт B протух (hhtoken истёк / отозван). OAuth-flow восстановления B делает
   `GET https://hh.ru/oauth/authorize?...` под B's resume (`app/oauth.py`,
   Step 1 — строки ~331-337; Step 2 approve-POST ~343-350), передавая B's `cookies=`.
3. Но в общей jar всё ещё лежит **живой hhtoken аккаунта A**. hh.ru аутентифицирует
   запрос по нему: сервер видит юзера A, а не B.
4. Сервер выдаёт **OAuth code юзера A** в контексте resume/флоу аккаунта B.
   Итог: B получает token A (cross-account identity confusion): флоу B исполняется
   под личностью A, code/token A записывается в OAuth-кэш B.
5. **Корреляция фермы:** все аккаунты шарят одну jar (включая hhuid-производные
   cookies) → для hh.ru вся ферма выглядит как один субъект; риск массового бана
   всех аккаунтов одновременно.
6. **Недетерминизм:** curl_cffi сортирует cookies по времени/domain; записи `hh.ru`
   и `.hh.ru` — разные записи в jar. Какой hhtoken «победит» в конкретном запросе,
   зависит от тайминга → баг флуктуирующий и трудно воспроизводимый.

## Что изменилось

Все изменения — в `app/hh_http.py` (ядро) + kwargs на call sites.

### API

```python
r = HH.request("GET", url, cookies=acc["cookies"], cookie_jar_key=<account_key>)
```

- `request()` принимает новый kwarg `cookie_jar_key: str | None` (извлекается из
  kwargs через `kwargs.pop(...)`, как `_diag_tag`/`_skip_diag`/`_force_requests`,
  и **не** проходит в транспорт).
- `cookies=` остаётся pass-through к выбранной сессии.

### `_get_session(cookie_jar_key)` — LRU-реестр per-account сессий

- `cookie_jar_key=None` → **legacy** общие сессии `_session_cffi`/`_session_req`
  (запросы без аккаунтного контекста, например `probe_outbound_ip`).
- Иначе → per-key пара сессий `{"cffi": ..., "req": ...}` из реестра
  `self._sessions` (`collections.OrderedDict`, LRU):
  - ленивое создание при первом обращении;
  - `move_to_end(key)` при каждом доступе (recency);
  - лимит `_MAX_SESSIONS = 100`: при превышении вытесняется самая давно не
    использовавшаяся запись (`popitem(last=False)`), вытеснённые сессии
    закрываются (`.close()`), чтобы их keep-alive/cookies не переиспользовались;
  - все операции под `self._sessions_lock` (`threading.RLock`) — lock-safe при
    конкурентных запросах фермы.
- Fallback при ошибке curl_cffi идёт в **ту же per-key** requests-сессию, а не в
  общую (иначе cross-account confusion сохранялся бы на fallback-пути).

### `set_proxy()`

Пересоздаёт legacy-сессии (как раньше) **и очищает весь per-account реестр**
(под lock, с `.close()` вытеснённых сессий): keep-alive соединения, привязанные к
старому прокси, не должны переиспользоваться. Per-account сессии лениво
пересоздадутся через новый прокси при следующем запросе.

## Migration note (для кода, дёргающего `HH` напрямую)

**Правило:** любой вызов `HH.request/get/post/put/delete(...)` с аккаунтным
контекстом должен передавать **оба** kwargs одновременно:

```python
HH.get(url, cookies=acc["cookies"], cookie_jar_key=_token_key(acc), ...)
```

- Передать только `cookies=` **недостаточно**: без `cookie_jar_key` запрос уходит в
  legacy общую jar (kwarg опциональный, default `None`) — это ровно прежний
  уязвимый режим.
- Рекомендуемый ключ — `app.oauth._token_key(acc)`:
  `f"{resume_hash}::{sha256(hhtoken or short)[:16]}"` — стабилен на аккаунт и
  изолирует даже при совпадающем `resume_hash`.
- Мигрированы в рамках фикса: call sites в `app/hh_apply.py`, `app/hh_resume.py`
  (`cookie_jar_key=_token_key(acc)`); остальные callers с аккаунтным контекстом
  (oauth authorize-flow, negotiations, chat и т.п.) мигрируются в этой же ветке —
  regression-тесты фиксируют контракт для этих флоу.
- Для нового кода: добавляете `HH.*`-вызов внутри флоу, исполняемого под
  аккаунтом, — обязаны передать оба kwargs. Запросы без аккаунтного контекста
  (пробы, публичные endpoint'ы) `cookie_jar_key` не передают.

## Rollback strategy

- Изменения изолированы: ядро в `app/hh_http.py` (реестр сессий + kwarg) и kwargs
  на call sites. Схем данных, persisted-state и миграций нет — per-account сессии
  живут только в памяти процесса.
- Откат = **revert коммита** (коммит делает мейнтейнер вручную после ревью).
- Revert безопасен: kwargs аддитивные, callers без `cookie_jar_key` продолжают
  работать (legacy shared jar — поведение до фикса). Никакой очистки данных или
  runtime-состояния при откате не требуется.

## Тесты

### `tests/test_hh_http_per_account.py`

Unit-тесты без сети (транспорт подменён fake-сессиями, curl_cffi-путь
принудительно выключен — детерминированы независимо от наличия curl_cffi в CI):

- **(a) Изоляция:** разные `cookie_jar_key` → разные instances сессий; повторный
  доступ к тому же ключу → тот же instance; `None` → legacy общая сессия;
  маршрутизация `request()` по per-account сессиям, `cookies=` прокидываются в
  сессию своего аккаунта, `cookie_jar_key` не утекает в транспорт.
- **(b) LRU:** `_MAX_SESSIONS == 100`; 101-й ключ вытесняет самую давно не
  использовавшуюся запись (вытеснённая сессия закрыта; повторное обращение
  создаёт новую); обращение к ключу защищает его от вытеснения (recency touch).
- **(c) `set_proxy()`:** очищает legacy и per-account сессии; клиент остаётся
  рабочим — следующий запрос получает свежую сессию, прокси прокинут в транспорт.
- **(d) Thread-safety:** 16 потоков × десятки итераций конкурентного доступа —
  ровно один instance сессии на ключ; LRU-инвариант (реестр ≤ лимита) сохраняется
  под конкуренцией.

### `tests/test_hh_http_regression.py`

Regression-фиксация через библиотеку `responses` (в CI curl_cffi не установлен →
активен requests-fallback; при установленном curl_cffi сетевые тесты скипаются):

1. `cookies=` реально уходят в запрос (проверка Cookie-заголовка).
2. **Суть бага:** перемежающиеся запросы A→B→A→B — каждый несёт только свой
   hhtoken; server-side `Set-Cookie` аккаунта A не всплывает в запросах B; при
   этом jar аккаунта A сохраняет свои server-cookies между запросами (изоляция —
   не «выбрасывание всех cookies вообще»).
3. Whitebox-идентичность сессий: разные ключи → разные сессии, один ключ → та же,
   `None` → legacy.
4. Legacy-запрос без `cookie_jar_key` продолжает работать (с cookies и без).
5. Флоу `app.hh_negotiations` (`fetch_hh_negotiations_stats`,
   `auto_decline_discards`) передают `cookies` + стабильный `cookie_jar_key` в
   каждый запрос (guard против регресса call sites на shared jar).
6. `set_proxy("")` после серии per-account запросов не ломает следующий запрос и
   не теряет cookies.
