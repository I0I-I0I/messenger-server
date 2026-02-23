from __future__ import annotations

from pydantic import BaseModel

from app.schemas.conversations import ConversationSummary
from app.schemas.messages import MessageRead
from app.schemas.users import UserPublic


class BootstrapResponse(BaseModel):
    me: UserPublic
    user: UserPublic
    users: list[UserPublic]
    conversations: list[ConversationSummary]
    recent_messages: list[MessageRead]
    recentMessages: list[MessageRead]


class SyncChangesResponse(BaseModel):
    users: list[UserPublic]
    conversations: list[ConversationSummary]
    messages: list[MessageRead]
