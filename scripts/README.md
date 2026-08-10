# scripts/ — миграция на mobile flow и сервисные утилиты

Набор stand-alone скриптов для миграции существующих пользователей бота
с web-flow на mobile-flow (OAuth api.hh.ru) и повседневного обслуживания.
Скрипты не трогают код бота; каждый запускается напрямую из любой директории
(внутри сами делают `chdir` в корень репо и подключают `sys.path`).

## Общие соглашения

- **Dry-run по умолчанию**: всё, что пишет на диск, сначала печатает план.
  Реальное выполнение — только с явным флагом `--apply`.
- **`--help`** есть у каждого скрипта (argparse, с примерами).
- Python 3.10+, только stdlib (`mobile_smoke_test.py` дополнительно
  использует `requests` из requirements.txt). `run_e2e_local.sh` — bash.
- Отсутствующие файлы данных (`accounts.json`, `oauth_tokens.json` и т.д.)
  обрабатываются дружелюбно, без traceback.
- Логи — в stdout; секреты в отчёты не попадают.

## Оглавление

| # | Скрипт | Назначение | Запись на диск |
|---|--------|------------|----------------|
| 1 | [migrate_accounts_add_mode.py](#1-migrate_accounts_add_modepy) | Миграция: добавить `"mode"` в accounts/browser_sessions | по `--apply` |
| 2 | [oauth_status_check.py](#2-oauth_status_checkpy) | Диагностика OAuth-токенов аккаунтов | нет (read-only) |
| 3 | [import_dumps_to_cache.py](#3-import_dumps_to_cachepy) | Импорт дампов справочников в оффлайн-кэш | по `--apply` |
| 4 | [mobile_smoke_test.py](#4-mobile_smoke_testpy) | Health-check 10 mobile endpoints | только лог |
| 5 | [rotate_oauth_tokens.py](#5-rotate_oauth_tokenspy) | Ротация токенов, истекающих < 24h | по `--apply` |
| 6 | [backup_data.py](#6-backup_datapy) | Бэкап/восстановление `data/` | по `--apply` |
| 7 | [generate_config_template.py](#7-generate_config_templatepy) | Шаблоны `.env` / config для чистого деплоя | по `--apply` |
| 8 | [run_e2e_local.sh](#8-run_e2e_localsh) | Поднять бота + прогнать e2e-тесты | временный лог |

Рекомендуемый порядок миграции: **6 → 1 → 3 → 2 → 5 → 4**
(бэкап → миграция mode → кэш справочников → диагностика → ротация → smoke-тест).

---

### 1. migrate_accounts_add_mode.py

Добавляет отсутствующее поле `"mode"` (default `"auto"`) в каждую запись
`data/accounts.json` и `data/browser_sessions.json`. Перед записью делает
backup оригиналов в `data/backup/{YYYY-MM-DD}/`; повторный запуск в тот же
день кладёт копии с суффиксом `_HHMMSS`. Существующие значения `mode` не
перезаписывает. Atomic write, chmod 0600.

```bash
python3 scripts/migrate_accounts_add_mode.py                     # dry-run: план
python3 scripts/migrate_accounts_add_mode.py --apply             # mode=auto
python3 scripts/migrate_accounts_add_mode.py --mode mobile --apply
python3 scripts/migrate_accounts_add_mode.py --rollback 2026-08-10          # план отката
python3 scripts/migrate_accounts_add_mode.py --rollback 2026-08-10 --apply  # откат (с автобэкапом)
```

Флаги: `--mode {web,mobile,auto}`, `--apply`, `--rollback YYYY-MM-DD`.
Exit: 0 — успех/нечего делать, 1 — ошибка.

### 2. oauth_status_check.py

Read-only таблица по всем аккаунтам:
`resume_hash | mode | oauth_present | oauth_expires_in | recommended_action`.
Использует `app.oauth.get_oauth_status()` (composite-ключи
`hash::account_key` поддерживаются). Эвристика рекомендуемого действия:
нет hash → «указать resume_hash»; нет записи → «пройти OAuth-flow»;
истёк без refresh → «повторная авторизация»; жив и < 48h (или истёк, но
есть refresh) → «запустить rotate_oauth_tokens.py --apply»; иначе «ок».

```bash
python3 scripts/oauth_status_check.py          # таблица + сводка
python3 scripts/oauth_status_check.py --json   # машиночитаемый вывод
```

Флаги: `--json`. Exit: 0 всегда (кроме битого accounts.json → 1).

### 3. import_dumps_to_cache.py

Копирует дампы справочников HH mobile API (`scratchpad/dumps/*.json`)
в `data/cache/dictionaries/`, пишет TTL-метаданные в `_meta.json`
(`sha256`, `size`, `source`, `imported_at`, `expires_at`). Каждый файл
валидируется (размер > 0 + валидный JSON); невалидные — WARN и пропуск.
Без `--force-refresh` свежие файлы (sha256 совпал, TTL жив) пропускаются.
Source ищется автоматически: `<repo>/scratchpad/dumps`, затем дамп-директория
в claude-scratchpad; можно задать явно.

```bash
python3 scripts/import_dumps_to_cache.py                 # dry-run: план
python3 scripts/import_dumps_to_cache.py --apply         # импорт (TTL 30 дней)
python3 scripts/import_dumps_to_cache.py --apply --ttl-days 7 --force-refresh
python3 scripts/import_dumps_to_cache.py --apply --source /path/to/dumps
```

Флаги: `--source DIR`, `--ttl-days N` (30), `--force-refresh`, `--apply`.
Exit: 0 — успех, 1 — source не найден.

### 4. mobile_smoke_test.py

Берёт первый живой OAuth-токен из `data/oauth_tokens.json` и делает
10 GET-запросов к api.hh.ru: `/me`, `/counters/user`,
`/negotiations_statistic/mine`, `/vacancies/possible_job_offers`,
`/negotiations`, `/saved_searches/vacancies`, `/vacancies/favorited`,
`/vacancies/blacklisted`, `/dictionaries`, `/areas`. Выводит таблицу
`endpoint | status | ms | ok?` (ok = status < 400) и дописывает лог в
`data/mobile_smoke_YYYYMMDD.log`. Если mobile-endpoint вернул 406,
повторяет с mobile-заголовками (`ru.hh.android/26.28.1` +
`x-force-app-access: true`) и помечает `(mobile-hdrs)`.

```bash
python3 scripts/mobile_smoke_test.py                        # первый живой токен
python3 scripts/mobile_smoke_test.py --token-key 'abc123::main'
python3 scripts/mobile_smoke_test.py --base-url https://api.hh.ru --timeout 15
```

Флаги: `--base-url`, `--token-key`, `--timeout` (10s), `--log-dir` (data/).
Exit: 0 — все ok, 1 — есть падения, 2 — нет файла/живого токена.
Единственный скрипт, который ходит в сеть (только GET).

### 5. rotate_oauth_tokens.py

Dry-run: читает `data/oauth_tokens.json` напрямую и печатает таблицу
`key | expires_at | осталось | refresh_token? | вердикт` + сводку
(total / уникальных refresh_token / ok / needs refresh / expired /
без refresh_token). Composite-ключи дедуплицируются по refresh_token
(plain-копии помечаются `(dup)`).
`--apply`: вызывает штатный `app.oauth.refresh_oauth_tokens_proactive()`
для токенов с остатком < порога (per-key locks, fallback на второй
client_id, запись на диск) и печатает статистику checked/refreshed/failed.

> Примечание: в брифе упоминался `oauth._refresh_token()` — такой функции
> в `app/oauth.py` нет; используется штатный механизм proactive-refresh.

```bash
python3 scripts/rotate_oauth_tokens.py                        # dry-run
python3 scripts/rotate_oauth_tokens.py --threshold-hours 48   # другой порог
python3 scripts/rotate_oauth_tokens.py --apply                # реальный refresh (HTTP!)
```

Флаги: `--apply`, `--threshold-hours N` (24). Exit: 0 — успех
(включая failed>0 с warning), 1 — ошибка самого скрипта.

### 6. backup_data.py

Бэкап всей `data/` в tarball `backup_YYYYMMDD_HHMMSS.tar.gz`
(default `backups/` в корне репо). Исключает логи (`*.log`) и вложенные
`backup/`/`cache/`; пути в архиве относительные к `data/`.
`--restore TARBALL` восстанавливает (перед `--apply` автоматически делает
backup текущего состояния и печатает его путь); защита от path traversal
в именах внутри архива.

```bash
python3 scripts/backup_data.py                    # dry-run: что войдёт
python3 scripts/backup_data.py --apply            # реальный бэкап
python3 scripts/backup_data.py --include-logs --apply
python3 scripts/backup_data.py --restore backups/backup_20260810_120000.tar.gz         # план
python3 scripts/backup_data.py --restore backups/backup_20260810_120000.tar.gz --apply # восстановить
```

Флаги: `--restore TARBALL`, `--out DIR`, `--include-logs`, `--apply`.
Exit: 0 — успех/нечего делать, 1 — ошибка.

### 7. generate_config_template.py

Генерирует шаблоны для деплоя с чистой конфигурацией:

- `.env.template` (корень репо) — все найденные в коде env-переменные
  (`HH_BOT_HOST/PORT/UNSAFE_EXPOSE/API_KEY/ALLOWED_ORIGINS`, `HH_PROXY`,
  `LLM_PROXY`, `HH_IMPERSONATE`, `HH_OAUTH_CLIENT_ID/_SECRET[_2]`,
  `HH_CHATIK_BASE`) с русскими комментариями и пустыми секретами;
- `data/config.template.json` — все ключи с ДЕФОЛТАМИ класса `Config`
  (значения пользователя не копируются) + объект `_doc` с описаниями.

Защита от утечек: `llm_api_key` и прочие секреты — только плейсхолдеры.

```bash
python3 scripts/generate_config_template.py           # dry-run в stdout
python3 scripts/generate_config_template.py --apply   # записать оба файла
python3 scripts/generate_config_template.py --apply --force  # перезаписать
```

Флаги: `--apply`, `--force`. Exit: 0/1.

### 8. run_e2e_local.sh

Поднимает бота на 127.0.0.1 в background (uvicorn), ждёт готовности
(`GET /healthz`, до 30s), прогоняет `pytest tests/e2e/`, затем убивает
бота (trap на EXIT/INT/TERM; при наличии `setsid` — вся process group).
Exit code скрипта = exit code pytest.

Модуль приложения автодетектится: `app.main:app`, если файл существует,
иначе `app.routes:app` (текущий реальный entrypoint); переопределение —
env `APP_MODULE`. Порт — `E2E_PORT` (default 8000), занятость порта
проверяется до старта. Если `tests/e2e/` отсутствует — SKIP и exit 0
(с `--strict` — exit 1); проверка выполняется до запуска сервера.

```bash
bash scripts/run_e2e_local.sh                # CI/локально
bash scripts/run_e2e_local.sh --strict       # падать без tests/e2e/
bash scripts/run_e2e_local.sh --keep-server  # бот остаётся (PID в выводе)
E2E_PORT=8100 bash scripts/run_e2e_local.sh
```

Env: `APP_MODULE`, `E2E_PORT`, `UVICORN_EXTRA_ARGS`, `PYTHON_BIN`.
Exit: 0 — тесты прошли (или SKIP), 1 — ошибка/тесты упали, 2 — неверные аргументы.
