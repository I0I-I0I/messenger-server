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


def test_conversation_payload_includes_member_profiles(client):
    _register(client, "alice")
    bob_id = _register(client, "bob")

    alice_tokens = _login(client, "alice")

    create_response = client.post(
        "/v1/conversations/direct",
        json={"other_user_id": bob_id},
        headers=_auth_headers(alice_tokens["access"]),
    )
    assert create_response.status_code == 200
    created = create_response.json()["data"]

    assert "member_ids" in created
    assert "members" in created
    assert len(created["members"]) == 2
    assert {member["username"] for member in created["members"]} == {"alice", "bob"}

    list_response = client.get(
        "/v1/conversations",
        headers=_auth_headers(alice_tokens["access"]),
    )
    assert list_response.status_code == 200
    rows = list_response.json()["data"]
    assert len(rows) == 1
    assert len(rows[0]["members"]) == 2
    assert {member["username"] for member in rows[0]["members"]} == {"alice", "bob"}
