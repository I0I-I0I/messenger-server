from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.db.session as db_session
from app.core.rate_limit import auth_limiter
from app.main import app


@pytest.fixture()
def client(tmp_path):
    auth_limiter._events.clear()
    database_path = tmp_path / "test.db"
    db_session.configure_engine(f"sqlite:///{database_path}")
    db_session.init_db()

    with TestClient(app) as test_client:
        yield test_client
