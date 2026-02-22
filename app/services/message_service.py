from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.models import Conversation, ConversationCounter, Message


PREVIEW_MAX_LENGTH = 280


def list_messages(
    db: Session,
    *,
    conversation_id: str,
    after_seq: int = 0,
    limit: int = 50,
) -> list[Message]:
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .where(Message.seq > after_seq)
            .order_by(Message.seq.asc())
            .limit(limit)
        ).all()
    )


def list_recent_messages(
    db: Session,
    *,
    conversation_ids: list[str],
    limit: int = 100,
) -> list[Message]:
    if not conversation_ids:
        return []
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id.in_(conversation_ids))
            .order_by(Message.created_at.desc())
            .limit(limit)
        ).all()
    )


def _serialize_message(message: Message) -> dict[str, object]:
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "sender_id": message.sender_id,
        "client_message_id": message.client_message_id,
        "seq": message.seq,
        "content": message.content,
        "created_at": message.created_at,
    }


def send_message(
    db: Session,
    *,
    conversation_id: str,
    sender_id: int,
    client_message_id: str,
    content: str,
) -> tuple[dict[str, object], bool]:
    existing = db.scalar(
        select(Message).where(
            Message.sender_id == sender_id,
            Message.client_message_id == client_message_id,
        )
    )
    if existing is not None:
        if existing.conversation_id != conversation_id:
            raise APIError(
                status_code=409,
                code="client_message_conflict",
                message="client_message_id already used for a different conversation",
            )
        return _serialize_message(existing), False

    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise APIError(status_code=404, code="conversation_not_found", message="Conversation not found")

    counter = db.get(ConversationCounter, conversation_id)
    if counter is None:
        counter = ConversationCounter(conversation_id=conversation_id, next_seq=1)
        db.add(counter)
        db.flush()

    seq = counter.next_seq
    counter.next_seq += 1

    message = Message(
        conversation_id=conversation_id,
        sender_id=sender_id,
        client_message_id=client_message_id,
        seq=seq,
        content=content,
    )
    db.add(message)

    now = datetime.now(UTC)
    conversation.updated_at = now
    conversation.last_message_at = now
    conversation.last_message_preview = content[:PREVIEW_MAX_LENGTH]

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_after_conflict = db.scalar(
            select(Message).where(
                Message.sender_id == sender_id,
                Message.client_message_id == client_message_id,
            )
        )
        if existing_after_conflict is not None and existing_after_conflict.conversation_id == conversation_id:
            return _serialize_message(existing_after_conflict), False
        raise

    db.refresh(message)
    return _serialize_message(message), True
