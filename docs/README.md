# Документация hh.ru-clicker

Индекс документации проекта. Состояние: ветка `refactor/mobile-api`
(HEAD `b3bba5a` = `origin/main` + uncommitted Phase 0 HHClient-абстракции
+ mobile OTP из ветки `pr20`).

## Для юзеров бота

| Документ | О чём |
|---|---|
| [MOBILE_MIGRATION_GUIDE.md](MOBILE_MIGRATION_GUIDE.md) | Пошаговый перевод аккаунта с web-flow (cookies) на mobile OTP (SMS-авторизация api.hh.ru): кнопки UI, поля `mode`/`default_client_mode`, откат на web, ограничения (нет телефона → только web), FAQ |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Типовые проблемы: протух OAuth-токен, mobile API 401 и fallback на web, DDoS-Guard soft-ban, chatik cookies wipe, «200 + SPA HTML вместо JSON», HH-лимиты, опросники, LLM-ошибки + таблица «симптом → секция» |

## Для разработчиков

| Документ | О чём |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Устройство проекта: FastAPI + воркеры + два канала к hh.ru; интерфейс `HHClient` (37 методов), `WebHHClient`/`MobileHHClient`, фабрика `get_client()` и выбор `mode`; два сквозных пути запроса (отклик, WebSocket-push); известные несоответствия Phase 0 |
| [API_REFERENCE.md](API_REFERENCE.md) | Reference по `HHClient`: сигнатура + вызов + форма ответа для всех 37 методов; таблица web/mobile-поддержки с кандидат-эндпоинтами api.hh.ru для фаз 2–4; конвенция ошибок |
| [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) | Все 56 полей `Config` (`app/config.py`): default, смысл, где используется; env-переменные (настоящий override — `HH_PROXY`); детально про `default_client_mode` и поле `mode` аккаунтов/temp-сессий |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Как контрибутить: coding style (FastAPI + vanilla JS без build-step), ветвление (main / refactor/mobile-api / pr-N), формат коммитов, тестирование (pytest + Playwright e2e в `tests/e2e/`), запрет Co-Authored-By трейлеров |

## Реверс-инжиниринг hh.ru

| Файл | О чём |
|---|---|
| [HH_OPENAPI_KEY_FINDINGS.md](HH_OPENAPI_KEY_FINDINGS.md) | Находки по OpenAPI-спеке hh.ru |
| [hh_openapi.yaml](hh_openapi.yaml) | Выгруженная OpenAPI-спека публичного API hh.ru |
| [../HH_API_MAP.md](../HH_API_MAP.md) | Карта API hh.ru, используемая ботом (файл в корне репо) |

## Сопутствующее в корне репо

| Файл | О чём |
|---|---|
| [../CHANGELOG.md](../CHANGELOG.md) | Keep a Changelog: `[Unreleased]` (Phase 0) и `[pr20]` (13 коммитов mobile OTP) |
| [../README.md](../README.md) | Главный README: возможности, скриншоты, быстрый старт, секция «Что нового в refactor/mobile-api» |
| [../AUDIT_REPORT.md](../AUDIT_REPORT.md) | Аудит приложения (4 агента, 3 раунда, 45 находок) |

---

Doc-package собран 2026-08-10 роем из 8 subagent-ов (orchestrator #8,
deepdive → docs). Отчёт о сборке: `scratchpad/deepdive/report_docs.md`.
