from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import success_response
from app.db.session import get_db
from app.models import User
from app.schemas.users import UserPublic

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return success_response(UserPublic.model_validate(current_user).model_dump(mode="json"))


@router.get("/search")
def search_users(
    query: str = Query(min_length=1, max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    normalized_query = f"%{query.lower()}%"
    rows = db.scalars(
        select(User)
        .where(
            User.id != current_user.id,
            or_(
                func.lower(User.username).like(normalized_query),
                func.lower(User.display_name).like(normalized_query),
            ),
        )
        .order_by(User.username.asc())
        .limit(limit)
    ).all()

    users = [UserPublic.model_validate(row).model_dump(mode="json") for row in rows]
    return success_response({"users": users})
