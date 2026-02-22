from __future__ import annotations

from sqlalchemy import select

import app.db.session as db_session
from app.core.security import hash_password, verify_password
from app.models import RefreshToken


def _register_and_login(client, username: str, password: str = "password123") -> dict[str, str]:
    register_response = client.post(
        "/v1/auth/register",
        json={"username": username, "display_name": username, "password": password},
    )
    assert register_response.status_code == 201

    login_response = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert login_response.status_code == 200

    tokens = login_response.json()["data"]["tokens"]
    return {
        "access": tokens["access_token"],
        "refresh": tokens["refresh_token"],
    }


def test_password_hashing_round_trip():
    plain_password = "password123"
    hashed_password = hash_password(plain_password)

    assert hashed_password != plain_password
    assert verify_password(plain_password, hashed_password)
    assert not verify_password("wrong-password", hashed_password)


def test_refresh_token_rotation(client):
    tokens = _register_and_login(client, "alice")

    first_refresh = client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh"]})
    assert first_refresh.status_code == 200

    rotated = first_refresh.json()["data"]["tokens"]
    second_refresh_token = rotated["refresh_token"]

    reused_old = client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh"]})
    assert reused_old.status_code == 401
    assert reused_old.json()["error"]["code"] == "invalid_refresh_token"

    logout_response = client.post("/v1/auth/logout", json={"refresh_token": second_refresh_token})
    assert logout_response.status_code == 200

    after_logout = client.post("/v1/auth/refresh", json={"refresh_token": second_refresh_token})
    assert after_logout.status_code == 401

    session_factory = db_session.SessionLocal
    assert session_factory is not None
    with session_factory() as session:
        token_rows = session.scalars(select(RefreshToken).order_by(RefreshToken.id.asc())).all()
        assert len(token_rows) >= 2
        assert all(row.token_hash != tokens["refresh"] for row in token_rows)
        assert all(row.token_hash != second_refresh_token for row in token_rows)
        assert token_rows[-2].replaced_by_token_id == token_rows[-1].id
