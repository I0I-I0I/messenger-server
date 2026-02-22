from __future__ import annotations


def _register(client, username: str, password: str = "password123") -> int:
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


def test_message_send_and_idempotency(client):
    alice_id = _register(client, "alice")
    bob_id = _register(client, "bob")

    assert alice_id != bob_id

    alice_tokens = _login(client, "alice")

    conversation_response = client.post(
        "/v1/conversations/direct",
        json={"other_user_id": bob_id},
        headers=_auth_headers(alice_tokens["access"]),
    )
    assert conversation_response.status_code == 200
    conversation_id = conversation_response.json()["data"]["id"]

    payload = {"client_message_id": "client-msg-0001", "content": "hello from alice"}

    first_send = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json=payload,
        headers=_auth_headers(alice_tokens["access"]),
    )
    assert first_send.status_code == 201

    second_send = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json=payload,
        headers=_auth_headers(alice_tokens["access"]),
    )
    assert second_send.status_code == 200

    first_message = first_send.json()["data"]
    second_message = second_send.json()["data"]

    assert first_message["id"] == second_message["id"]
    assert first_message["seq"] == 1
    assert second_message["seq"] == 1

    list_messages = client.get(
        f"/v1/conversations/{conversation_id}/messages",
        headers=_auth_headers(alice_tokens["access"]),
        params={"after_seq": 0, "limit": 50},
    )
    assert list_messages.status_code == 200

    messages = list_messages.json()["data"]["messages"]
    assert len(messages) == 1
    assert messages[0]["client_message_id"] == payload["client_message_id"]
