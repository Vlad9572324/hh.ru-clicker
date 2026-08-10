# Архитектура

## Компоненты

```mermaid
flowchart LR
  UI[Dashboard + feature modules] <-->|REST / WebSocket| API[FastAPI routes]
  API --> M[Manager / workers]
  API --> F[HHClient factory]
  M --> F
  F --> A{mode}
  A -->|web| W[WebHHClient]
  A -->|mobile| X[FallbackHHClient]
  A -->|auto + OAuth| X
  A -->|auto, no OAuth| W
  X --> O[MobileHHClient / api.hh.ru]
  X -. supported fallback .-> W
  W --> H[hh.ru + chatik + websocket.hh.ru]
  API --> D[(local data/*.json)]
```

`HHClientBase` задаёт общий контракт. Capability-интерфейсы отделяют операции,
которые существуют только в web или mobile. Фабрика выбирает реализацию по
per-account `mode`; конфигурационный default используется лишь при отсутствии
явного значения.

## Phase 0–5

```mermaid
flowchart TB
  P0[Phase 0: interface, factory, modes] --> P1[Phase 1: auth and transport]
  P1 --> P2[Phase 2: negotiations and chats]
  P2 --> P3[Phase 3: apply and vacancy metadata]
  P3 --> P4[Phase 4: resume, views, status, analysis]
  P4 --> P5[Phase 5: UI integrations and operational hardening]
```

| Фаза | Результат |
|---|---|
| 0 | единый клиент, web adapter, mobile skeleton, factory и режимы |
| 1 | mobile transport, OAuth/OTP, identity и token persistence |
| 2 | переговоры, треды, сообщения, quick replies и chat actions |
| 3 | pre-flight, отклики, related vacancies и employer metadata |
| 4 | резюме, просмотры, skills, job status и анализ |
| 5 | callers/UI переведены на abstraction, realtime и fallback укреплены |

`docs/PHASE_MATRIX.md` сохраняет детальную историческую матрицу методов; этот
документ описывает итоговую систему.

## Fallback chain

```mermaid
sequenceDiagram
  participant C as Consumer
  participant F as Factory/FallbackHHClient
  participant M as Mobile API
  participant W as Web flow
  C->>F: operation(account)
  F->>M: mobile implementation
  alt success or domain error
    M-->>C: result/error
  else unsupported, network, 401/403 or 5xx
    F->>W: same operation
    W-->>C: normalized result
  end
```

Предметные ошибки (`400`, `404`, `409`) обычно возвращаются вызывающему коду и
не скрываются fallback. Web-only операции требуют живых cookies даже у
mobile-аккаунта.

## Realtime

WebSocket HH доставляет chat events, внутренний WS dashboard — snapshots и
счётчики UI. Reconnect использует backoff; polling остаётся резервом. Разрыв WS
не меняет выбранный HH client mode.

## Данные и конкурентность

`data/accounts.json`, `browser_sessions.json`, `oauth_tokens.json` и
`config.json` записываются локально и атомарно. OAuth refresh защищён per-user
lock. Исходящие web-запросы используют отдельный cookie jar на identity
аккаунта; LRU ограничивает число session jars. Полная модель угроз и удаление
данных описаны в [SECURITY.md](SECURITY.md).
