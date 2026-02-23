from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import logging
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RealtimeOutboxEvent
from app.realtime.publisher import RealtimePublisher

logger = logging.getLogger(__name__)


class RealtimeDispatcher:
    def __init__(
        self,
        *,
        publisher: RealtimePublisher,
        session_factory: Callable[[], Session],
        poll_interval_sec: float,
        batch_size: int,
    ) -> None:
        self._publisher = publisher
        self._session_factory = session_factory
        self._poll_interval_sec = poll_interval_sec
        self._batch_size = batch_size
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run())
        logger.info("Realtime dispatcher started")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("Realtime dispatcher stopped")

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                processed = await self.process_once()
                if processed == 0:
                    await asyncio.sleep(self._poll_interval_sec)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Realtime dispatcher crashed")
            raise

    async def process_once(self) -> int:
        now = datetime.now(UTC)
        with self._session_factory() as db:
            events = list(
                db.scalars(
                    select(RealtimeOutboxEvent)
                    .where(RealtimeOutboxEvent.published_at.is_(None))
                    .where(RealtimeOutboxEvent.next_attempt_at <= now)
                    .order_by(RealtimeOutboxEvent.id.asc())
                    .limit(self._batch_size)
                ).all()
            )
            if not events:
                return 0

            processed = 0
            for event in events:
                try:
                    await self._publisher.publish(event)
                    event.published_at = datetime.now(UTC)
                    event.last_error = None
                except Exception as exc:
                    event.attempts += 1
                    delay = min(30.0, 0.5 * (2 ** (event.attempts - 1)))
                    event.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
                    event.last_error = str(exc)[:1000]
                    logger.warning(
                        "Realtime publish failed event_id=%s attempts=%s error=%s",
                        event.event_id,
                        event.attempts,
                        exc,
                    )
                processed += 1

            db.commit()
            return processed
