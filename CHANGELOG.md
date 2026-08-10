# Changelog

Все значимые изменения проекта документируются в этом файле.

## Unreleased

### Fixed

- fix(security): CRITICAL №3 — cross-account cookie confusion via shared curl_cffi Session
  - `HH.request()` теперь принимает `cookies=` + `cookie_jar_key=`: per-account сессия
    с изолированной cookie jar (LRU-реестр, макс. 100 ключей, thread-safe);
    `cookie_jar_key=None` — legacy общая сессия для запросов без аккаунтного контекста;
    `set_proxy()` очищает реестр сессий.
  - Call sites с аккаунтным контекстом передают `cookie_jar_key=_token_key(acc)`;
    kwargs аддитивные — поведение без них не меняется (breaking: нет).
