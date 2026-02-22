from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    created_at: datetime


class UserSearchResult(BaseModel):
    users: list[UserPublic]
