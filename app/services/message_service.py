from __future__ import annotations

from datetime import UTC, datetime
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.models import Conversation, ConversationCounter, Message

logger = logging.getLogger(__name__)


PREVIEW_MAX_LENGTH = 280


def list_messages(
    db: Session,
    *,
    conversation_id: str,
    after_seq: int = 0,
    limit: int = 50,
) -> list[Message]:
    logger.debug(
        "Listing messages conversation_id=%s after_seq=%s limit=%s",
        conversation_id,
        after_seq,
        limit,
    )
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
        logger.debug("No conversation ids provided for recent messages fetch")
        return []
    logger.debug("Listing recent messages for %s conversations limit=%s", len(conversation_ids), limit)
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
    sender_id: str,
    client_message_id: str,
    content: str,
) -> tuple[dict[str, object], bool]:
    logger.info(
        "Send message attempt conversation_id=%s sender_id=%s client_message_id=%s",
        conversation_id,
        sender_id,
        client_message_id,
    )
    existing = db.scalar(
        select(Message).where(
            Message.sender_id == sender_id,
            Message.client_message_id == client_message_id,
        )
    )
    if existing is not None:
        if existing.conversation_id != conversation_id:
            logger.warning(
                "client_message_id conflict sender_id=%s client_message_id=%s existing_conversation=%s requested_conversation=%s",
                sender_id,
                client_message_id,
                existing.conversation_id,
                conversation_id,
            )
            raise APIError(
                status_code=409,
                code="client_message_conflict",
                message="client_message_id already used for a different conversation",
            )
        logger.debug(
            "Idempotent send hit sender_id=%s client_message_id=%s message_id=%s",
            sender_id,
            client_message_id,
            existing.id,
        )
        return _serialize_message(existing), False

    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        logger.warning("Conversation not found for send conversation_id=%s", conversation_id)
        raise APIError(status_code=404, code="conversation_not_found", message="Conversation not found")

    counter = db.get(ConversationCounter, conversation_id)
    if counter is None:
        counter = ConversationCounter(conversation_id=conversation_id, next_seq=1)
        db.add(counter)
        db.flush()
        logger.debug("Conversation counter initialized conversation_id=%s", conversation_id)

    seq = counter.next_seq
    counter.next_seq += 1
    logger.debug("Allocated message sequence conversation_id=%s seq=%s", conversation_id, seq)

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
        logger.info("Message persisted message_id=%s conversation_id=%s seq=%s", message.id, conversation_id, seq)
    except IntegrityError:
        logger.warning(
            "IntegrityError on send; attempting idempotent conflict recovery sender_id=%s client_message_id=%s",
            sender_id,
            client_message_id,
        )
        db.rollback()
        existing_after_conflict = db.scalar(
            select(Message).where(
                Message.sender_id == sender_id,
                Message.client_message_id == client_message_id,
            )
        )
        if existing_after_conflict is not None and existing_after_conflict.conversation_id == conversation_id:
            logger.debug(
                "Recovered existing message after conflict message_id=%s",
                existing_after_conflict.id,
            )
            return _serialize_message(existing_after_conflict), False
        raise

    db.refresh(message)
    return _serialize_message(message), True
