from __future__ import annotations

import json
import logging

from app.models import RealtimeOutboxEvent
from app.realtime.connection_manager import ConnectionManager
from app.realtime.protocol import event_frame

logger = logging.getLogger(__name__)


class RealtimePublisher:
    def __init__(self, connection_manager: ConnectionManager) -> None:
        self._connection_manager = connection_manager

    async def publish(self, event: RealtimeOutboxEvent) -> int:
        decoded_payload = json.loads(event.payload_json)
        if not isinstance(decoded_payload, dict):
            raise ValueError("Realtime event payload_json must decode to an object")

        seq = decoded_payload.get("seq")
        occurred_at = decoded_payload.get("occurred_at")
        payload = decoded_payload.get("payload")
        if not isinstance(seq, int) or not isinstance(occurred_at, str) or not isinstance(payload, dict):
            raise ValueError("Realtime event payload_json is missing required fields")

        frame = event_frame(
            event_type=event.event_type,
            event_id=event.event_id,
            conversation_id=event.conversation_id,
            seq=seq,
            occurred_at=occurred_at,
            payload=payload,
        )
        delivered = await self._connection_manager.fanout_conversation(event.conversation_id, frame)
        logger.debug(
            "Realtime event published event_id=%s type=%s conversation_id=%s delivered=%s",
            event.event_id,
            event.event_type,
            event.conversation_id,
            delivered,
        )
        return delivered
