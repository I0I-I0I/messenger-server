from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DirectConversationCreateRequest(BaseModel):
    other_user_id: int = Field(gt=0)


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    updated_at: datetime
    last_message_preview: str | None
    last_message_at: datetime | None
    member_ids: list[int]
