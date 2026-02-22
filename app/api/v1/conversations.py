from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import success_response
from app.db.session import get_db
from app.models import User
from app.schemas.conversations import ConversationSummary, DirectConversationCreateRequest
from app.services import conversation_service

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
def list_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversations = conversation_service.list_user_conversations(db, current_user.id)
    payload = [ConversationSummary.model_validate(item).model_dump(mode="json") for item in conversations]
    return success_response(payload)


@router.post("/direct")
def open_or_create_direct(
    payload: DirectConversationCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = conversation_service.get_or_create_direct_conversation(
        db,
        user_id=current_user.id,
        other_user_id=payload.other_user_id,
    )
    return success_response(ConversationSummary.model_validate(conversation).model_dump(mode="json"))
