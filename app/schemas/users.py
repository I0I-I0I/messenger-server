from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_BATCH_USER_IDS = 100
UserId = Annotated[str, Field(min_length=1, max_length=64)]


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: str
    created_at: datetime


class UserSearchResult(BaseModel):
    users: list[UserPublic]


class UserBatchLookupRequest(BaseModel):
    ids: list[UserId] = Field(min_length=1, max_length=MAX_BATCH_USER_IDS)

    @field_validator("ids", mode="before")
    @classmethod
    def normalize_ids(cls, value: object) -> object:
        if not isinstance(value, list):
            return value

        normalized: list[object] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                normalized.append(item)
                continue
            trimmed = item.strip()
            if not trimmed or trimmed in seen:
                continue
            seen.add(trimmed)
            normalized.append(trimmed)
        return normalized
