# Messenger Architecture (FastAPI Backend + Expo Offline-First Client)

## Summary
- This repository is currently a backend-only FastAPI service for messenger APIs.
- The mobile/web client architecture (Expo/React Native) is documented from `additional_info.md` and is currently offline-first/local-only.
- Integration target remains strict offline-first: UI reads from SQLite only; network writes into SQLite through sync/outbox flows.
- Backend is implemented with SQLite + SQLAlchemy and designed so it can move to Postgres later.

## Current State

### Repository Snapshot (This Repo)
- Stack: Python, FastAPI, SQLAlchemy, Pydantic, JWT auth.
- Root layout:
  - `app/main.py`
  - `app/core/`
  - `app/db/`
  - `app/models/`
  - `app/schemas/`
  - `app/api/v1/`
  - `app/services/`
  - `tests/`
- Entrypoints:
  - API app: `app/main.py`
  - Runner: `main.py`
- Test status baseline:
  - `tests/test_auth.py`
  - `tests/test_messages.py`

### Backend Features Already Implemented
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

## Architecture Principles
- Offline-first is non-negotiable:
  - UI reads from local SQLite only.
  - Network layer never becomes UI source of truth directly.
- Consistent API envelope:
  - Success: `{ "data": ... }`
  - Error: `{ "error": { "code": string, "message": string, "details"?: any } }`
- Idempotency for sends:
  - Message send is deduped by `(sender_id, client_message_id)`.
- Predictable ordering:
  - Server assigns per-conversation `seq` via `conversation_counters`.

## Backend Design (FastAPI)

### Directory Structure
- `app/main.py` - app bootstrap, lifespan init, CORS, router mounting.
- `app/core/` - settings, errors/envelope handlers, security, rate limiting.
- `app/db/` - SQLAlchemy engine/session/base + DB init.
- `app/models/` - ORM entities.
- `app/schemas/` - request/response schemas.
- `app/api/v1/` - routers (`auth`, `users`, `conversations`, `messages`, `sync`).
- `app/services/` - business logic (`auth_service`, `conversation_service`, `message_service`).
- `tests/` - integration/unit-style API tests.

### Data Model (SQLite Now, Postgres-Friendly)
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
  - Unique constraints:
    - `(sender_id, client_message_id)`
    - `(conversation_id, seq)`
- `conversation_counters`
  - `conversation_id`, `next_seq`

### Auth and Security
- Password hashing with Argon2 (`passlib`).
- JWT short-lived access token.
- Rotating refresh tokens:
  - Raw refresh token is never stored.
  - SHA-256 hash is stored in `refresh_tokens.token_hash`.
  - Refresh flow revokes old token and links replacement via `replaced_by_token_id`.
- Input validation via Pydantic.
- Auth route rate limiting (in-memory limiter).
- CORS is configured and should be locked down by environment in production.

## API Contracts (v1)

### Envelope
- Success:
```json
{ "data": { } }
```
- Error:
```json
{ "error": { "code": "string", "message": "string", "details": {} } }
```

### Auth
- `POST /v1/auth/register`
  - Request: `username`, `display_name?`, `password`
  - Response: `user`, `tokens`
- `POST /v1/auth/login`
  - Request: `username`, `password`
  - Response: `user`, `tokens`
- `POST /v1/auth/refresh`
  - Request: `refresh_token`
  - Response: rotated `tokens`
- `POST /v1/auth/logout`
  - Request: `refresh_token`
  - Response: `{ "ok": true }`

### Conversations and Messages
- `POST /v1/conversations/direct`
  - Request: `other_user_id`
  - Behavior: return existing DM or create new DM.
- `POST /v1/conversations/{id}/messages`
  - Request: `client_message_id`, `content`
  - Behavior: idempotent create by sender + client message id.

### Sync
- `GET /v1/sync/bootstrap`
  - Returns `me`, `conversations`, `recent_messages`.
- `GET /v1/sync/changes?after_seq_by_conversation=...`
  - Incremental message pull per conversation, keyed by last seen `seq`.

## Expo/React Native Current Architecture (from `additional_info.md`)

### Current Frontend Stack
- Expo + React Native + `expo-router`
- SQLite (`expo-sqlite`)
- Zustand
- AsyncStorage

### Current Frontend Module Map
- `src/app` - routes/screens
- `src/db` - SQLite init/schema/migrations
- `src/db/queries` - raw SQL queries
- `src/repository` - data mapping and multi-step DB operations
- `src/usecases` - app usecases
- `src/sync` - outbox processing
- `src/state` - session/UI stores
- `src/domain` - domain types/validators
- `src/service` - mock seed data

### Current SQLite Schema (Frontend)
- `users`
- `conversations`
  - deterministic direct conversation id: `min(userA,userB)__max(userA,userB)`
- `messages`
  - includes local delivery `status` (`pending|sent|failed`), `server_echo`
- `outbox`
  - queued operations with retry metadata

### Current Message/Outbox Behavior
- Send flow enqueues a local pending message and an outbox job.
- Outbox processor currently marks `send_message` as sent locally (no live backend call yet).
- Retry and failure status management are local-first.

## Backend <-> Expo Integration Plan

### Transport Layer to Add in Frontend
- `src/transport/rest/client.ts`
- `src/transport/rest/auth.ts`
- `src/transport/rest/conversations.ts`
- `src/transport/rest/messages.ts`

### Token Handling Contract
- Access token in memory.
- Refresh token in secure storage.
- Single-flight refresh coordination to prevent parallel refresh storms.

### Sync Layer to Add/Extend
- `src/sync/bootstrap.ts`
  - hydrate SQLite from `/v1/sync/bootstrap`
- `src/sync/messageSync.ts`
  - pull incremental changes via `/v1/sync/changes`
- `src/sync/outboxProcessor.ts`
  - call send endpoint, reconcile local rows with server identifiers

### Frontend Schema Additions Needed for Server Reconciliation
- `messages` add:
  - `client_message_id`
  - `server_id`
  - `server_seq`
  - `server_created_at`
- `conversations` add:
  - `server_updated_at` (optional)
- `outbox.payload_json` should include server request payload fields.

## Important Public Interfaces and Type Changes
- Backend API paths are root-based and implemented under `app/api/v1/*`.
- Contract fields required across client/server:
  - `client_message_id` for idempotency
  - `seq` for ordering/sync cursor
  - server reconciliation fields: `server_id`, `server_seq`, `server_created_at`
- Auth contract:
  - JWT access token + rotating refresh token.

## Testing and Validation

### Backend (Now)
- Unit-level auth/security checks:
  - password hashing verify path
  - refresh token rotation behavior
- Integration-level API checks:
  - auth register/login/refresh/logout
  - message send/list
  - idempotent message resend returns existing message

### Frontend (Required During Integration)
- Unit tests:
  - refresh coordination (single-flight)
  - outbox reconciliation and retry logic
  - sync merge behavior into SQLite
- Manual scenarios:
  - offline send -> reconnect -> sent + reconciled IDs/seq
  - duplicate retry -> no duplicate server message
  - expired access token -> refresh -> request succeeds

## Rollout Plan
- Phase 1 (complete): backend MVP APIs and auth/idempotency foundation.
- Phase 2: Expo transport + sync integration against current backend.
- Phase 3: optional WebSocket realtime layer without violating offline-first rules.

## Assumptions and Defaults
- No end-to-end encryption in v1.
- REST is source of correctness; realtime is additive.
- SQLite remains initial persistence for both backend dev and frontend local state.
- Backend remains deployable as a single service behind reverse proxy TLS/HSTS.
