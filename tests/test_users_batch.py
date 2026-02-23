from __future__ import annotations


def _register(client, username: str, password: str = "password123") -> str:
    response = client.post(
        "/v1/auth/register",
        json={"username": username, "display_name": username, "password": password},
    )
    assert response.status_code == 201
    return response.json()["data"]["user"]["id"]


def _login(client, username: str, password: str = "password123") -> dict[str, str]:
    response = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    tokens = response.json()["data"]["tokens"]
    return {
        "access": tokens["access_token"],
        "refresh": tokens["refresh_token"],
    }


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def test_users_batch_returns_known_visible_and_skips_unknown_or_invisible(client):
    alice_id = _register(client, "alice")
    bob_id = _register(client, "bob")
    charlie_id = _register(client, "charlie")

    alice_tokens = _login(client, "alice")

    create_conversation = client.post(
        "/v1/conversations/direct",
        json={"other_user_id": bob_id},
        headers=_auth_headers(alice_tokens["access"]),
    )
    assert create_conversation.status_code == 200

    batch = client.post(
        "/v1/users/batch",
        json={"ids": [alice_id, bob_id, charlie_id, "missing-user-id", f" {bob_id} ", ""]},
        headers=_auth_headers(alice_tokens["access"]),
    )
    assert batch.status_code == 200
    users = batch.json()["data"]["users"]
    returned_ids = {user["id"] for user in users}

    assert returned_ids == {alice_id, bob_id}


def test_users_batch_validates_required_ids_and_limit(client):
    _register(client, "alice")
    tokens = _login(client, "alice")
    headers = _auth_headers(tokens["access"])

    missing_ids = client.post("/v1/users/batch", json={}, headers=headers)
    assert missing_ids.status_code == 422

    blank_ids = client.post("/v1/users/batch", json={"ids": [" ", ""]}, headers=headers)
    assert blank_ids.status_code == 422

    too_many_ids = client.post("/v1/users/batch", json={"ids": [f"id-{idx}" for idx in range(101)]}, headers=headers)
    assert too_many_ids.status_code == 422
