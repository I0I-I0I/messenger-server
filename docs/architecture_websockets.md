# WebSocket Architecture (Expo Offline-First Client + FastAPI Backend)

## Status
- Backend WebSocket and realtime outbox implementation is complete in this repository.
- Client implementation guidance is documented in `client_websocket_architecture.md`.

## 1. Goals and Constraints

This architecture must follow the existing rules from `backend_architecture.md` and `additional_info.md`:

- UI reads from SQLite only.
- Network never becomes direct UI source of truth.
- REST remains canonical for writes and recovery.
- WebSocket is additive for low-latency updates.
- Message ordering is authoritative by server `seq` per conversation.
- Message send idempotency remains `(sender_id, client_message_id)`.

## 2. Responsibility Split

- REST (`/v1/...`):
  - authoritative writes (`POST /messages`, `MarkRead`, auth refresh)
  - bootstrap and gap recovery (`/v1/sync/bootstrap`, `/v1/sync/changes`)
- WebSocket (`/v1/ws`):
  - realtime push for committed server events
  - lightweight client commands (subscribe, typing, ping)
  - no direct durable write path for messages in v1

Result: if WS fails, app still works via outbox + sync.

## 3. High-Level Runtime Flow

### 3.1 Send Message
1. Client inserts local pending message + outbox row in SQLite.
2. Outbox sends `POST /v1/conversations/{id}/messages` with `client_message_id`.
3. Server commits message with `seq`.
4. Server writes realtime event to outbox-events table in same DB transaction.
5. Event dispatcher publishes `message.created` to WS subscribers.
6. Client upserts event into SQLite and reconciles pending local row.

### 3.2 Receive Message
1. Sender writes via REST.
2. Receiver gets `message.created` over WS.
3. Receiver upserts into SQLite.
4. UI rerenders from SQLite query.

### 3.3 Reconnect/Gaps
1. WS disconnect occurs.
2. Client reconnects with backoff.
3. Client runs `GET /v1/sync/changes?after_seq_by_conversation=...`.
4. Any missed events are merged into SQLite.

## 4. Backend Architecture (FastAPI)

### 4.1 New Backend Modules

Suggested additions:

- `app/api/v1/ws.py`
  - WebSocket endpoint and protocol validation
- `app/realtime/connection_manager.py`
  - user connections, subscriptions, fanout
- `app/realtime/protocol.py`
  - envelope schemas, parse/validate commands
- `app/realtime/publisher.py`
  - publish committed events to active sockets
- `app/realtime/dispatcher.py`
  - background loop reading DB outbox-events and publishing
- `app/services/realtime_service.py`
  - event creation helper called from message/read services

### 4.2 WebSocket Endpoint

- URL: `wss://<host>/v1/ws?access_token=<jwt>` (MVP)
- Auth: same JWT access token as REST.
- On success server sends `connection.welcome`:

```json
{
  "type": "connection.welcome",
  "connection_id": "01HS...",
  "user_id": "u_123",
  "server_time": "2026-02-23T00:00:00Z",
  "heartbeat_sec": 25
}
```

### 4.3 Client -> Server Commands

```json
{ "op": "subscribe", "conversation_ids": ["c1", "c2"] }
{ "op": "unsubscribe", "conversation_ids": ["c1"] }
{ "op": "typing", "conversation_id": "c1", "state": "start" }
{ "op": "typing", "conversation_id": "c1", "state": "stop" }
{ "op": "ping", "ts": 1700000000000 }
```

Server response examples:

```json
{ "type": "ack", "op": "subscribe", "ok": true }
{ "type": "pong", "ts": 1700000000000 }
{ "type": "error", "code": "INVALID_COMMAND", "message": "..." }
```

### 4.4 Server -> Client Event Envelope

```json
{
  "type": "message.created",
  "event_id": "evt_01HS...",
  "conversation_id": "c1",
  "seq": 104,
  "occurred_at": "2026-02-23T00:00:00Z",
  "payload": {
    "id": "msg_uuid",
    "sender_id": "u_2",
    "client_message_id": "cmid_uuid",
    "content": "hello",
    "created_at": "2026-02-23T00:00:00Z"
  }
}
```

Required event types in v1:

- `message.created`
- `message.updated` (optional later)
- `conversation.updated` (last message preview/unread metadata)
- `receipt.read` (if read receipts are implemented)
- `typing` (ephemeral)

### 4.5 Event Production: Transactional Outbox

To avoid lost events between DB commit and WS publish, add a DB table:

- `realtime_outbox_events`
  - `id` (pk)
  - `event_type`
  - `conversation_id`
  - `user_targets_json` (or null for conversation fanout)
  - `payload_json`
  - `created_at`
  - `published_at` nullable
  - `attempts`

Write this outbox row in the same transaction as message insert/read update. A background dispatcher publishes and marks `published_at`.

### 4.6 Delivery Semantics

- Ordering guarantee: per conversation by `seq`.
- Delivery guarantee over WS: at-most-once/best-effort.
- Durability guarantee: provided by REST + `/sync/changes` catch-up.
- Dedupe key on client: `server_id` or `(conversation_id, seq)`.

### 4.7 Scale Path

Phase A (single instance): in-memory `ConnectionManager`.

Phase B (multi instance):
- add Redis pub/sub for cross-instance fanout
- keep DB outbox dispatcher singleton per shard/lease
- optional dedicated realtime worker process

## 5. Frontend Architecture (Expo)

### 5.1 New Frontend Modules

- `src/transport/ws/client.ts`
  - socket lifecycle, parse/serialize protocol
- `src/transport/ws/types.ts`
  - WS command/event types
- `src/sync/realtimeSync.ts`
  - apply WS events into SQLite
- `src/sync/reconnect.ts`
  - backoff and reconnect policy
- `src/usecases/realtime.ts`
  - start/stop connection per session

### 5.2 Connection Lifecycle

1. User session is restored.
2. Start WS with current access token.
3. Send `subscribe` for visible/open conversations (or all user conversations if acceptable).
4. On disconnect: schedule reconnect with exponential backoff + jitter.
5. After reconnect: run `/sync/changes` before trusting live stream.

Recommended backoff: `1s, 2s, 4s, 8s, 15s, 30s (cap)` + jitter.

### 5.3 Event Application Rules (Critical)

- Never write WS payload directly into React state as source of truth.
- Every durable event is applied via repository/SQL upsert.
- UI updates only because SQLite changed.
- `typing` can stay in lightweight zustand UI store (ephemeral, not persisted).

### 5.4 Message Reconciliation

When `message.created` arrives:

1. Find local pending message by `client_message_id` + current user sender context.
2. If found, update row:
  - `status = sent`
  - `server_id`, `server_seq`, `server_created_at`
  - normalize content/timestamps to server values
3. If not found, insert as remote message.
4. Ensure unique constraint prevents duplicate insert on retries.

### 5.5 Token Handling

- Access token in memory.
- Refresh token in secure storage.
- WS auth failures (`401` / `TOKEN_EXPIRED`) trigger single-flight refresh.
- Reconnect WS with new access token after refresh.

### 5.6 Offline Behavior

- If offline: WS down, outbox continues queuing sends locally.
- On online restore:
  - run outbox processor
  - reconnect WS
  - run `/sync/changes` to fill missed updates

## 6. Schema Changes

### 6.1 Frontend SQLite

`messages` table additions (if not already present):

- `client_message_id TEXT`
- `server_id TEXT`
- `server_seq INTEGER`
- `server_created_at TEXT`

Indexes/constraints:

- `UNIQUE(server_id)` where non-null
- `UNIQUE(conversation_id, server_seq)` where non-null
- index on `(conversation_id, server_seq DESC)`

Optional table:

- `sync_cursors(conversation_id PRIMARY KEY, last_seq INTEGER NOT NULL)`

### 6.2 Backend DB

Add `realtime_outbox_events` for transactional event publishing.

## 7. Protocol and Error Contract

WS errors should be structured similarly to REST envelope style:

```json
{
  "type": "error",
  "error": {
    "code": "INVALID_COMMAND",
    "message": "conversation_ids is required"
  }
}
```

Recommended error codes:

- `UNAUTHORIZED`
- `TOKEN_EXPIRED`
- `FORBIDDEN_CONVERSATION`
- `INVALID_COMMAND`
- `RATE_LIMITED`
- `INTERNAL_ERROR`

## 8. Security

- Only `wss` in production.
- Validate membership before allowing `subscribe` to a conversation.
- Rate limit command frequency per connection (`typing`, `subscribe` spam).
- Keep WS access token short-lived.
- Prefer redacting query strings from logs if token is passed via query param.

## 9. Observability

Track metrics:

- active WS connections
- reconnect attempts/user
- event publish latency (DB commit -> WS send)
- outbox dispatcher lag
- sync gap recovery count
- duplicate event drops on client

Log with correlation IDs:

- HTTP message send request id
- generated realtime `event_id`
- WS `connection_id`

## 10. Testing Strategy

### Backend

- Unit:
  - protocol parser validation
  - auth/membership checks for subscribe
  - outbox dispatcher retry behavior
- Integration:
  - POST message creates outbox event
  - event is delivered to subscribed receiver
  - reconnect + `/sync/changes` closes missed gap

### Frontend

- Unit:
  - WS event -> SQLite merge logic
  - pending-to-sent reconciliation by `client_message_id`
  - reconnect backoff + refresh single-flight
- Manual:
  - send while offline -> reconnect -> no duplicates
  - kill WS during heavy chat -> recover via `/sync/changes`
  - two devices same user -> both receive consistent updates

## 11. Incremental Rollout Plan

1. Backend WS skeleton (`/v1/ws`, subscribe, ping/pong).
2. Transactional outbox events from message send path.
3. Frontend WS client + durable event merge into SQLite.
4. Reconnect + forced `/sync/changes` on reconnect.
5. Add typing and read receipts (ephemeral + durable mix).
6. Scale with Redis pub/sub when multiple backend instances are introduced.

## 12. Non-Negotiable Rules

- REST remains source of truth for durable writes.
- WebSocket events are hints for latency, not sole consistency mechanism.
- Any inconsistency is corrected by `/v1/sync/changes`.
- UI continues to read only from SQLite.
