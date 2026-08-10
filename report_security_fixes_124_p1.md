# Security fixes: P1 findings по итогам `report_codex_review_sec124.md`

Дата: 2026-08-10
Worktree: `/tmp/security-fix-124` (branch `fix/security-critical-124`, база `b3bba5a`)
Метод: 4 параллельных subagent-а с дизъюнктными скоупами файлов; git commits не делались.
Итог тестов: **`pytest -q`: 248 passed, 2 skipped** (baseline до фиксов: 218 passed, 1 skipped). Стабильность: 3 полных прогона подряд + 5 стресс-прогонов новых security-тестов без единого падения.

Оба skip — средовые, не связаны с фиксами:
- `tests/test_container_bind_smoke.py` — docker-демон недоступен в этом окружении (compose-вариант smoke; subprocess-вариант проходит);
- `tests/test_paused_reason.py` — требует полный BotManager-сетап (предсуществующий skip).

---

## [CRITICAL] #4 — refresh сериализован по `resume_hash`, а ротируемый token разделяется между resume → split-brain

**Файлы:** `app/oauth.py` (+106/−34), новый `tests/test_oauth_refresh_concurrency.py` (4 теста).

**Фикс — lock по владельцу refresh_token (identity token family), а не по resume:**
- Новый `_refresh_lock_key(cached, resume_hash)`:
  - mobile-запись с `mobile_user_id` → `user:<uid>` — один lock на все резюме пользователя;
  - legacy `mobile_otp` без user_id → общий fallback `mobile-otp:shared-family` (консервативная сериализация всей family);
  - браузерные (не разделяемые) токены → `resume:<hash>` как было. Префиксы исключают коллизии пространств ключей.
- `import_mobile_tokens()` сохраняет `mobile_user_id` (= `me["id"]`) в каждую запись family; оба refresh-пути (lazy и proactive) переносят его в новые записи при ротации, чтобы привязка lock'а к владельцу переживала ротацию.
- **CAS под lock'ом (оба пути):** после захвата family-lock запись перечитывается под `_oauth_lock`; если `refresh_token` сменился относительно предъявленного до lock'а — сетевой вызов со старым (уже ротированным) токеном НЕ делается, переиспользуется результат соседа; в сеть всегда идёт токен из актуальной записи, а не из snapshot'а.
- Proactive path: skip записи, удалённой (invalidate) пока ждали lock; гонка двух concurrent proactive-циклов закрыта тем же family-lock'ом + CAS (`seen_refresh` остаётся лишь дедупом внутри одного вызова).
- Транзакционность: точечная запись + `_propagate_refresh_token()` идут последовательно под одним family-lock'ом; `_save_oauth_tokens()` ВНЕ `_oauth_lock` (ограничение issue #19 — deadlock — сохранено).

**Тест:** `threading.Barrier`, 10 потоков на 2+ resume-ключах с общим R1; мок-транспорт ротирует токен (первый вызов R1 → R2, повторные R1 → invalid_grant). Assert'ы: R1 ушёл в сеть ровно 1 раз; все записи family (plain + composite) сошлись к R2 в памяти и на диске; ни одного ложного auth failure. Негативный контроль: на pre-fix коде все 4 теста падают (ловят split-brain). Детерминизм: 13+ прогонов у агента + 5 интеграционных без падений.

## [HIGH] #6 — OTP lockout обходился новым `/request-code` через 60s

**Файлы:** `app/mobile_auth.py` (+47), `tests/test_otp_lockout.py` (+5 тестов), `tests/test_mobile_auth.py` (+3 теста).

**Фикс — lockout по времени, не снимаемый выдачей нового кода:**
- `login()` при 5-й неудаче пишет и `locked_until`, и `last_lockout_at` (момент старта блокировки).
- Новый `_otp_locked_until(state)` = `max(locked_until, last_lockout_at + OTP_LOCKOUT_SECONDS)` (TTL 15 min): lockout не теряется даже при переписывании state без `locked_until`; совместимо с legacy-state.
- `request_code()` ПЕРЕД throttle/дневным лимитом проверяет lockout: активен → `MobileAuthError(429, retry_after=...)`; новый код не выдаётся, к HH не обращаемся, attempts/challenge/state не трогаются (raise до любой записи, под `_otp_lock`). Смена phone/email не обходит — state глобален, проверка до любых действий.
- После истечения TTL — прежнее поведение: новый код, `attempts=0`. 60s resend-throttle и дневной лимит не изменены.
- Роуты не менялись: `/request-code` и `/verify` уже сериализуют `retry_after` из `MobileAuthError`.

**Тесты:** brute-force через request-code/смену phone (всё 429 в пределах 15 min, HH не вызывается, state на диске не изменён); истечение TTL (за 1s до конца ещё 429, после — успех и верификация нового кода); throttle вне lockout; lockout переживает замену state и распознаётся из legacy-state. Время — через monkeypatch часов.

**Бонус того же finding'а #5 (файл принадлежал этому скоупу):** `HHMobileClient.__init__` больше не глотает сбой egress-механизма: если `HH_PROXY` задан, но его не удалось применить → `MobileAuthError(503)` (fail-closed), а не тихий `_proxy = ""` с прямым выходом. Пустой HH_PROXY — как и раньше легитимный режим без прокси. (+3 теста.)

## [HIGH] #5 — прямые `requests.*` к hh.ru в обход HH_PROXY

**Файлы:** `app/routes/accounts.py`, `app/routes/debug.py`, `app/hh_resume.py`, новый `tests/test_hh_egress_guard.py` (11 тестов).

Найдено и закрыто **12 прямых call-sites** (все cookies jar'ы аккаунтов сохранены, добавлен прокси):
- `accounts.py` (8): questionnaire `/applicant/vacancy_response`, hot leads, `/applicant/negotiations`, POST `/applicant/resumes/clone`, GET `/resume/{hash}`, `/applicant/resumes`, 2 запроса в `_url_preview_compute` (для последнего добавлена проверка hostname: hh.ru/hh.kz-семейство → через прокси, не-hh URL — без HH-прокси).
- `debug.py` (3): `/applicant/resumes` (сырой Cookie-заголовок сохранён), negotiations filter, `/chat/messages`.
- `hh_resume.py` (1, вне исходного списка): `_edit_resume_field` — `requests.Session()` (в т.ч. с `verify=False`) → `HH.get`/`HH.post`; TLS-верификация восстановлена. `fetch_resume_text()` уже ходила через `HH`.

Механизм: замена на синглтон `HH` из `app/hh_http.py` — конвенция проекта: авто-инжект `proxies={"http"/"https": HH_PROXY}`, явные headers (webview UA, X-Xsrftoken, Referer) и cookies сохраняются, Chrome TLS impersonate, requests-fallback тоже с прокси.

**Тесты:** (1) repository-wide AST-guard по `app/**/*.py` — запрещает прямые `requests.*`/`Session().get` к hh.ru/hh_base() вне `hh_http.py` (ловит многострочные вызовы, f-string, `url=`-keyword, session-паттерн); на pre-fix версиях из git корректно детектит все 12 нарушений. (2) Функциональные: `set_proxy("socks5h://singbox:1080")` → запросы исправленных путей уходят с `proxies` и cookies аккаунта (оба транспорта HH), teardown восстанавливает прокси.

Вне скоупа (проверено, не hh.ru или уже fail-closed): `app/routes/llm.py` (LLM-провайдеры, свой `_llm_proxies()`), `hh_apply.py`/`hh_chat.py`/`manager.py` (aiohttp/WS через HH_PROXY по отчёту).

## [MEDIUM/operational] #1 — docker-compose bind ломал доступность дашборда даже с хоста

**Файлы:** `docker-compose.yml`, `web_app.py` (только `_resolve_host()`), `tests/test_backup_requires_key.py` (+6 тестов), новый `tests/test_container_bind_smoke.py`.

**Фикс:**
- `docker-compose.yml`: внутри контейнера `HH_BOT_HOST: "0.0.0.0"` + `HH_BOT_ALLOW_CONTAINER_BIND: "1"`; снаружи `ports: "127.0.0.1:8000:8000"` без изменений. Комментарии: Docker DNAT идёт на container IP, не на container loopback; граница безопасности — host-side loopback publish.
- `web_app.py::_resolve_host()`: новый container opt-in `HH_BOT_ALLOW_CONTAINER_BIND=1` разрешает bind ТОЛЬКО `0.0.0.0` без API-ключа (с WARNING в stderr). Fail-closed сохранён полностью: без opt-in `0.0.0.0` без ключа → RuntimeError (даже при `HH_BOT_UNSAFE_EXPOSE=1`); произвольный non-loopback opt-in НЕ разрешает — по-прежнему ключ + UNSAFE_EXPOSE.
- Empirically: pre-fix код в subprocess-дыме падал ровно с целевым RuntimeError при `HH_BOT_HOST=0.0.0.0`; post-fix тот же сценарий отвечает HTTP 200.

**Smoke test:**
- Вариант A (compose): `docker compose up -d hh-bot` → poll `curl http://127.0.0.1:8000/healthz` → `compose down`; `skipif` нет docker CLI/compose v2/демона — в этом окружении честно скипается (демон недоступен).
- Вариант B (проходит здесь): subprocess `python3 web_app.py` c compose-эквивалентным env (0.0.0.0 + opt-in, свободный порт, ключ/UNSAFE_EXPOSE вычищены), готовность через `/healthz`, assert HTTP 200 + WARNING про opt-in в логе, graceful shutdown в finally.

---

## Покрытие пробелов из секции «Test coverage summary» отчёта

| Пробел отчёта | Закрыт |
|---|---|
| refresh: никакой concurrency/token-family lock проверки | barrier-тест 10 потоков, split-brain assert'ы, CAS-проверка |
| OTP: request-code после lockout, смена identity | 5 новых тестов lockout-TTL + brute-force со сменой phone |
| proxy: нет repository-wide guard и functional proxy-теста | AST-guard + 4 функциональных теста с mock-транспортом |
| compose reachability | compose smoke (skipif docker) + subprocess bind smoke |

## Известные ограничения / вне скоупа этого раунда

- Межпроцессная синхронизация refresh (несколько workers/процессов) не добавлялась — lock'и process-local, как и `_otp_lock`; это зафиксировано в отчёте как свойство модели, в P1-скоуп не входило.
- Parser-edge-cases `base_url` allowlist (IDNA/uppercase/trailing-dot) — finding закрыт ранее (CRITICAL #2), новые кейсы не добавлялись (не P1).
- HEAD/OPTIONS/trailing-slash тесты `/api/backup` — не P1, не делались.
- `README.md`/`Start-HHClicker.ps1` упоминают `HH_BOT_HOST` — документация не обновлялась (вне назначенного скоупа).

## Проверка

```
$ cd /tmp/security-fix-124 && python3 -m pytest -q   # ×3 подряд
248 passed, 2 skipped in ~2.6s
```

Изменённые файлы (git status, коммитов нет):
`app/oauth.py`, `app/mobile_auth.py`, `app/routes/accounts.py`, `app/routes/debug.py`, `app/hh_resume.py`, `web_app.py`, `docker-compose.yml`, `tests/test_backup_requires_key.py`, `tests/test_otp_lockout.py`, `tests/test_mobile_auth.py` + новые `tests/test_oauth_refresh_concurrency.py`, `tests/test_hh_egress_guard.py`, `tests/test_container_bind_smoke.py`.
