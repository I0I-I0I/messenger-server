from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import APIError, success_response
from app.db.session import get_db
from app.models import User
from app.schemas.conversations import ConversationSummary
from app.schemas.messages import MessageRead
from app.schemas.users import UserPublic
from app.services import conversation_service, message_service, user_hydration_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sync", tags=["sync"])


def _parse_after_seq_by_conversation(raw: str | None) -> dict[str, int]:
    if raw is None or raw == "":
        logger.debug("after_seq_by_conversation not provided; defaulting to empty map")
        return {}

    try:
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            raise ValueError("must be an object")
        result: dict[str, int] = {}
        for conversation_id, seq in decoded.items():
            if not isinstance(conversation_id, str) or not isinstance(seq, int) or seq < 0:
                raise ValueError("invalid item")
            result[conversation_id] = seq
        logger.debug("Parsed after_seq_by_conversation JSON for %s conversations", len(result))
        return result
    except json.JSONDecodeError:
        pass
    except ValueError as exc:
        raise APIError(
            status_code=422,
            code="invalid_after_seq",
            message="Invalid after_seq_by_conversation format",
            details={"reason": str(exc)},
        ) from exc

    result: dict[str, int] = {}
    for pair in raw.split(","):
        if not pair.strip():
            continue
        if ":" not in pair:
            raise APIError(
                status_code=422,
                code="invalid_after_seq",
                message="Invalid after_seq_by_conversation format",
            )
        conversation_id, seq_text = pair.split(":", 1)
        conversation_id = conversation_id.strip()
        if not conversation_id or not seq_text.strip().isdigit():
            raise APIError(
                status_code=422,
                code="invalid_after_seq",
                message="Invalid after_seq_by_conversation format",
            )
        result[conversation_id] = int(seq_text.strip())
    logger.debug("Parsed after_seq_by_conversation CSV for %s conversations", len(result))
    return result


@router.get("/bootstrap")
def bootstrap(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info("Sync bootstrap requested user_id=%s", current_user.id)
    conversations = conversation_service.list_user_conversations(db, current_user.id)
    conversation_ids = [conversation["id"] for conversation in conversations]
    recent_messages = message_service.list_recent_messages(db, conversation_ids=conversation_ids, limit=200)
    referenced_user_ids = user_hydration_service.collect_user_ids_from_conversations(conversations)
    referenced_user_ids.update(user_hydration_service.collect_user_ids_from_messages(recent_messages))
    referenced_user_ids.add(current_user.id)
    users = user_hydration_service.fetch_users_by_ids(
        db,
        requester_id=current_user.id,
        user_ids=sorted(referenced_user_ids),
        visibility_mode="conversation_scoped",
    )
    serialized_users = [UserPublic.model_validate(user_hydration_service.serialize_user_public(row)).model_dump(mode="json") for row in users]
    users_by_id = {user["id"]: user for user in serialized_users}

    hydrated_conversations = user_hydration_service.attach_members_to_conversations(
        [dict(conversation) for conversation in conversations],
        users_by_id,
    )
    serialized_conversations = [ConversationSummary.model_validate(conversation).model_dump(mode="json") for conversation in hydrated_conversations]
    serialized_recent_messages = [MessageRead.model_validate(message).model_dump(mode="json") for message in recent_messages]
    me = UserPublic.model_validate(current_user).model_dump(mode="json")

    payload = {
        "me": me,
        "user": me,
        "users": serialized_users,
        "conversations": serialized_conversations,
        "recent_messages": serialized_recent_messages,
        "recentMessages": serialized_recent_messages,
    }
    logger.debug(
        "Sync bootstrap payload user_id=%s conversations=%s recent_messages=%s",
        current_user.id,
        len(serialized_conversations),
        len(payload["recent_messages"]),
    )
    return success_response(payload)


@router.get("/changes")
def sync_changes(
    after_seq_by_conversation: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info("Sync changes requested user_id=%s", current_user.id)
    after_map = _parse_after_seq_by_conversation(after_seq_by_conversation)
    conversations = conversation_service.list_user_conversations(db, current_user.id)
    changed_messages: list[dict[str, object]] = []
    for conversation in conversations:
        conversation_id = conversation["id"]
        after_seq = after_map.get(conversation_id, 0)
        messages = message_service.list_messages(
            db,
            conversation_id=conversation_id,
            after_seq=after_seq,
            limit=100,
        )
        if not messages:
            continue
        changed_messages.extend(MessageRead.model_validate(message).model_dump(mode="json") for message in messages)

    referenced_user_ids = user_hydration_service.collect_user_ids_from_conversations(conversations)
    referenced_user_ids.update(user_hydration_service.collect_user_ids_from_messages(changed_messages))
    referenced_user_ids.add(current_user.id)
    users = user_hydration_service.fetch_users_by_ids(
        db,
        requester_id=current_user.id,
        user_ids=sorted(referenced_user_ids),
        visibility_mode="conversation_scoped",
    )
    serialized_users = [UserPublic.model_validate(user_hydration_service.serialize_user_public(row)).model_dump(mode="json") for row in users]
    users_by_id = {user["id"]: user for user in serialized_users}

    hydrated_conversations = user_hydration_service.attach_members_to_conversations(
        [dict(conversation) for conversation in conversations],
        users_by_id,
    )
    serialized_conversations = [ConversationSummary.model_validate(conversation).model_dump(mode="json") for conversation in hydrated_conversations]

    logger.debug(
        "Sync changes response user_id=%s conversations=%s messages=%s users=%s",
        current_user.id,
        len(serialized_conversations),
        len(changed_messages),
        len(serialized_users),
    )
    return success_response(
        {
            "conversations": serialized_conversations,
            "messages": changed_messages,
            "users": serialized_users,
        }
    )
