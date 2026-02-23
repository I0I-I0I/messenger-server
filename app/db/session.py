from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

Base = declarative_base()

engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def _connect_args(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def configure_engine(database_url: str) -> None:
    global engine, SessionLocal
    logger.info("Configuring database engine")
    logger.debug("Database URL: %s", database_url)
    engine = create_engine(database_url, connect_args=_connect_args(database_url), future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    logger.info("Database engine configured")


configure_engine(get_settings().database_url)


def init_db() -> None:
    from app.models import conversation, message, realtime_outbox_event, refresh_token, user  # noqa: F401

    if engine is None:
        raise RuntimeError("Database engine is not configured")
    logger.info("Creating database tables if they do not exist")
    Base.metadata.create_all(bind=engine)
    logger.info("Database schema initialization complete")


def get_db() -> Generator[Session, None, None]:
    if SessionLocal is None:
        raise RuntimeError("Database session factory is not configured")
    db = SessionLocal()
    logger.debug("Database session opened")
    try:
        yield db
    finally:
        db.close()
        logger.debug("Database session closed")
