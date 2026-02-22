from __future__ import annotations

from pydantic import BaseModel

from app.schemas.conversations import ConversationSummary
from app.schemas.messages import MessageRead
from app.schemas.users import UserPublic


class ConversationChanges(BaseModel):
    conversation_id: str
    messages: list[MessageRead]


class BootstrapResponse(BaseModel):
    me: UserPublic
    conversations: list[ConversationSummary]
    recent_messages: list[MessageRead]


class SyncChangesResponse(BaseModel):
    changes: list[ConversationChanges]
