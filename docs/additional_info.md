# Project Summary for Codex

**Overview**
This is an Expo (React Native) messenger client built with `expo-router`. The app is intentionally offline-first: the UI reads from local SQLite only, and all writes go through a local outbox. The current implementation is fully local (no live backend), but the repo includes architecture docs for a future REST + WebSocket backend.

**Tech Stack**
- Expo + React Native + `expo-router`
- SQLite via `expo-sqlite`
- State: `zustand`
- Storage: `@react-native-async-storage/async-storage`

**Repo Map (important paths)**
- `src/app`: Expo Router screens and layouts.
- `src/db`: SQLite setup, schema, and migrations.
- `src/db/queries`: Raw SQL query functions for each table.
- `src/repository`: Repository layer mapping DB rows to domain models and coordinating multi-step DB changes.
- `src/usecases`: Application-level use cases (auth, chats, messages, users).
- `src/sync`: Outbox processing (local retry logic).
- `src/state`: Zustand session store and UI state.
- `src/domain`: Types, ids, and validators.
- `src/service`: Mock data used for DB seeding only.
- `frontend.md`: Frontend architecture rules (SQLite as single source of truth).

**Database (SQLite) Details**
Database initialization lives in `src/db/index.ts` and runs on app bootstrap via `initDb()` in `src/state/useSessionStore.ts`. It enables `PRAGMA foreign_keys = ON` and `PRAGMA journal_mode = WAL`, applies schema migrations, then seeds if empty.

Schema defined in `src/db/schema.ts`:
- `users`
  - `id` (PK), `username` (unique), `display_name`, `avatar_url`, `created_at`, `updated_at`, `password_hash`
- `conversations`
  - `id` (PK), `user_a`, `user_b`, `created_at`, `updated_at`, `last_message_preview`, `last_message_at`, `unread_count`
  - Conversation id is deterministic: `min(userA,userB)__max(userA,userB)`.
- `messages`
  - `id` (PK), `conversation_id` (FK), `sender_id`, `content`, `created_at`, `status` (`pending|sent|failed`), `server_echo` (0/1)
  - Index on `(conversation_id, created_at DESC)`.
- `outbox`
  - `id` (PK), `type`, `payload_json`, `created_at`, `attempts`, `next_retry_at`

Migrations: `DB_VERSION = 2`. On schema mismatch, the DB is dropped and recreated. Seeding uses `src/service/mockData.ts` to populate users, conversations, and starter messages.

**Repository Layer (DB Access Pattern)**
The data access flow is: `usecases` → `repository` → `db/queries` → SQLite.

Key repositories:
- `src/repository/userRepository.ts`
  - `createUser` writes to `users` and sets an avatar URL.
  - `getUserAuthByUsername` reads password hash from SQLite.
- `src/repository/chatRepository.ts`
  - `listChatsForUser` joins conversation info with user and last message.
  - `findOrCreateDirectChat` uses deterministic conversation ids.
- `src/repository/messageRepository.ts`
  - `enqueueSendMessage` inserts a `pending` message, updates conversation preview, and enqueues an outbox job.
  - `markMessageAsSent/Failed` updates status.
- `src/repository/sessionRepository.ts`
  - Uses AsyncStorage (`src/session/session.ts`) to persist current user id.

**Outbox and Message Flow**
- `sendMessage` in `src/usecases/messages.ts` enqueues the message, then calls `processOutboxOnce`.
- `src/sync/outboxProcessor.ts` processes `outbox` entries. For `send_message`, it currently marks the message as `sent` immediately and removes the outbox item. On repeated failures (after 5 attempts), it marks the message as `failed`.

**Run Locally**
- `pnpm install`
- `pnpx expo start`
