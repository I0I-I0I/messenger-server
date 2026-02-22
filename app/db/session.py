from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.settings import get_settings

Base = declarative_base()

engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def _connect_args(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def configure_engine(database_url: str) -> None:
    global engine, SessionLocal
    engine = create_engine(database_url, connect_args=_connect_args(database_url), future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


configure_engine(get_settings().database_url)


def init_db() -> None:
    from app.models import conversation, message, refresh_token, user  # noqa: F401

    if engine is None:
        raise RuntimeError("Database engine is not configured")
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    if SessionLocal is None:
        raise RuntimeError("Database session factory is not configured")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
