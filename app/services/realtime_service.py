from __future__ import annotations

from datetime import UTC, datetime
import json

from sqlalchemy.orm import Session

from app.models import Conversation, Message, RealtimeOutboxEvent
from app.services import user_hydration_service


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.isoformat()


def _enqueue_event(
    db: Session,
    *,
    event_type: str,
    conversation_id: str,
    seq: int,
    occurred_at: datetime,
    payload: dict[str, object],
) -> None:
    event_payload = {
        "seq": seq,
        "occurred_at": _serialize_datetime(occurred_at),
        "payload": payload,
    }
    db.add(
        RealtimeOutboxEvent(
            event_type=event_type,
            conversation_id=conversation_id,
            payload_json=json.dumps(event_payload, separators=(",", ":"), sort_keys=True),
            next_attempt_at=datetime.now(UTC),
        )
    )


def enqueue_message_created(db: Session, *, message: Message) -> None:
    sender_rows = user_hydration_service.fetch_users_by_ids(
        db,
        requester_id=message.sender_id,
        user_ids=[message.sender_id],
        visibility_mode="all",
    )
    if not sender_rows:
        raise RuntimeError("Sender user could not be resolved for realtime payload")
    sender = user_hydration_service.serialize_user_public(sender_rows[0])

    payload: dict[str, object] = {
        "id": message.id,
        "sender_id": message.sender_id,
        "client_message_id": message.client_message_id,
        "content": message.content,
        "created_at": _serialize_datetime(message.created_at),
        "sender": sender,
    }
    _enqueue_event(
        db,
        event_type="message.created",
        conversation_id=message.conversation_id,
        seq=message.seq,
        occurred_at=message.created_at,
        payload=payload,
    )


def enqueue_conversation_updated(db: Session, *, conversation: Conversation, seq: int) -> None:
    payload: dict[str, object] = {
        "id": conversation.id,
        "updated_at": _serialize_datetime(conversation.updated_at),
        "last_message_preview": conversation.last_message_preview,
        "last_message_at": _serialize_datetime(conversation.last_message_at),
    }
    _enqueue_event(
        db,
        event_type="conversation.updated",
        conversation_id=conversation.id,
        seq=seq,
        occurred_at=conversation.updated_at,
        payload=payload,
    )
