from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SendMessageRequest(BaseModel):
    client_message_id: str = Field(min_length=8, max_length=64)
    content: str = Field(min_length=1, max_length=2000)


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    sender_id: str
    client_message_id: str
    seq: int
    content: str
    created_at: datetime


class MessageListResponse(BaseModel):
    messages: list[MessageRead]
