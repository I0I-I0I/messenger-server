# Messenger Architecture (FastAPI Backend + Expo Offline-First Client)

## Summary
- Backend is a FastAPI service with SQLite + SQLAlchemy, designed to be Postgres-friendly later.
- Architecture is offline-first end-to-end: UI reads only from local SQLite on client.
- REST remains source of correctness for durable writes and recovery.
- WebSocket is implemented as an additive realtime path for low-latency event delivery.

## Current Backend State (Implemented)

### Stack and Layout
- Stack: Python, FastAPI, SQLAlchemy, Pydantic, JWT auth.
- Key paths:
  - `app/main.py`
  - `app/core/`
  - `app/db/`
  - `app/models/`
  - `app/schemas/`
  - `app/api/v1/`
  - `app/services/`
  - `app/realtime/`
  - `tests/`

### Implemented APIs
- Auth:
  - `POST /v1/auth/register`
  - `POST /v1/auth/login`
  - `POST /v1/auth/refresh`
  - `POST /v1/auth/logout`
- Users:
  - `GET /v1/users/me`
  - `GET /v1/users/search?query=&limit=`
- Conversations:
  - `GET /v1/conversations`
  - `POST /v1/conversations/direct`
- Messages:
  - `GET /v1/conversations/{id}/messages?after_seq=&limit=`
  - `POST /v1/conversations/{id}/messages`
- Sync:
  - `GET /v1/sync/bootstrap`
  - `GET /v1/sync/changes?after_seq_by_conversation=...`
- WebSocket:
  - `WS /v1/ws`

## Architecture Principles
- Offline-first is non-negotiable.
- Consistent HTTP envelope:
  - Success: `{ "data": ... }`
  - Error: `{ "error": { "code": string, "message": string, "details"?: any } }`
- Message idempotency by `(sender_id, client_message_id)`.
- Ordering by server-assigned per-conversation `seq`.
- WS delivery is best-effort; REST + sync provide durable correctness.

## Backend Design

### Modules
- `app/api/v1/`
  - REST routers (`auth`, `users`, `conversations`, `messages`, `sync`)
  - WS router (`ws`)
- `app/services/`
  - business logic (`auth_service`, `conversation_service`, `message_service`, `realtime_service`)
- `app/realtime/`
  - `protocol.py` command parsing + frame builders
  - `connection_manager.py` connection/subscription state and fanout
  - `publisher.py` outbox event to socket fanout
  - `dispatcher.py` background retrying dispatcher for realtime outbox rows

### Data Model
- `users`
  - `id`, `username`, `display_name`, `password_hash`, `created_at`, `updated_at`
- `refresh_tokens`
  - `id`, `user_id`, `token_hash`, `issued_at`, `expires_at`, `revoked_at`, `replaced_by_token_id`
- `conversations`
  - `id`, `type`, `created_at`, `updated_at`, `last_message_preview`, `last_message_at`
- `conversation_members`
  - `conversation_id`, `user_id`, `joined_at`, `role`
- `messages`
  - `id` (UUID), `conversation_id`, `sender_id`, `client_message_id`, `seq`, `content`, `created_at`
  - unique: `(sender_id, client_message_id)`
  - unique: `(conversation_id, seq)`
- `conversation_counters`
  - `conversation_id`, `next_seq`
- `realtime_outbox_events`
  - `id`, `event_id`, `event_type`, `conversation_id`, `payload_json`, `created_at`, `published_at`, `attempts`, `next_attempt_at`, `last_error`

## Auth and Security
- Password hashing: Argon2 (`passlib`).
- JWT short-lived access token.
- Rotating refresh tokens with hashed storage (`SHA-256`).
- Auth rate limiter on auth routes.
- WS security controls:
  - auth required at handshake
  - conversation membership validation on subscribe
  - per-connection command rate limiting
  - max payload size guard
  - idle timeout handling
- CORS is configured and should be environment-restricted in production.
- Production deployment should use TLS (`wss` externally).

## WebSocket Protocol (Implemented)

### Connection
- URL: `ws(s)://<host>/v1/ws`
- Auth:
  - preferred: `Authorization: Bearer <access_token>`
  - fallback: `?access_token=<jwt>`

Server welcome:
```json
{
  "type": "connection.welcome",
  "connection_id": "...",
  "user_id": "...",
  "server_time": "2026-02-23T00:00:00+00:00",
  "heartbeat_sec": 25,
  "protocol_version": 1
}
```

### Client Commands
```json
{ "op": "subscribe", "conversation_ids": ["c1", "c2"] }
{ "op": "unsubscribe", "conversation_ids": ["c1"] }
{ "op": "ping", "ts": 1700000000000 }
```

### Server Frames
```json
{ "type": "ack", "op": "subscribe", "ok": true }
{ "type": "pong", "ts": 1700000000000 }
{ "type": "error", "error": { "code": "INVALID_COMMAND", "message": "..." } }
```

### Durable Event Frames (v1)
- `message.created`
- `conversation.updated`

Example:
```json
{
  "type": "message.created",
  "event_id": "...",
  "conversation_id": "c1",
  "seq": 104,
  "occurred_at": "2026-02-23T00:00:00+00:00",
  "payload": {
    "id": "msg_uuid",
    "sender_id": "u_2",
    "client_message_id": "cmid_uuid",
    "content": "hello",
    "created_at": "2026-02-23T00:00:00+00:00"
  }
}
```

## Realtime Delivery Semantics
- Ordering: per conversation by server `seq`.
- WS delivery: best-effort, at-most-once in transport layer.
- Durability: guaranteed by REST writes + `/v1/sync/changes` catch-up.
- Correctness rule: client must always recover via sync after reconnect/gap.

## Transactional Outbox Flow
1. Client sends `POST /v1/conversations/{id}/messages`.
2. Server allocates `seq`, inserts message.
3. In same transaction, server enqueues `message.created` and `conversation.updated` rows in `realtime_outbox_events`.
4. Dispatcher polls unpublished rows and publishes over active WS subscriptions.
5. On success: mark `published_at`.
6. On failure: increment attempts and schedule retry with exponential backoff.

## Scale Path
- Current mode: single-process in-memory connection manager.
- Ready seam for scale:
  - keep outbox dispatcher and publisher as replaceable runtime components
  - add Redis pub/sub for multi-instance fanout in future
  - optionally run dispatcher as separate worker process

## Client Integration Notes
- Client-side implementation instructions live in `client_websocket_architecture.md`.
- Key integration contract:
  - SQLite remains client source of truth
  - durable WS events are merged into SQLite
  - reconnect must run `/v1/sync/changes`

## Testing Status
Current backend tests include:
- `tests/test_auth.py`
  - hashing and refresh token rotation
- `tests/test_messages.py`
  - idempotent send and sequence behavior
- `tests/test_ws.py`
  - invalid token rejection
  - forbidden subscribe for non-member
  - delivery of `message.created` and `conversation.updated` to subscribed receiver
- `tests/test_realtime_dispatcher.py`
  - successful publish marks row published
  - failure path retries and eventually publishes

## Rollout and Operations
- Existing backend is production-approachable for single-node deployments.
- For multi-node, add shared pub/sub and dispatcher coordination.
- Monitor:
  - active WS connections
  - outbox backlog size
  - publish retries/latency
  - sync catch-up rates after reconnect

## Assumptions and Defaults
- No end-to-end encryption in v1.
- REST and sync remain authoritative.
- WS is additive latency optimization, not correctness dependency.
