from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class ConnectionContext:
    connection_id: str
    user_id: str
    websocket: WebSocket
    outgoing_queue: asyncio.Queue[dict[str, object]]
    writer_task: asyncio.Task[None] | None
    subscriptions: set[str] = field(default_factory=set)


class ConnectionManager:
    def __init__(self, *, max_subscriptions_per_connection: int) -> None:
        self._max_subscriptions_per_connection = max_subscriptions_per_connection
        self._connections: dict[str, ConnectionContext] = {}
        self._connections_by_user: dict[str, set[str]] = {}
        self._connections_by_conversation: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def register(self, websocket: WebSocket, *, user_id: str) -> ConnectionContext:
        connection_id = str(uuid.uuid4())
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=200)
        context = ConnectionContext(
            connection_id=connection_id,
            user_id=user_id,
            websocket=websocket,
            outgoing_queue=queue,
            writer_task=None,
        )

        async with self._lock:
            self._connections[connection_id] = context
            self._connections_by_user.setdefault(user_id, set()).add(connection_id)
            context.writer_task = asyncio.create_task(self._writer_loop(connection_id))
        logger.info("WebSocket connection registered connection_id=%s user_id=%s", connection_id, user_id)
        return context

    async def unregister(self, connection_id: str, *, close_socket: bool = True, close_code: int = 1000) -> None:
        async with self._lock:
            context = self._connections.pop(connection_id, None)
            if context is None:
                return

            user_connections = self._connections_by_user.get(context.user_id)
            if user_connections is not None:
                user_connections.discard(connection_id)
                if not user_connections:
                    self._connections_by_user.pop(context.user_id, None)

            for conversation_id in list(context.subscriptions):
                conversation_connections = self._connections_by_conversation.get(conversation_id)
                if conversation_connections is not None:
                    conversation_connections.discard(connection_id)
                    if not conversation_connections:
                        self._connections_by_conversation.pop(conversation_id, None)
            context.subscriptions.clear()

        current_task = asyncio.current_task()
        if context.writer_task is not None and context.writer_task is not current_task:
            context.writer_task.cancel()
            try:
                await context.writer_task
            except asyncio.CancelledError:
                pass

        if close_socket:
            try:
                await context.websocket.close(code=close_code)
            except Exception:
                logger.debug("WebSocket already closed connection_id=%s", connection_id)
        logger.info("WebSocket connection unregistered connection_id=%s user_id=%s", connection_id, context.user_id)

    async def _writer_loop(self, connection_id: str) -> None:
        while True:
            async with self._lock:
                context = self._connections.get(connection_id)
            if context is None:
                return

            try:
                payload = await context.outgoing_queue.get()
                await context.websocket.send_json(payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "WebSocket writer failed connection_id=%s user_id=%s error=%s",
                    connection_id,
                    context.user_id,
                    exc,
                )
                await self.unregister(connection_id, close_socket=False)
                return

    async def send(self, connection_id: str, payload: dict[str, object]) -> bool:
        async with self._lock:
            context = self._connections.get(connection_id)

        if context is None:
            return False

        try:
            context.outgoing_queue.put_nowait(payload)
            return True
        except asyncio.QueueFull:
            logger.warning("Slow WebSocket client disconnected connection_id=%s", connection_id)
            await self.unregister(connection_id, close_socket=True, close_code=1013)
            return False

    async def fanout_conversation(self, conversation_id: str, payload: dict[str, object]) -> int:
        async with self._lock:
            connection_ids = list(self._connections_by_conversation.get(conversation_id, set()))

        delivered = 0
        for connection_id in connection_ids:
            if await self.send(connection_id, payload):
                delivered += 1
        return delivered

    async def subscribe(self, connection_id: str, conversation_ids: list[str]) -> None:
        normalized = list(dict.fromkeys(conversation_ids))
        if not normalized:
            return

        async with self._lock:
            context = self._connections.get(connection_id)
            if context is None:
                return

            projected_total = len(context.subscriptions.union(normalized))
            if projected_total > self._max_subscriptions_per_connection:
                raise ValueError("Subscription limit exceeded")

            for conversation_id in normalized:
                context.subscriptions.add(conversation_id)
                self._connections_by_conversation.setdefault(conversation_id, set()).add(connection_id)

    async def unsubscribe(self, connection_id: str, conversation_ids: list[str]) -> None:
        normalized = list(dict.fromkeys(conversation_ids))
        if not normalized:
            return

        async with self._lock:
            context = self._connections.get(connection_id)
            if context is None:
                return

            for conversation_id in normalized:
                context.subscriptions.discard(conversation_id)
                conversation_connections = self._connections_by_conversation.get(conversation_id)
                if conversation_connections is not None:
                    conversation_connections.discard(connection_id)
                    if not conversation_connections:
                        self._connections_by_conversation.pop(conversation_id, None)

    async def connection_count(self) -> int:
        async with self._lock:
            return len(self._connections)
