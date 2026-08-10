# E2E-тесты GUI (Playwright)

Playwright-тесты веб-интерфейса (`static/index.html` + `static/js/app.js`).
Вся инфраструктура мокается: ни один запрос не уходит наружу.

## Запуск

```bash
cd /tmp/mobile-refactor
python3 -m pytest tests/e2e/<file> --browser=chromium -q
```

Headless — по умолчанию. Все e2e-тесты живут в `tests/e2e/test_*.py`.

> Вложенного `tests/e2e/pytest.ini` НЕТ сознательно: корневым `pytest.ini`
> (`testpaths = tests`, `addopts`, `filterwarnings`) управляет весь набор
> тестов, включая e2e. Второй конфиг создавал бы конфликтующие настройки.

Зависимости — см. `requirements-dev.txt` (pytest, pytest-playwright, playwright);
aiohttp для мок-сервера уже есть в основном `requirements.txt`.

## Как это устроено

Один session-scoped aiohttp-сервер в daemon-потоке (свой asyncio-loop,
bind на port 0 — реальный порт берётся из сокета):

| что | куда |
|---|---|
| `GET /` | `static/index.html` |
| `GET /static/...` | файлы из `static/` |
| `GET /ws` | мок WebSocket-эндпоинт, **без auth** |

Все HTTP-запросы страницы к `/api/*` перехватываются `page.route("**/api/**")`
внутри фикстуры `ui` **до** обращения к серверу и мокируются из `ui.state` /
`ui.data` / `ui.set_response()`. WS-соединение при этом настоящее (страница ↔
мок-сервер).

## Фикстуры

### `static_url` (session)

`str` — базовый URL локального сервера: `http://127.0.0.1:<port>`.

### `ws_server` (session)

Объект управления мок-WS:

- `send_state(state_dict)` — отправить `{"type":"state_update", **state_dict}`
  всем активным соединениям (вызывается из потока тестов через
  `asyncio.run_coroutine_threadsafe` в loop сервера);
- `close_all(code=1000, reason="")` — серверный разрыв активных соединений;
- `received: list[dict]` — все сообщения, полученные от страницы (`sendCmd`),
  за всю сессию.

### `ui` (function)

Главный объект теста:

| поле/метод | описание |
|---|---|
| `ui.page` | Playwright page (фикстура `page` из pytest-playwright) |
| `ui.state` | `dict` — дефолтный снапшот состояния бота (deep copy на каждый тест). Источник для (а) WS при connect и (б) `GET /api/raw/accounts`, `/api/raw/config`. Мутируется **до** `ui.open()` |
| `ui.data` | `dict` — пейлоады ленивых GET-эндпоинтов. Ключи: `applied`, `tests`, `vacancies`, `interviews`, `hr_contacts`, `sessions`, `resume_views` (dict idx→payload), `proxy_info`, `llm_usage`. Мутируется до `ui.open()` или между вызовами |
| `ui.commands` | `list[dict]` — WS-сообщения от страницы (`sendCmd`) за текущий тест |
| `ui.calls` | `list[dict]` — перехваченные HTTP `/api/*` запросы: `{method, path, json}` |
| `ui.page_errors` | `list[str]` — window-level JS-ошибки (`pageerror`) |
| `ui.open()` | `page.goto(static_url)` + ждёт `#conn-dot.connected` и полный первичный рендер (header + карточки аккаунтов). Идемпотентна |
| `ui.push_state()` | отправить текущий `ui.state` через WS (имитация broadcast от бота — UI перерендерится) |
| `ui.close_ws(code=1000)` | серверный разрыв WS (для reconnect-тестов) |
| `ui.set_response(method, path_regex, body=None, status=200)` | override HTTP-ответа; `path_regex` матчится `re.search` по пути |
| `ui.wait_until(predicate, timeout=5, interval=0.05)` | поллинг Python-предиката для асинхронных эффектов |

### Роутинг HTTP-моков (внутри `ui.open()`/`page.route`)

- `GET /api/raw/config` → `ui.state["config"]`
- `GET /api/raw/accounts` → `ui.state["accounts"]` (если ключа нет — `ui.state` целиком)
- `GET /api/applied|tests|vacancies|interviews|hr_contacts|sessions|proxy/info|llm_usage` → соответствующий пейлоад из `ui.data`
- `GET /api/account/<idx>/resume_views` → `ui.data["resume_views"][idx]`
  (отсутствующий idx → `{"stats": {}, "history": []}`)
- остальные `GET` → `404 {"error": "not mocked"}` + запись в `ui.calls`
- любой `POST/PUT/PATCH/DELETE` → `200 {"ok": true}` + запись
  `{method, path, json}` в `ui.calls`; `set_response()` имеет приоритет

## Поведение, о котором нужно знать

- **WS при подключении**: сервер сразу шлёт `ui.state`, зарегистрированный в
  `ui.open()`. `push_state()` шлёт текущее (мутированное) состояние.
- **Второй snapshot в `ui.open()`**: реальный бот шлёт broadcast каждые 0.3с
  (`broadcast_loop` в `app/routes/core.py`), а значения в карточках аккаунтов
  рендерятся только со второго snapshot (`renderAccounts` сначала создаёт
  шаблон карточки, `updateCard` вызывается с повторным snapshot). Поэтому
  `ui.open()` после connect дополнительно делает `push_state()` и ждёт
  заполнения карточки.
- **Автозапросы при загрузке**: через ~800мс после `DOMContentLoaded` страница
  сама делает `GET /api/proxy/info` (для него есть дефолт в `ui.data`).
- **Дефолтный `ui.state`** повторяет форму реального
  `BotManager.get_state_snapshot()` (`app/manager.py`; broadcast в
  `app/routes/core.py`) и поля, читаемые render-функциями `static/js/app.js`:
  1 аккаунт (`idx/name/short/color/status/sent/found_vacancies/
  responses_streak_count/...`), `config` со всеми toggle-ключами из snapshot
  (`use_oauth_apply`, `llm_use_quick_replies`, `llm_auto_send`,
  `hh_ai_letter_first_try`, `related_vacancies_enabled`, `auto_apply_tests`,
  `skip_inconsistent`, `filter_agencies`, `filter_low_competition`, ...),
  `paused=false`, `log` с уровнями info/success/warning/error,
  `recent_responses: []`, `llm_log: []`. Ключей `chat_deduplication`/
  `temp_skip*` в текущем коде нет (проверено grep'ом), поэтому в дефолте их нет.
- **Скриншот на fail**: autouse-хук пишет `tests/e2e/failures/<test_name>.png`
  при падении тела теста (директория создаётся автоматически).
