# Tests

```bash
pip install pytest
python3 -m pytest
```

Покрытие сосредоточено на pure-функциях и местах, где аудит нашёл регрессы:

| Файл | Что проверяет | Защищает от |
|---|---|---|
| `test_classify_apply.py` | `classify_apply_response()` — классификация ответа HH popup | C5: 200 = "sent" без проверки тела (фолс-позитивы на test-required/limit/already) |
| `test_questionnaire.py` | `_parse_questionnaire_rich()` — radio/checkbox/select labels | M2: label_map keyed by id, lookup by value → "да/нет" вместо реальных меток |
| `test_safe_cast.py` | `_safe_cast()` для CONFIG-полей | M0a: dynamic `setattr(CONFIG, k, type(old)(v))` с type confusion |
| `test_url_safety.py` | `_is_safe_llm_base_url()`, `_detect_base_url()` | SSRF в `/api/llm_detect`; правильная авто-детекция Gemini/Anthropic |
| `test_llm_dedup_persist.py` | `upsert_interview()` + `get_replied_keys()` round-trip | C4: после рестарта повторные ответы работодателям |
| `test_ws_origin.py` | `_ws_origin_allowed()` | CSWSH: bind 127.0.0.1 не спасает от ws:// атаки из браузера |

55 тестов. На локальной машине запуск <1с.

## Что не покрыто (пока)

- Async HTTP-флоу (`send_response_async`, `fill_and_submit_questionnaire`) — нужны mock'ы aiohttp. Pure-классификатор `classify_apply_response` вынесен и покрыт.
- LLM API integration (`generate_llm_reply`) — нужны mock'ы OpenAI client. Покрыта только валидация ответа в hh_apply.
- Frontend (`static/js/app.js`) — нужен node + jsdom. `esc()` критично, осталось без покрытия.

## Что нашли сами тесты

При первом запуске тест `test_llm_dedup_persist` показал `RuntimeError: release unlocked lock`
в `_save_*_async` функциях — module reload в фикстуре заменял `_save_*_lock` на новый
объект, и фоновый поток падал. Зафиксил capture lock локально (см. `app/storage.py`).
