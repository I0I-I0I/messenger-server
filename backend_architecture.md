# Flexible, Scalable, Secure Architecture Plan (Expo + FastAPI + SQLite)

**Summary**
- Keep the offline-first rule: UI reads only from SQLite; network only writes to SQLite + small UI state.
- Introduce a REST transport layer and a sync layer that mirrors server state into SQLite.
- Build a FastAPI backend with JWT access + rotating refresh tokens, strong input validation, and idempotent message send.
- Design schemas and APIs to allow an easy future move to Postgres and WebSockets without changing client logic.

## Current State (Observed)
- Frontend is offline-first with SQLite as source of truth.
- Usecases → repository → db queries → SQLite.
- Outbox exists but currently “marks sent” locally without server.
- Auth is local-only in SQLite.

## Target Architecture Overview
**Frontend**
- UI layer reads SQLite only.
- `sync/` orchestrates all network I/O.
- `transport/rest/` contains fetch-based API client with auth/token refresh.
- Outbox sends queued actions; sync pulls remote changes into SQLite.

**Backend**
- Single FastAPI app (monolith) with modular routers.
- SQLite now; schema designed for Postgres upgrade.
- JWT access tokens + rotating refresh tokens.
- Idempotent send with `client_message_id`.

---

# Backend Design (FastAPI)

## Directory Structure
- `backend/app/main.py` – app bootstrap
- `backend/app/core/` – settings, security, logging
- `backend/app/db/` – SQLAlchemy/SQLModel setup, migrations
- `backend/app/models/` – ORM models
- `backend/app/schemas/` – Pydantic request/response models
- `backend/app/api/v1/` – routers: auth, users, conversations, messages, sync
- `backend/app/services/` – business logic, idempotency, token rotation
- `backend/app/workers/` – optional background tasks (token cleanup, etc.)

## Core Tables (SQLite now, Postgres later)
- `users`  
  `id`, `username`, `display_name`, `password_hash`, `created_at`, `updated_at`
- `refresh_tokens`  
  `id`, `user_id`, `token_hash`, `issued_at`, `expires_at`, `revoked_at`, `replaced_by_token_id`
- `conversations`  
  `id`, `type` (`direct` for now), `created_at`, `updated_at`, `last_message_preview`, `last_message_at`
- `conversation_members`  
  `conversation_id`, `user_id`, `joined_at`, `role`
- `messages`  
  `id` (server UUID), `conversation_id`, `sender_id`, `client_message_id`, `seq`, `content`, `created_at`
  Unique: `(sender_id, client_message_id)`
- `conversation_counters`  
  `conversation_id`, `next_seq` (for reliable per-conversation ordering)

## REST API (v1)
All responses use a consistent envelope:
- Success: `{ "data": ... }`
- Error: `{ "error": { "code": string, "message": string, "details"?: any } }`

### Auth
- `POST /v1/auth/register`
- `POST /v1/auth/login`
- `POST /v1/auth/refresh`
- `POST /v1/auth/logout`  
Access token short-lived; refresh token rotates.

### Users
- `GET /v1/users/me`
- `GET /v1/users/search?query=&limit=`

### Conversations
- `GET /v1/conversations`
- `POST /v1/conversations/direct` with `other_user_id`
  Returns existing or created DM.

### Messages
- `GET /v1/conversations/{id}/messages?after_seq=&limit=`
- `POST /v1/conversations/{id}/messages`
  Body includes `client_message_id`, `content`

### Sync
- `GET /v1/sync/bootstrap`
  Returns `me`, `conversations`, latest messages summary
- `GET /v1/sync/changes?after_seq_by_conversation=...`
  Allows incremental sync without WebSockets

## Security Controls
- Password hashing with Argon2 or bcrypt.
- JWT access token, rotating refresh token stored hashed in DB.
- Input validation with Pydantic and strict size limits (message length).
- Rate limiting for auth endpoints (e.g., IP + user).
- CORS locked to known origins in production.
- TLS terminated at reverse proxy; HSTS enabled.
- Audit log for auth events (optional initially).

---

# Frontend Design (Expo)

## New Modules
- `src/transport/rest/client.ts`
  Fetch wrapper, handles base URL, auth header, JSON errors, retry
- `src/transport/rest/auth.ts`
  login, refresh, logout, register
- `src/transport/rest/messages.ts`
  getMessages, sendMessage
- `src/transport/rest/conversations.ts`
  list, openOrCreateDirect

## Auth + Token Storage
- Access token stored in memory.
- Refresh token stored in `expo-secure-store`.
- Token refresh coordinated to avoid parallel refresh requests.

## Sync Layer
- `src/sync/bootstrap.ts`  
  On login: call `/sync/bootstrap`, hydrate SQLite with users, conversations, recent messages.
- `src/sync/messageSync.ts`  
  Poll when chat is open or app foregrounds. Uses `after_seq`.
- `src/sync/outboxProcessor.ts`  
  Sends `send_message` via REST. On success, update `server_id`, `seq`, `status=sent`.

## SQLite Schema Changes
- `messages` add:
  `server_id`, `server_seq`, `server_created_at`, `client_message_id`
- `conversations` add:
  `server_updated_at` (optional)
- `outbox` payload includes server request data.

## UX/State
- Keep `zustand` minimal (session + UI).
- UI still reads from SQLite only.
- `usecases` remain thin, delegating to repository + sync.

---

# Important Changes to Public APIs/Interfaces/Types
- New REST API contracts described above (`/v1/...`).
- New message fields for server synchronization:
  `client_message_id`, `server_id`, `server_seq`, `server_created_at`.
- Auth tokens:
  Access token (JWT) + refresh token rotation.

---

# Testing and Validation

## Backend
- Unit tests for auth token rotation and password hashing.
- Integration tests for:
  `POST /auth/login`, `POST /auth/refresh`, `POST /messages`, `GET /messages`.
- Idempotency test: same `client_message_id` returns existing message.

## Frontend
- Unit tests for:
  outbox processor, token refresh logic, sync reconciliation.
- Manual scenarios:
  offline send → reconnect → message sent and marked `sent`
  duplicate send retry does not create duplicate message
  token expiry → auto refresh → request succeeds

---

# Rollout Plan
- Phase 1: Backend MVP with auth, users, conversations, messages.
- Phase 2: Frontend REST transport + sync; keep offline-first.
- Phase 3: Add optional realtime channel later (WebSocket) without changing UI.

---

# Assumptions and Defaults
- Auth: JWT + refresh rotation.
- Realtime: REST first, WebSocket soon.
- No end-to-end encryption for v1.
- Backend deployed as a single container/VM behind a reverse proxy.
- SQLite used for initial development; schema supports later Postgres migration.
