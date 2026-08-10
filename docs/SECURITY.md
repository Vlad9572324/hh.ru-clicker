# Защита данных

Этот dashboard обрабатывает credentials и персональные данные. По умолчанию
держите его на одном доверенном компьютере и публикуйте порт только на loopback.

## Что и где хранится

| Файл в `data/` | Содержимое |
|---|---|
| `accounts.json` | настройки аккаунтов, имя, `resume_hash`, параметры поиска |
| `browser_sessions.json` | cookies и метаданные browser sessions |
| `oauth_tokens.json` | OAuth access/refresh tokens и сроки действия |
| `config.json` | общие настройки, mobile auth config и LLM credentials |

Файлы находятся локально: в bind-mounted `./data` или Docker volume, который вы
настроили. Само приложение не синхронизирует их в облако; обращения к hh.ru и
выбранному LLM-провайдеру, конечно, являются внешней передачей. Не добавляйте
`data/`, backup или debug logs в git и облачные папки.

## Секреты и логи

`app.logging_utils._mask()` оставляет короткий префикс и заменяет хвост
звёздочками; helper применяется к телефонам, токенам, email, OTP и паролям в
чувствительных auth-сценариях. Безопасный пример телефона: `+7*** *** 37**`,
имени: `Тестовый Пользователь`, hash: `xxxx…hash`.

Маскирование — дополнительная защита, не основание публиковать лог. Диагностика
может содержать URL, фрагменты ответов и контекст ошибок. Перед передачей файла
просмотрите `data/debug.log*` и `data/diag.log`, удалите PII и credentials.

## Сетевой доступ и API-key

Обычная конфигурация публикует `127.0.0.1:8000`. Non-loopback bind запрещён без
непустого `HH_BOT_API_KEY`; для осознанного внешнего bind также требуется
`HH_BOT_UNSAFE_EXPOSE=1`. Контейнерное исключение разрешает слушать `0.0.0.0`
внутри контейнера только при host-side публикации на loopback.

```yaml
environment:
  HH_BOT_API_KEY: "replace-with-a-long-random-secret"
  HH_BOT_UNSAFE_EXPOSE: "1"
```

Передавайте ключ заголовком `X-API-Key`. Не помещайте его в URL: query strings
попадают в историю и access logs, а изменяющие запросы query-key не принимают.
Используйте reverse proxy с TLS, firewall и отдельной аутентификацией.

`GET`, `POST` и `DELETE /api/backup` **всегда** требуют API-key, даже если
глобальный `HH_BOT_API_KEY` пуст. Backup включает cookies и LLM/OAuth secrets —
храните его зашифрованным и удаляйте после восстановления.

## HTTP-защита

Middleware добавляет:

- `X-Frame-Options: DENY`;
- `X-Content-Type-Options: nosniff`;
- `Referrer-Policy: no-referrer`;
- Content Security Policy, ограничивающую источники скриптов, стилей,
  соединений, изображений, форм и frame ancestors.

Эти headers снижают риск clickjacking, MIME sniffing и утечки referrer, но не
заменяют TLS и аутентификацию.

## Изоляция аккаунтов

Каждый запрос с account identity получает собственную пару HTTP sessions через
`cookie_jar_key`. Cookie jar аккаунта A не используется для аккаунта B; fallback
с `curl_cffi` на `requests` остаётся в том же per-account jar. Реестр ограничен
LRU-лимитом. Не копируйте вручную cookies между записями.

## OAuth и OTP

- Mobile refresh token обычно имеет TTL около 14 суток; access token обновляется
  заранее/лениво. Refresh сериализован per-user lock, чтобы конкурентные worker
  не инвалидировали token family.
- После окончательного истечения или отзыва выполните OTP снова.
- Пять неверных OTP включают блокировку на 15 минут отдельно для телефона;
  новый запрос кода не сбрасывает lockout.
- CAPTCHA должен пройти пользователь на странице HH. Не автоматизируйте обход.

## Удаление всех локальных данных

Сначала убедитесь, что вы находитесь в каталоге проекта и вам не нужен backup.
Команды необратимо удаляют volume, `data/` и локальные images проекта:

```bash
docker-compose down -v
rm -rf data/
docker images --format '{{.Repository}}:{{.Tag}}' | grep '^hh-bot-' | xargs -r docker rmi
```

Последняя команда эквивалентна удалению `hh-bot-*`, но сначала формирует точный
список. Если compose использует другое имя image/volume, проверьте
`docker-compose config`, `docker volume ls` и `docker images` вручную. Также
удалите экспортированные backup, screenshots и копии логов.

## Ответственность

Бот автоматизирует действия на hh.ru. Пользователь отвечает за соблюдение ToS,
законов о персональных данных, разрешённую частоту запросов и содержание
автоматических сообщений. Не используйте проект для обхода CAPTCHA, ограничений
сервиса или доступа к чужим аккаунтам.
