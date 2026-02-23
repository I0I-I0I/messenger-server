from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.users import UserPublic


class DirectConversationCreateRequest(BaseModel):
    other_user_id: str = Field(min_length=1, max_length=64)


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    updated_at: datetime
    last_message_preview: str | None
    last_message_at: datetime | None
    member_ids: list[str]
    members: list[UserPublic] = Field(default_factory=list)
