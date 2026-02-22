from __future__ import annotations

import logging

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    logger.debug("Resolving current user from access token")
    payload = decode_access_token(token)
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.isdigit():
        logger.warning("Token subject is invalid")
        raise APIError(status_code=401, code="invalid_token", message="Token payload is invalid")

    user = db.get(User, int(subject))
    if user is None:
        logger.warning("Token user_id=%s not found", subject)
        raise APIError(status_code=401, code="invalid_token", message="Token user was not found")

    logger.debug("Resolved current user user_id=%s", user.id)
    return user
