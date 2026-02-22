from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.errors import APIError
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    logger.debug("Hashing password")
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    is_valid = pwd_context.verify(plain_password, hashed_password)
    logger.debug("Password verification result=%s", is_valid)
    return is_valid


def create_access_token(*, subject: str, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload = {"sub": subject, "type": "access", "iat": int(now.timestamp()), "exp": int(expire.timestamp())}
    logger.debug("Creating access token subject=%s expires_at=%s", subject, expire.isoformat())
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, object]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        logger.warning("Access token decode failed")
        raise APIError(status_code=401, code="invalid_token", message="Invalid or expired access token") from exc

    if payload.get("type") != "access":
        logger.warning("Invalid token type in access token payload")
        raise APIError(status_code=401, code="invalid_token", message="Invalid token type")

    logger.debug("Access token decoded subject=%s", payload.get("sub"))
    return payload


def generate_refresh_token() -> str:
    logger.debug("Generating refresh token")
    return secrets.token_urlsafe(48)


def hash_token(raw_token: str) -> str:
    logger.debug("Hashing refresh token")
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
