# HH Public OpenAPI Discovery (2026-06-22)

Stored alongside the project so contributors don't need to re-reverse:

- `docs/hh_openapi.yaml` — full OpenAPI 3.0.3 spec, 1.2 MB,
  fetched from `https://api.hh.ru/openapi/specification/public`
  (the URL is embedded in `https://api.hh.ru/openapi/redoc` HTML).

## What we found

### Webhook API (`/webhook/subscriptions`)
- POST: subscribe to push events on a callback URL
- GET: list current subscriptions
- PUT/DELETE `/{subscription_id}` — manage
- **Applicant-side: NOT exposed.** Every action description ends with
  «Событие присылается менеджеру работодателя…», so a regular applicant
  OAuth token cannot register a webhook here.
- Available action types (HR-only):
  - `CHAT_CREATED` / `CHAT_MESSAGE_CREATED`
  - `NEGOTIATION_EMPLOYER_STATE_CHANGE`
  - `NEW_NEGOTIATION_VACANCY` / `NEW_RESPONSE_OR_INVITATION_VACANCY`
  - `VACANCY_PUBLICATION_FOR_VACANCY_MANAGER`
  - `VACANCY_ARCHIVATION` / `VACANCY_CHANGE` / `VACANCY_PROLONGATION`

So the bot's WS-push on `websocket.hh.ru` (already implemented) is
the only push channel applicants get.

### Negotiations / chat (23 endpoints)
Official OAuth alternative to our reverse-engineered chatik.hh.ru:
- `GET /common/chats` — list of chats
- `GET /common/chats/counters/unread`
- `POST /common/chats/{chat_id}/messages` — send (alternative to
  chatik/api/send)
- `PUT /common/chats/{chat_id}/write_possibility` — change chat write
  state (interesting if applicants are allowed to flip it!)
- `POST /common/chats/files/upload_links` + `GET files/conditions`
  — attach files to a chat message
- `POST /common/chats/without_vacancy` — create a free-form chat
- `PUT /common/chats/{chat_id}/leave`
- `PUT /common/chats/{chat_id}/message/{message_id}/read` — explicit
  read-receipt (could give us per-message viewedByOpponent precision)
- `GET /negotiations` — all our applications
- `GET /negotiations/{id}` — detail
- `GET /negotiations/{nid}/test/solution` — **programmatic
  questionnaire/test answer fetch** (huge for the bot's test handling)
- `POST /negotiations/phone_interview` — schedule a phone interview
  programmatically
- `GET /resumes/{resume_id}/negotiations_history`

### dev.hh.ru
- Title: `HeadHunter API` — public dev portal, not a staging server.
- `/admin` — developer "personal cabinet" (where you register OAuth
  applications). Pages through with our applicant cookies; we are
  logged in as user_id 176187251 and offered the «Регистрация нового
  приложения» form.
- Linked sister domains found in `permittedHosts` allowlist:
  hr.zarplata.ru, talantix.ru, career.ru, livehh.ru, joblist.ru,
  dreamjob.ru, jcat.ru, planetahr.ru, ka.hh.ru, hhid.ru,
  rabota.tut.by, jobs.day.az, hh1.az.
- Internal k8s host accidentally exposed in the allowlist:
  `rating-kube.kube.37b.io` (HH's AS-number is 37b).
- Mobile app deep-link schemes: `hh:`, `hhios:`, `hhapp:`, `hhempios:`,
  `jtb:`, `jtbios:`, `jtbapp:`, `jtbempios:`, `jdazi:`.

### Strategic implications for the bot
- Webhook channel is HR-only → no easy upgrade from our current WS push.
- The `/common/chats/{chat_id}/messages` POST + OAuth pairing is a
  cleaner, ToS-compliant send path than chatik/api/send (which we
  reverse-engineered). If our existing `_oauth_apply` flow is in use
  for an account, the same OAuth token works for chat send too.
- `/negotiations/{nid}/test/solution` would let the bot fetch and reuse
  past test answers programmatically — currently the bot scrapes them
  from HTML.
- `/common/chats/{chat_id}/message/{message_id}/read` provides per-msg
  read-receipts vs the `viewedByOpponent` boolean we currently surface.
