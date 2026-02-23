from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError


@dataclass(slots=True)
class ProtocolError(Exception):
    code: str
    message: str


class SubscribeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["subscribe"]
    conversation_ids: list[str]


class UnsubscribeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["unsubscribe"]
    conversation_ids: list[str]


class PingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["ping"]
    ts: int | None = None


Command = SubscribeCommand | UnsubscribeCommand | PingCommand


def parse_command(raw_text: str, *, max_bytes: int) -> Command:
    payload_size = len(raw_text.encode("utf-8"))
    if payload_size > max_bytes:
        raise ProtocolError(code="INVALID_COMMAND", message="Frame is too large")

    try:
        decoded = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ProtocolError(code="INVALID_COMMAND", message="Invalid JSON payload") from exc

    if not isinstance(decoded, dict):
        raise ProtocolError(code="INVALID_COMMAND", message="Command payload must be an object")

    op = decoded.get("op")
    model: type[BaseModel]
    if op == "subscribe":
        model = SubscribeCommand
    elif op == "unsubscribe":
        model = UnsubscribeCommand
    elif op == "ping":
        model = PingCommand
    else:
        raise ProtocolError(code="INVALID_COMMAND", message="Unsupported command")

    try:
        return model.model_validate(decoded)
    except ValidationError as exc:
        raise ProtocolError(code="INVALID_COMMAND", message=str(exc.errors()[0]["msg"])) from exc


def welcome_frame(*, connection_id: str, user_id: str, heartbeat_sec: int) -> dict[str, object]:
    return {
        "type": "connection.welcome",
        "connection_id": connection_id,
        "user_id": user_id,
        "server_time": datetime.now(UTC).isoformat(),
        "heartbeat_sec": heartbeat_sec,
        "protocol_version": 1,
    }


def ack_frame(*, op: str, details: dict[str, object] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "ack",
        "op": op,
        "ok": True,
    }
    if details:
        payload["details"] = details
    return payload


def error_frame(*, code: str, message: str, details: dict[str, object] | None = None) -> dict[str, object]:
    error_payload: dict[str, object] = {"code": code, "message": message}
    if details:
        error_payload["details"] = details
    return {"type": "error", "error": error_payload}


def pong_frame(*, ts: int | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"type": "pong"}
    if ts is not None:
        payload["ts"] = ts
    return payload


def event_frame(
    *,
    event_type: str,
    event_id: str,
    conversation_id: str,
    seq: int,
    occurred_at: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "type": event_type,
        "event_id": event_id,
        "conversation_id": conversation_id,
        "seq": seq,
        "occurred_at": occurred_at,
        "payload": payload,
    }
