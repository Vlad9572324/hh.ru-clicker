# HH.ru Reverse-Engineered API Map

Полная карта API hh.ru, добытая реверс-инженерингом JS-бандлов и SSR-данных.
476 эндпоинтов найдено, протестировано.

---

## Chatik API (chatik.hh.ru)

Полностью открытый внутренний API чатов. Авторизация через куки hh.ru.
Headers: `Origin: https://chatik.hh.ru`, `Referer: https://chatik.hh.ru/`, `X-XSRFToken: {_xsrf}`

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/chatik/api/chats` | GET | Полный список чатов (id, type, unread, lastMessage, resources) |
| `/chatik/api/chat_data?chatId=N` | GET | История чата (messages.items, participants) |
| `/chatik/api/chat_data_by_topic?topicId=N` | GET | Чат по ID топика переговоров |
| `/chatik/api/send` | POST | Отправка `{chatId, idempotencyKey, text}` |
| `/chatik/api/search?query=X` | GET | Поиск по чатам |
| `/chatik/api/unread` | GET | `{unreadCount, unreadSupportCount}` |
| `/chatik/api/counters` | GET | Все счётчики |
| `/chatik/api/participants/me` | GET | Данные текущего юзера |
| `/chatik/api/templates` | GET | Шаблоны сообщений |
| `/chatik/api/settings` | GET | Настройки |
| `/chatik/api/config` | GET | Конфиг (sentryDSN, build, apiHost, staticHost) |
| `/chatik/api/features` | GET | Feature flags |
| `/chatik/api/typing?chatId=N` | GET | Статус набора |
| `/chatik/api/pinned` | GET | Закреплённые чаты |
| `/chatik/api/archived` | GET | Архивные чаты |
| `/chatik/api/muted` | GET | Замьюченные |
| `/chatik/api/blocked` | GET | Заблокированные |
| `/chatik/api/drafts` | GET | Черновики |
| `/chatik/api/health` | GET | Healthcheck |
| `/chatik/api/status` | GET | Статус сервиса |

**Важно**: `/chat/messages?page=N` (hh.ru) — пагинация СЛОМАНА, всегда 20 чатов. `/chatik/api/chats` — правильная замена.

---

## Applicant APIs (hh.ru)

### Работающие ✅

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/shards/user_statuses/job_search_status?status=X` | PUT | Смена статуса поиска (active_search, looking_for_offers, not_looking_for_job) |
| `/applicant/vacancy_response/popup?vacancyId=N` | GET | Данные отклика: `resumeInconsistencies`, `test.hasTests`, `letterRequired`, `type` |
| `/applicant/vacancy_response/popup` | POST | Отправка отклика (FormData: resume_hash, vacancy_id, letter, lux) |
| `/shards/applicant/resumes` | GET | Все резюме с _attributes (percent, status, isSearchable, canPublishOrUpdate) |
| `/shards/applicant/artifacts/all` | GET | Фото и файлы `{images: [...]}` |
| `/shards/applicant/negotiations/possible_job_offers` | GET | Потенциальные офферы от работодателей |
| `/shards/vacancy/register_interaction` | POST | Аналитика `{vacancyId, interactionType: view\|click\|response\|show}` |
| `/shards/hhpro_ai_letter` | POST | AI сопроводительное письмо `{resumeHash, vacancyId}` (async) |
| `/shards/hhpro_ai_check_status` | GET | Опрос результата AI `?resumeHash=X&vacancyId=Y` |
| `/shards/resume/search` | GET | Поиск резюме (видим конкурентов) `?text=X&area=1&order_by=relevance` |
| `/shards/search/resume/clusters` | GET | Все фильтры HR с количеством `?text=X&area=1` |
| `/shards/vacancy/counts` | GET | Количество вакансий по запросу |
| `/shards/notifications/mark_as_viewed` | POST | Пометить уведомления прочитанными |
| `/shards/recommended_skills` | POST | Рекомендуемые навыки (400 — формат не найден) |

### Защищённые капчей ⚠️

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/applicant/resumes/touch` | POST | Поднятие резюме (302 → captcha) |
| `/shards/resume/edit/visibility` | POST | Видимость резюме (500) |
| `/shards/applicant/profile/update` | POST | Обновление профиля (500) |

---

## Public API (api.hh.ru)

Работает без авторизации:

| Endpoint | Описание |
|----------|----------|
| `/suggests/skill_set?text=X` | Автодополнение навыков |
| `/suggests/professional_roles?text=X` | Автодополнение ролей |
| `/professional_roles` | Полный каталог профессиональных ролей |
| `/dictionaries` | Все справочники HH (schedule, employment, experience, etc.) |

Требуют OAuth2 (hhtoken не работает как Bearer):
- `/me`, `/resumes/mine`, `/negotiations`, `/vacancies`

---

## SSR Data (HTML `<template id="HH-Lux-InitialState">`)

Каждая страница HH содержит JSON с полными данными:

| Страница | Ключ SSR | Данные |
|----------|----------|--------|
| `/resume/{hash}` | `applicantResume` | 30K chars — все поля, conditions, fieldStatuses, percent |
| `/applicant/resumes` | `applicantResumesStatistics` | search_shows, views, invitations за 7 дней |
| `/vacancy/{id}` | `vacancyView` | Полные данные вакансии, работодатель, навыки, зарплата |
| `/applicant/negotiations` | `applicantNegotiations` | Топик-лист с actions |
| Любая страница | `experiments` | A/B тесты для аккаунта |
| Любая страница | `features` | Feature flags |
| `/applicant/settings` | `xsrfToken`, `session` | Токены, сессия |

---

## Ключевые находки

### resumeInconsistencies
При GET `/applicant/vacancy_response/popup?vacancyId=N` HH возвращает:
```json
{
  "resumeInconsistencies": {
    "resume": [{
      "inconsistencies": {
        "inconsistency": [{
          "type": "EXPERIENCE",
          "required": "WORK_EXPERIENCE_FROM_3_YEAR_TO_6_YEAR",
          "actual": "WORK_EXPERIENCE_FROM_1_YEAR_TO_3_YEAR"
        }]
      }
    }]
  }
}
```
HR видит это как ⚠️ — снижает шансы. Можно фильтровать перед откликом.

### AI Cover Letter (бесплатно)
Эксперимент `hhpro_ai_cover_letter_v2: experiment` включён для аккаунта.
`POST /shards/hhpro_ai_letter` → 200, async генерация, poll через `hhpro_ai_check_status`.

### Аналитика рынка
`/shards/search/resume/clusters` для "тестировщик" в Москве:
- 35 411 активно ищут работу
- 254 669 хотят удалёнку
- 888 576 с фото (из 2.5М)
- Топ навыки: Пользователь ПК (240К), Работа в команде (206К)

---

## Справочники HH

### schedule
| ID | Название |
|----|----------|
| fullDay | Полный день |
| shift | Сменный график |
| flexible | Гибкий график |
| remote | Удалённая работа |
| flyInFlyOut | Вахтовый метод |

### experience
| ID | Название |
|----|----------|
| noExperience | Нет опыта |
| between1And3 | От 1 года до 3 лет |
| between3And6 | От 3 до 6 лет |
| moreThan6 | Более 6 лет |

### resume_access_type
| ID | Название |
|----|----------|
| no_one | Не видно никому |
| whitelist | Видно выбранным работодателям |
| blacklist | Скрыто от выбранных работодателей |
| clients | Видно всем работодателям на hh.ru |
| everyone | Видно всему интернету |
| direct | Доступно только по прямой ссылке |

### applicant_negotiation_status
| ID | Название |
|----|----------|
| active | Активные |
| invitations | Приглашения |
| response | Отклики |
| discard | Отказ |
| interview | Собеседование |
| hired | Выход на работу |

---

## Внутренняя инфраструктура

- **Chatik build**: `1.9.1`
- Internal infrastructure details omitted for security


## 🆕 Discovered 2026-06-22 (Round 2)

### WebSocket push channel (hh-bot уже использует)
- `GET websocket.hh.ru/connection/data?connectionMode=direct&appVersion=X` → `{"url": "wss://websocket.hh.ru/ws/connect?sd=<token>"}` (token включает auth)
- `WebSocket(<url>)` — события: `chat_message_create`, `chat_message_edited`, `chat_message_deleted`, `chat_state_changed`, `chat_participant_action`, `last_viewed_message_change`, `connect`/`disconnect`
- iframe-proxy на `https://websocket.hh.ru/proxy-webapp/index.html` (cross-domain auth)
- Ping раз в 180с (raw text "ping"), reconnect 2-30с до 120 попыток

### Job-search public status (соискатель)
- `PUT /shards/user_statuses/job_search_status?status=<X>` body=пустой → 200 `{}`
- Значения enum: `active_search`, `looking_for_offers`, `accept_offers`, `has_job_offer`, `accepted_job_offer`, `not_looking_for_job`
- `PUT /shards/user_statuses/job_search_status_notification_read?triggerName=X` — отметить уведомление прочитанным

### Resume access type (видимость)
- `POST /shards/resume/edit/visibility` `{hash, accessType: "no_one"}` — единственный путь для `no_one`
- Прочие accessType-значения меняются на странице `/resume/edit/{hash}/visibility` через `/applicant/resume/edit?resume=H` — но требуют валидации (HH вернёт 400 если есть пропущенные поля)
- Enum из `_conditions.accessType.parts[0].string.enum` (per-user): `["clients","whitelist","blacklist","direct","no_one"]` — **никакого `everyone`** в обычном тарифе
- `_conditions` каждого поля резюме = полная схема валидации (mincount, maxcount, status, parts, enum)

### Employer ratings (рейтинг работодателей!)
- `GET /employer_reviews/proxy_components/small_widget?employerId=N` → JSON (~150KB) с `employerReviews`:
  - `totalRating: "4.3"`, `recommendationsPercent: 81`
  - `ratings[6]`: WORKPLACE, TEAM, MANAGEMENT, CAREER, REST_RECOVERY, SALARY (значения "1"-"5")
  - `advantages[]`: топ преимуществ с подсчётом голосов
  - `negativeReviews[]`, `reviews[]` — полные отзывы
  - `reviewsCount`, `negativeReviewsCount`, `staffCount` (`STAFF_COUNT_MORE_10000`), `activityStatus`
  - `aiSummaryIsActive`, `topManagerWords`, `employeeStories`, `awards`, `last3MonthsReviewsInfo`
  - `services.tariff` — какой тариф у работодателя (`STANDARD`, `PAID`, ...)
- `GET /employer_reviews/proxy_components/big_widget?employerId=N` — большой виджет (400 без is_on_employer_page)
- `interviewReviewWizardData` в ответе содержит pre-filled данные про твою negotiation

### Chatik endpoints (расширили)
- `POST /chatik/api/participant_action` `{chatId, actionType: TYPING|NONE}` — индикатор печати
- `POST /chatik/api/send_event` `{chatId, messageId, event, eventParams}` — клик по «event-кнопке» (`buttons[].type==send_event`)
- `GET /chatik/api/quick_replies?chatId=N` → `{quick_replies: [{id, type:"send", text, label, metadata}]}` — HH-AI предложения ответов (типа «Где находится место работы?», «Какая схема оплаты?»)
- `GET /chatik/api/get_or_create_bot_dialog` — создать чат с роботом-рекрутёром
- `GET /chatik/api/notify_chat_opened`, `mark_read`, `notify_admin`, `rate_chat`, `get_link_preview`, `check_link`, `filter_clusters`, `maps/yandex`, `similar_counters`

### SSR-данные на страницах
- `/applicant/negotiations` — `applicantEmployerPoliteness` (% чтения откликов + dаys ответа на работодателя), `applicantEmployerManagersActivity` (онлайн-статус HR), `applicantNegotiationsCounters`, **52 поля** на каждый topic в `applicantNegotiations.topicList[]` (employerManagerId, inboxAvailabilityState, applicantVacancySummaryEnabled, availableTransitions...)
- `/applicant/resumes` — `applicantResumesStatistics`, `applicantSuitableVacancyByResume`, `applicantUserStatuses.jobSearchStatus`, `globalInvitations`, `userStats.{resumes-views, new-applicant-invitations}`
- `/employer/{id}` — `employerInfo` (23 поля: hrBrand, badges, accreditedITEmployer, wantsBeTargetEmployer...), `employerInsiderInterview`, `activeEmployerVacancyCount`
- `userTargeting` (рекламные puids) — gender, age range, salary range, education level, experience years, profession id, region path — всё что HH знает про юзера для таргета

### HH's own competing features (что у HH есть нативно)
- `/shards/autoresponse` + `/shards/autoresponse/statistics` — **HH's native auto-reply** (мы их прямой конкурент)
- `/employer/candidates/ai-assistant` — HH AI помогает HR оценивать кандидатов
- `/employer/candidates/ai-assistant/questions-settings` — кастомные вопросы которые HR задаёт AI
- `/employer/candidates/neuroresponse` + `neuroresponse-statistics` — нейроанализ откликов
- `/employer/auto_invite/disable` — HR может массовый auto-invite
- `applicantPaymentServices` list: `AI_AUTO_RESPONSE_COVER_LETTER`, `AI_COVER_LETTER`, `RESUME_AUDIT`, `RESUME_TARGET_EMPLOYER`, `VACANCY_RESPONSES_SUMMARY`, `COMPLETE_RESUME_INTERVIEW_PRACTICE`, `HH_PRO_SUBSCRIPTION`, etc.

### Micro-frontends (отдельные хосты)
- `career.hh.ru` (Career Platform): `topicInterviewReviewWizard`, `careerNegotiationsBanner`
- `employer-reviews-front.hh.ru` (отзывы): `employerReviewsSmall`, `employerReviewsBig`
- `applicant-services-front.hh.ru` (services): через `/applicant-services/services/connected`
- `mentors.hh.ru`, `skills.hh.ru`, `webcall.hh.ru` — отдельные хосты, гл. редирект через `mf_use_mfp2`

### Что не нашли (404 / закрыто)
- Прямые REST для HR-профиля (`/manager/{id}` и пр. все 404) — данные только через SSR (employer/manager activity)
- `applicant/auto_search` / `applicant/auto_response` — концепции есть в фичах, но прямых URL для AJAX нет
- Свободные ML/recommendations endpoints — закрыты
