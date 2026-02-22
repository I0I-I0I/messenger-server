from __future__ import annotations

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_access_token(token)
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.isdigit():
        raise APIError(status_code=401, code="invalid_token", message="Token payload is invalid")

    user = db.get(User, int(subject))
    if user is None:
        raise APIError(status_code=401, code="invalid_token", message="Token user was not found")

    return user
