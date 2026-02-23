from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json

from sqlalchemy import select

import app.db.session as db_session
from app.models import RealtimeOutboxEvent
from app.realtime.dispatcher import RealtimeDispatcher


class _FakePublisher:
    def __init__(self, *, failures: int = 0) -> None:
        self._remaining_failures = failures
        self.published_event_ids: list[str] = []

    async def publish(self, event: RealtimeOutboxEvent) -> int:
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise RuntimeError("simulated publish failure")
        self.published_event_ids.append(event.event_id)
        return 1


def _setup_database(tmp_path) -> None:
    database_path = tmp_path / "dispatcher.db"
    db_session.configure_engine(f"sqlite:///{database_path}")
    db_session.init_db()


def _create_event() -> RealtimeOutboxEvent:
    payload = {
        "seq": 1,
        "occurred_at": datetime.now(UTC).isoformat(),
        "payload": {"id": "msg-1", "content": "hello"},
    }
    return RealtimeOutboxEvent(
        event_type="message.created",
        conversation_id="conversation-1",
        payload_json=json.dumps(payload),
        next_attempt_at=datetime.now(UTC),
    )


def test_dispatcher_marks_events_as_published(tmp_path):
    _setup_database(tmp_path)
    session_factory = db_session.SessionLocal
    assert session_factory is not None

    with session_factory() as db:
        db.add(_create_event())
        db.commit()

    publisher = _FakePublisher()
    dispatcher = RealtimeDispatcher(
        publisher=publisher,
        session_factory=session_factory,
        poll_interval_sec=0.01,
        batch_size=50,
    )
    processed = asyncio.run(dispatcher.process_once())
    assert processed == 1

    with session_factory() as db:
        event = db.scalar(select(RealtimeOutboxEvent))
        assert event is not None
        assert event.published_at is not None
        assert event.attempts == 0
        assert event.event_id in publisher.published_event_ids


def test_dispatcher_retries_after_publish_failure(tmp_path):
    _setup_database(tmp_path)
    session_factory = db_session.SessionLocal
    assert session_factory is not None

    with session_factory() as db:
        db.add(_create_event())
        db.commit()

    publisher = _FakePublisher(failures=1)
    dispatcher = RealtimeDispatcher(
        publisher=publisher,
        session_factory=session_factory,
        poll_interval_sec=0.01,
        batch_size=50,
    )
    first_processed = asyncio.run(dispatcher.process_once())
    assert first_processed == 1

    with session_factory() as db:
        event = db.scalar(select(RealtimeOutboxEvent))
        assert event is not None
        assert event.published_at is None
        assert event.attempts == 1
        now = datetime.now(UTC)
        if event.next_attempt_at.tzinfo is None:
            now = now.replace(tzinfo=None)
        assert event.next_attempt_at > now
        event.next_attempt_at = now - timedelta(seconds=1)
        db.commit()

    second_processed = asyncio.run(dispatcher.process_once())
    assert second_processed == 1

    with session_factory() as db:
        event = db.scalar(select(RealtimeOutboxEvent))
        assert event is not None
        assert event.published_at is not None
        assert event.attempts == 1
        assert event.event_id in publisher.published_event_ids
