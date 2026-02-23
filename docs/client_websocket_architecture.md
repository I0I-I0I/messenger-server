# Client WebSocket Architecture (Expo/React Native)

## 1. Purpose
This document defines how to implement client-side WebSocket realtime for the Expo messenger while preserving offline-first guarantees:
- UI reads from SQLite only.
- REST + `/v1/sync/changes` remain correctness paths.
- WebSocket is latency optimization for committed server events.

Scope for v1 in this document:
- Durable events only: `message.created`, `conversation.updated`.
- No typing/read-receipt client implementation in v1.

## 2. Backend Contract (Already Implemented)
- Endpoint: `wss://<host>/v1/ws`
- Auth:
  - Preferred: `Authorization: Bearer <access_token>`
  - Fallback: `?access_token=<jwt>`
- Inbound commands:
  - `{ "op": "subscribe", "conversation_ids": ["..."] }`
  - `{ "op": "unsubscribe", "conversation_ids": ["..."] }`
  - `{ "op": "ping", "ts": 1700000000000 }`
- Outbound frames:
  - `connection.welcome`
  - `ack`
  - `pong`
  - `error`
  - `message.created`
  - `conversation.updated`

## 3. Required Client Modules
Add these modules in the Expo app repository:

- `src/transport/ws/types.ts`
  - WS command/event TypeScript types
- `src/transport/ws/client.ts`
  - Socket lifecycle, connect/disconnect, send/receive, event listeners
- `src/sync/realtimeSync.ts`
  - Applies durable events into SQLite via repositories
- `src/sync/reconnect.ts`
  - Exponential backoff + jitter policy
- `src/usecases/realtime.ts`
  - Session-level start/stop orchestration

Integrate with existing:
- `src/sync/messageSync.ts`
- `src/sync/outboxProcessor.ts`
- repository/query layer for SQL writes

## 4. Type Contracts

### 4.1 Commands
```ts
export type WsCommand =
  | { op: "subscribe"; conversation_ids: string[] }
  | { op: "unsubscribe"; conversation_ids: string[] }
  | { op: "ping"; ts?: number };
```

### 4.2 Base Events
```ts
export type WsWelcomeEvent = {
  type: "connection.welcome";
  connection_id: string;
  user_id: string;
  server_time: string;
  heartbeat_sec: number;
  protocol_version: number;
};

export type WsAckEvent = {
  type: "ack";
  op: "subscribe" | "unsubscribe";
  ok: true;
  details?: { conversation_ids?: string[] };
};

export type WsPongEvent = {
  type: "pong";
  ts?: number;
};

export type WsErrorEvent = {
  type: "error";
  error: {
    code:
      | "UNAUTHORIZED"
      | "TOKEN_EXPIRED"
      | "FORBIDDEN_CONVERSATION"
      | "INVALID_COMMAND"
      | "RATE_LIMITED"
      | "INTERNAL_ERROR";
    message: string;
    details?: unknown;
  };
};
```

### 4.3 Durable Realtime Events
```ts
export type MessageCreatedEvent = {
  type: "message.created";
  event_id: string;
  conversation_id: string;
  seq: number;
  occurred_at: string;
  payload: {
    id: string;
    sender_id: string;
    client_message_id: string;
    content: string;
    created_at: string;
  };
};

export type ConversationUpdatedEvent = {
  type: "conversation.updated";
  event_id: string;
  conversation_id: string;
  seq: number;
  occurred_at: string;
  payload: {
    id: string;
    updated_at: string;
    last_message_preview: string | null;
    last_message_at: string | null;
  };
};

export type WsServerEvent =
  | WsWelcomeEvent
  | WsAckEvent
  | WsPongEvent
  | WsErrorEvent
  | MessageCreatedEvent
  | ConversationUpdatedEvent;
```

## 5. SQLite Changes (Client)
In the client schema/migration layer, update `messages` and indexes:

- `messages.client_message_id TEXT`
- `messages.server_id TEXT`
- `messages.server_seq INTEGER`
- `messages.server_created_at TEXT`

Indexes/constraints:
- unique `server_id` (where non-null)
- unique `(conversation_id, server_seq)` (where non-null)
- index `(conversation_id, server_seq DESC)`

Optional:
- `sync_cursors(conversation_id PRIMARY KEY, last_seq INTEGER NOT NULL)`

## 6. Lifecycle and Data Flow

### 6.1 Start Sequence
1. Session restore/login succeeds and access token is available in memory.
2. Start WS client.
3. Wait for `connection.welcome`.
4. Subscribe to active conversation IDs (currently open or visible threads).
5. Keep periodic ping (or rely on server timeout + lightweight app heartbeat loop).

### 6.2 Stop Sequence
- On logout/app teardown:
  - close socket
  - clear subscriptions
  - reset reconnect timers

### 6.3 Reconnect Sequence
1. On close/error, schedule reconnect using backoff with jitter:
   - `1s, 2s, 4s, 8s, 15s, 30s` cap
2. If auth failed (`UNAUTHORIZED`, `TOKEN_EXPIRED`), run single-flight refresh before reconnect.
3. After reconnect and resubscribe, immediately call `/v1/sync/changes` to fill missed gaps.

## 7. Event Application Rules (Critical)
Never apply WS payload directly to component state. Apply into SQLite through repository functions only.

### 7.1 `message.created`
Algorithm:
1. Look for local pending message with same `(sender_id == me, client_message_id)`.
2. If found:
   - set `status = sent`
   - set `server_id = payload.id`
   - set `server_seq = seq`
   - set `server_created_at = payload.created_at`
   - normalize content/timestamps to server values
3. If not found:
   - insert remote message row with server fields
4. Ensure idempotency:
   - if duplicate event arrives, uniqueness on `server_id` or `(conversation_id, server_seq)` must prevent duplicate insert.

### 7.2 `conversation.updated`
- Upsert `last_message_preview`, `last_message_at`, and server-updated timestamp fields on conversation row.
- Ignore stale update if local row already has newer server state.

## 8. Repository API Additions (Client)
Add explicit methods to avoid ad-hoc SQL in transport layer:

- `reconcilePendingMessageFromRealtime(event: MessageCreatedEvent, meId: string): Promise<void>`
- `upsertRemoteMessageFromRealtime(event: MessageCreatedEvent): Promise<void>`
- `applyConversationUpdatedFromRealtime(event: ConversationUpdatedEvent): Promise<void>`
- `getConversationIdsForRealtimeSubscribe(): Promise<string[]>`

## 9. WebSocket Client Behavior

### 9.1 `src/transport/ws/client.ts`
Responsibilities:
- Build URL from env (`wss` for production).
- Attach auth header when supported by runtime; fallback to query token.
- Parse incoming frames with runtime guards.
- Expose callbacks:
  - `onEvent(event)`
  - `onStatusChange(status)`
  - `onError(error)`
- Queue outbound commands only when socket is open.

### 9.2 Error Handling
Map WS errors to actions:
- `UNAUTHORIZED` / `TOKEN_EXPIRED`:
  - invoke token refresh coordinator
  - reconnect with new token
- `FORBIDDEN_CONVERSATION`:
  - remove conversation from active subscription set
- `RATE_LIMITED`:
  - pause command sends for cooldown window
- `INVALID_COMMAND`:
  - log + metrics; fix caller behavior

## 10. Integration with Outbox and REST Sync
- Outbox remains the only durable write path from client.
- WS never sends durable message create commands in v1.
- When outbox sends `POST /messages`, local row stays pending until REST response and/or WS `message.created` reconciliation.
- `/sync/changes` remains final source for missed updates after reconnect/background/offline periods.

## 11. Security and Operational Rules
- Use `wss` in production.
- Keep access token short-lived.
- Keep refresh token in secure storage.
- Redact tokens from logs and analytics events.
- Cap subscription set size on client to active conversations.

## 12. Testing Checklist

### Unit
- WS message parser and event guards
- reconnect backoff sequence + jitter bounds
- pending-to-sent reconciliation by `client_message_id`
- duplicate durable event idempotency
- auth refresh single-flight behavior under concurrent reconnect attempts

### Integration
- connect -> subscribe -> receive `message.created` -> SQLite updated
- disconnect during traffic -> reconnect -> `/sync/changes` closes gap
- expired token -> refresh -> reconnect works without user-visible data loss

### Manual
- offline send then online recovery with no duplicates
- two devices in same conversation keep ordering by `server_seq`
- WS unavailable: app still works with REST sync/outbox only

## 13. Rollout Plan (Client)
1. Add schema fields + migration.
2. Implement WS transport and type guards.
3. Implement realtime SQLite merge in sync layer.
4. Wire session lifecycle start/stop.
5. Add reconnect + forced catch-up sync.
6. Run integration/manual scenarios above.

## 14. Non-Negotiable Guarantees
- UI source of truth remains SQLite.
- REST + `/sync/changes` remain correctness path.
- WS remains additive latency path only.
