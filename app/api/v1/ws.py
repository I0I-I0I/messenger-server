from __future__ import annotations

import asyncio
from collections import deque
import logging
from time import monotonic

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

import app.db.session as db_session
from app.core.errors import APIError
from app.core.security import decode_access_token
from app.core.settings import get_settings
from app.models import ConversationMember, User
from app.realtime.connection_manager import ConnectionManager
from app.realtime.protocol import (
    PingCommand,
    ProtocolError,
    SubscribeCommand,
    UnsubscribeCommand,
    ack_frame,
    error_frame,
    parse_command,
    pong_frame,
    welcome_frame,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ws"])


def _extract_access_token(websocket: WebSocket) -> str | None:
    auth_header = websocket.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return websocket.query_params.get("access_token")


def _resolve_user_id(token: str) -> str:
    payload = decode_access_token(token)
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise APIError(status_code=401, code="invalid_token", message="Token payload is invalid")
    return subject


def _conversation_memberships(user_id: str, conversation_ids: list[str]) -> set[str]:
    session_factory = db_session.SessionLocal
    if session_factory is None:
        raise RuntimeError("Database session factory is not configured")
    with session_factory() as db:
        return set(
            db.scalars(
                select(ConversationMember.conversation_id).where(
                    ConversationMember.user_id == user_id,
                    ConversationMember.conversation_id.in_(conversation_ids),
                )
            ).all()
        )


def _command_allowed(events: deque[float], *, now: float, window_seconds: int, max_commands: int) -> bool:
    cutoff = now - window_seconds
    while events and events[0] <= cutoff:
        events.popleft()
    if len(events) >= max_commands:
        return False
    events.append(now)
    return True


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    settings = get_settings()
    token = _extract_access_token(websocket)
    if not token:
        await websocket.close(code=1008)
        return

    try:
        user_id = _resolve_user_id(token)
    except APIError:
        await websocket.close(code=1008)
        return

    session_factory = db_session.SessionLocal
    if session_factory is None:
        await websocket.close(code=1011)
        return
    with session_factory() as db:
        user = db.get(User, user_id)
    if user is None:
        await websocket.close(code=1008)
        return

    connection_manager: ConnectionManager | None = getattr(websocket.app.state, "connection_manager", None)
    if connection_manager is None:
        await websocket.close(code=1011)
        return

    await websocket.accept()
    context = await connection_manager.register(websocket, user_id=user_id)
    await connection_manager.send(
        context.connection_id,
        welcome_frame(connection_id=context.connection_id, user_id=user_id, heartbeat_sec=settings.ws_heartbeat_sec),
    )

    rate_events: deque[float] = deque()
    try:
        while True:
            try:
                raw_text = await asyncio.wait_for(websocket.receive_text(), timeout=settings.ws_idle_timeout_sec)
            except asyncio.TimeoutError:
                break
            except WebSocketDisconnect:
                break

            if not _command_allowed(
                rate_events,
                now=monotonic(),
                window_seconds=settings.ws_rate_limit_window_sec,
                max_commands=settings.ws_rate_limit_max_commands,
            ):
                await connection_manager.send(
                    context.connection_id,
                    error_frame(code="RATE_LIMITED", message="Command rate limit exceeded"),
                )
                continue

            try:
                command = parse_command(raw_text, max_bytes=settings.ws_max_command_bytes)
            except ProtocolError as exc:
                await connection_manager.send(context.connection_id, error_frame(code=exc.code, message=exc.message))
                continue

            if isinstance(command, PingCommand):
                await connection_manager.send(context.connection_id, pong_frame(ts=command.ts))
                continue

            if isinstance(command, SubscribeCommand):
                requested = list(dict.fromkeys(command.conversation_ids))
                if not requested:
                    await connection_manager.send(
                        context.connection_id,
                        error_frame(code="INVALID_COMMAND", message="conversation_ids is required"),
                    )
                    continue
                if len(requested) > settings.ws_max_ids_per_subscribe:
                    await connection_manager.send(
                        context.connection_id,
                        error_frame(code="INVALID_COMMAND", message="Too many conversation ids"),
                    )
                    continue

                member_ids = _conversation_memberships(user_id, requested)
                if member_ids != set(requested):
                    await connection_manager.send(
                        context.connection_id,
                        error_frame(code="FORBIDDEN_CONVERSATION", message="Not a member of one or more conversations"),
                    )
                    continue

                try:
                    await connection_manager.subscribe(context.connection_id, requested)
                except ValueError:
                    await connection_manager.send(
                        context.connection_id,
                        error_frame(code="INVALID_COMMAND", message="Subscription limit exceeded"),
                    )
                    continue

                await connection_manager.send(
                    context.connection_id,
                    ack_frame(op="subscribe", details={"conversation_ids": requested}),
                )
                continue

            if isinstance(command, UnsubscribeCommand):
                requested = list(dict.fromkeys(command.conversation_ids))
                if not requested:
                    await connection_manager.send(
                        context.connection_id,
                        error_frame(code="INVALID_COMMAND", message="conversation_ids is required"),
                    )
                    continue
                await connection_manager.unsubscribe(context.connection_id, requested)
                await connection_manager.send(
                    context.connection_id,
                    ack_frame(op="unsubscribe", details={"conversation_ids": requested}),
                )
                continue
    finally:
        await connection_manager.unregister(context.connection_id, close_socket=True)
        logger.info("WebSocket session closed connection_id=%s user_id=%s", context.connection_id, user_id)
