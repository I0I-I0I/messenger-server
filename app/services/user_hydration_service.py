from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Iterable, Mapping

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.models import ConversationMember, User

logger = logging.getLogger(__name__)


def _serialize_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.isoformat()


def collect_user_ids_from_conversations(conversations: Iterable[Mapping[str, object]]) -> set[str]:
    user_ids: set[str] = set()
    for conversation in conversations:
        member_ids = conversation.get("member_ids")
        if not isinstance(member_ids, list):
            continue
        for member_id in member_ids:
            if isinstance(member_id, str) and member_id:
                user_ids.add(member_id)
    return user_ids


def collect_user_ids_from_messages(messages: Iterable[object]) -> set[str]:
    user_ids: set[str] = set()
    for message in messages:
        sender_id: object | None
        if isinstance(message, Mapping):
            sender_id = message.get("sender_id")
        else:
            sender_id = getattr(message, "sender_id", None)
        if isinstance(sender_id, str) and sender_id:
            user_ids.add(sender_id)
    return user_ids


def fetch_users_by_ids(
    db: Session,
    *,
    requester_id: str,
    user_ids: Iterable[str],
    visibility_mode: str = "all",
) -> list[User]:
    normalized_ids = [user_id.strip() for user_id in user_ids if isinstance(user_id, str) and user_id.strip()]
    if not normalized_ids:
        return []

    deduped_ids = list(dict.fromkeys(normalized_ids))
    query = select(User).where(User.id.in_(deduped_ids))

    if visibility_mode == "conversation_scoped":
        requester_conversation_ids = select(ConversationMember.conversation_id).where(
            ConversationMember.user_id == requester_id
        )
        visible_user_ids = select(distinct(ConversationMember.user_id)).where(
            ConversationMember.conversation_id.in_(requester_conversation_ids)
        )
        query = query.where((User.id == requester_id) | (User.id.in_(visible_user_ids)))
    elif visibility_mode != "all":
        raise ValueError("Unsupported visibility mode")

    rows = db.scalars(query.order_by(User.username.asc(), User.id.asc())).all()
    logger.debug(
        "Fetched hydrated users requester_id=%s requested=%s returned=%s visibility_mode=%s",
        requester_id,
        len(deduped_ids),
        len(rows),
        visibility_mode,
    )
    return list(rows)


def serialize_user_public(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "created_at": _serialize_datetime(user.created_at),
    }


def attach_members_to_conversations(
    conversations: list[dict[str, object]],
    users_by_id: Mapping[str, dict[str, object]],
) -> list[dict[str, object]]:
    for conversation in conversations:
        member_ids = conversation.get("member_ids")
        if not isinstance(member_ids, list):
            conversation["members"] = []
            continue
        conversation["members"] = [users_by_id[user_id] for user_id in member_ids if user_id in users_by_id]
    return conversations
