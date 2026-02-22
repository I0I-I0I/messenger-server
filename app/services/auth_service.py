from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.core.settings import get_settings
from app.models import RefreshToken, User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenPair

settings = get_settings()


def _active_refresh_token_stmt(token_hash: str) -> Select[tuple[RefreshToken]]:
    now = datetime.now(UTC)
    return select(RefreshToken).where(
        RefreshToken.token_hash == token_hash,
        RefreshToken.revoked_at.is_(None),
        RefreshToken.expires_at > now,
    )


def _issue_refresh_token(db: Session, user_id: int) -> tuple[str, RefreshToken]:
    now = datetime.now(UTC)
    raw_token = generate_refresh_token()
    refresh_token = RefreshToken(
        user_id=user_id,
        token_hash=hash_token(raw_token),
        issued_at=now,
        expires_at=now + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(refresh_token)
    db.flush()
    return raw_token, refresh_token


def _token_pair(db: Session, user: User) -> TokenPair:
    access_token = create_access_token(subject=str(user.id))
    refresh_token_raw, _ = _issue_refresh_token(db, user.id)
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token_raw,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


def register_user(db: Session, payload: RegisterRequest) -> tuple[User, TokenPair]:
    existing_user = db.scalar(select(User).where(User.username == payload.username))
    if existing_user is not None:
        raise APIError(status_code=409, code="username_taken", message="Username is already in use")

    user = User(
        username=payload.username,
        display_name=payload.display_name or payload.username,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.flush()

    tokens = _token_pair(db, user)

    db.commit()
    db.refresh(user)
    return user, tokens


def authenticate_user(db: Session, payload: LoginRequest) -> tuple[User, TokenPair]:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise APIError(status_code=401, code="invalid_credentials", message="Invalid username or password")

    tokens = _token_pair(db, user)
    db.commit()
    return user, tokens


def rotate_refresh_token(db: Session, refresh_token_raw: str) -> tuple[User, TokenPair]:
    token_hash_value = hash_token(refresh_token_raw)
    current_token = db.scalar(_active_refresh_token_stmt(token_hash_value))
    if current_token is None:
        raise APIError(status_code=401, code="invalid_refresh_token", message="Refresh token is invalid or expired")

    user = db.get(User, current_token.user_id)
    if user is None:
        raise APIError(status_code=401, code="invalid_refresh_token", message="Refresh token is invalid")

    now = datetime.now(UTC)
    new_raw_token, new_token = _issue_refresh_token(db, user.id)

    current_token.revoked_at = now
    current_token.replaced_by_token_id = new_token.id

    access_token = create_access_token(subject=str(user.id))
    db.commit()

    tokens = TokenPair(
        access_token=access_token,
        refresh_token=new_raw_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )
    return user, tokens


def revoke_refresh_token(db: Session, refresh_token_raw: str) -> None:
    token_hash_value = hash_token(refresh_token_raw)
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash_value))
    if token is None:
        return

    if token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        db.commit()
