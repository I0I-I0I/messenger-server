from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.errors import success_response
from app.core.rate_limit import enforce_auth_rate_limit
from app.db.session import get_db
from app.schemas.auth import AuthResponse, LoginRequest, LogoutRequest, RefreshRequest, RegisterRequest
from app.schemas.users import UserPublic
from app.services import auth_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", dependencies=[Depends(enforce_auth_rate_limit)])
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    logger.info("Auth register endpoint hit username=%s", payload.username)
    user, tokens = auth_service.register_user(db, payload)
    body = AuthResponse(user=UserPublic.model_validate(user), tokens=tokens)
    return success_response(body.model_dump(mode="json"), status_code=status.HTTP_201_CREATED)


@router.post("/login", dependencies=[Depends(enforce_auth_rate_limit)])
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    logger.info("Auth login endpoint hit username=%s", payload.username)
    user, tokens = auth_service.authenticate_user(db, payload)
    body = AuthResponse(user=UserPublic.model_validate(user), tokens=tokens)
    return success_response(body.model_dump(mode="json"))


@router.post("/refresh", dependencies=[Depends(enforce_auth_rate_limit)])
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    logger.info("Auth refresh endpoint hit")
    user, tokens = auth_service.rotate_refresh_token(db, payload.refresh_token)
    body = AuthResponse(user=UserPublic.model_validate(user), tokens=tokens)
    return success_response(body.model_dump(mode="json"))


@router.post("/logout")
def logout(payload: LogoutRequest, db: Session = Depends(get_db)):
    logger.info("Auth logout endpoint hit")
    auth_service.revoke_refresh_token(db, payload.refresh_token)
    return success_response({"ok": True})
