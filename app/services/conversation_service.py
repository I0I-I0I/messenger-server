from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.models import Conversation, ConversationCounter, ConversationMember, User


class ConversationPayload(TypedDict):
    id: str
    type: str
    updated_at: datetime
    last_message_preview: str | None
    last_message_at: datetime | None
    member_ids: list[int]


def _conversation_member_ids(db: Session, conversation_ids: list[str]) -> dict[str, list[int]]:
    if not conversation_ids:
        return {}

    rows = db.execute(
        select(ConversationMember.conversation_id, ConversationMember.user_id).where(
            ConversationMember.conversation_id.in_(conversation_ids)
        )
    ).all()

    result: dict[str, list[int]] = {conversation_id: [] for conversation_id in conversation_ids}
    for conversation_id, user_id in rows:
        result.setdefault(conversation_id, []).append(user_id)
    return result


def require_membership(db: Session, *, user_id: int, conversation_id: str) -> None:
    member = db.get(ConversationMember, {"conversation_id": conversation_id, "user_id": user_id})
    if member is None:
        raise APIError(status_code=404, code="conversation_not_found", message="Conversation not found")


def list_user_conversations(db: Session, user_id: int) -> list[ConversationPayload]:
    conversation_rows = db.scalars(
        select(Conversation)
        .join(ConversationMember, ConversationMember.conversation_id == Conversation.id)
        .where(ConversationMember.user_id == user_id)
        .order_by(func.coalesce(Conversation.last_message_at, Conversation.updated_at).desc())
    ).all()

    conversation_ids = [conversation.id for conversation in conversation_rows]
    member_map = _conversation_member_ids(db, conversation_ids)

    payload: list[ConversationPayload] = []
    for conversation in conversation_rows:
        payload.append(
            {
                "id": conversation.id,
                "type": conversation.type,
                "updated_at": conversation.updated_at,
                "last_message_preview": conversation.last_message_preview,
                "last_message_at": conversation.last_message_at,
                "member_ids": member_map.get(conversation.id, []),
            }
        )
    return payload


def get_or_create_direct_conversation(db: Session, *, user_id: int, other_user_id: int) -> ConversationPayload:
    if user_id == other_user_id:
        raise APIError(status_code=400, code="invalid_target", message="Cannot create direct conversation with yourself")

    other_user = db.get(User, other_user_id)
    if other_user is None:
        raise APIError(status_code=404, code="user_not_found", message="User not found")

    candidate_ids_subquery = (
        select(ConversationMember.conversation_id)
        .where(ConversationMember.user_id.in_([user_id, other_user_id]))
        .group_by(ConversationMember.conversation_id)
        .having(func.count() == 2)
        .having(func.count(distinct(ConversationMember.user_id)) == 2)
        .subquery()
    )

    existing = db.scalar(
        select(Conversation)
        .where(Conversation.id.in_(select(candidate_ids_subquery.c.conversation_id)))
        .where(Conversation.type == "direct")
    )

    if existing is not None:
        member_map = _conversation_member_ids(db, [existing.id])
        return {
            "id": existing.id,
            "type": existing.type,
            "updated_at": existing.updated_at,
            "last_message_preview": existing.last_message_preview,
            "last_message_at": existing.last_message_at,
            "member_ids": member_map.get(existing.id, []),
        }

    conversation = Conversation(type="direct")
    db.add(conversation)
    db.flush()

    db.add_all(
        [
            ConversationMember(conversation_id=conversation.id, user_id=user_id),
            ConversationMember(conversation_id=conversation.id, user_id=other_user_id),
            ConversationCounter(conversation_id=conversation.id, next_seq=1),
        ]
    )
    db.commit()
    db.refresh(conversation)

    return {
        "id": conversation.id,
        "type": conversation.type,
        "updated_at": conversation.updated_at,
        "last_message_preview": conversation.last_message_preview,
        "last_message_at": conversation.last_message_at,
        "member_ids": [user_id, other_user_id],
    }
