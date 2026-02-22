from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import success_response
from app.db.session import get_db
from app.models import User
from app.schemas.messages import MessageRead, SendMessageRequest
from app.services import conversation_service, message_service

router = APIRouter(prefix="/conversations/{conversation_id}/messages", tags=["messages"])


@router.get("")
def list_messages(
    conversation_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation_service.require_membership(db, user_id=current_user.id, conversation_id=conversation_id)
    messages = message_service.list_messages(
        db,
        conversation_id=conversation_id,
        after_seq=after_seq,
        limit=limit,
    )
    payload = [MessageRead.model_validate(message).model_dump(mode="json") for message in messages]
    return success_response({"messages": payload})


@router.post("")
def send_message(
    conversation_id: str,
    payload: SendMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation_service.require_membership(db, user_id=current_user.id, conversation_id=conversation_id)
    message, created = message_service.send_message(
        db,
        conversation_id=conversation_id,
        sender_id=current_user.id,
        client_message_id=payload.client_message_id,
        content=payload.content,
    )

    response = MessageRead.model_validate(message).model_dump(mode="json")
    status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return success_response(response, status_code=status_code)
