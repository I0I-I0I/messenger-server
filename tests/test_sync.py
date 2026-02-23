from __future__ import annotations

import json


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


def _collect_referenced_user_ids(conversations: list[dict[str, object]], messages: list[dict[str, object]]) -> set[str]:
    ids: set[str] = set()
    for conversation in conversations:
        member_ids = conversation.get("member_ids", [])
        if isinstance(member_ids, list):
            ids.update(member_ids)

    for message in messages:
        sender_id = message.get("sender_id")
        if isinstance(sender_id, str):
            ids.add(sender_id)
    return ids


def test_sync_bootstrap_returns_users_covering_conversation_and_message_references(client):
    _register(client, "alice")
    bob_id = _register(client, "bob")
    tokens = _login(client, "alice")

    conversation_response = client.post(
        "/v1/conversations/direct",
        json={"other_user_id": bob_id},
        headers=_auth_headers(tokens["access"]),
    )
    conversation_id = conversation_response.json()["data"]["id"]

    send_response = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"client_message_id": "bootstrap-msg-1", "content": "hello"},
        headers=_auth_headers(tokens["access"]),
    )
    assert send_response.status_code == 201

    bootstrap = client.get("/v1/sync/bootstrap", headers=_auth_headers(tokens["access"]))
    assert bootstrap.status_code == 200
    payload = bootstrap.json()["data"]

    assert payload["me"]["id"] == payload["user"]["id"]
    assert payload["recentMessages"] == payload["recent_messages"]

    users_by_id = {user["id"] for user in payload["users"]}
    referenced = _collect_referenced_user_ids(payload["conversations"], payload["recent_messages"])
    assert referenced.issubset(users_by_id)


def test_sync_changes_flattened_payload_includes_users_for_references(client):
    alice_id = _register(client, "alice")
    bob_id = _register(client, "bob")

    alice_tokens = _login(client, "alice")
    bob_tokens = _login(client, "bob")

    conversation_response = client.post(
        "/v1/conversations/direct",
        json={"other_user_id": bob_id},
        headers=_auth_headers(alice_tokens["access"]),
    )
    conversation_id = conversation_response.json()["data"]["id"]

    first_send = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"client_message_id": "changes-msg-1", "content": "first"},
        headers=_auth_headers(alice_tokens["access"]),
    )
    assert first_send.status_code == 201

    second_send = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"client_message_id": "changes-msg-2", "content": "second"},
        headers=_auth_headers(bob_tokens["access"]),
    )
    assert second_send.status_code == 201

    query = json.dumps({conversation_id: 0})
    changes = client.get(
        "/v1/sync/changes",
        params={"after_seq_by_conversation": query},
        headers=_auth_headers(alice_tokens["access"]),
    )
    assert changes.status_code == 200
    payload = changes.json()["data"]

    assert "users" in payload
    assert "conversations" in payload
    assert "messages" in payload
    assert "changes" not in payload

    users_by_id = {user["id"] for user in payload["users"]}
    referenced = _collect_referenced_user_ids(payload["conversations"], payload["messages"])
    assert referenced.issubset(users_by_id)
    assert {alice_id, bob_id}.issubset(users_by_id)


def test_fresh_flow_has_no_unresolved_identity_references(client):
    _register(client, "alice")
    bob_id = _register(client, "bob")
    tokens = _login(client, "alice")

    conversation = client.post(
        "/v1/conversations/direct",
        json={"other_user_id": bob_id},
        headers=_auth_headers(tokens["access"]),
    )
    conversation_id = conversation.json()["data"]["id"]

    send_message = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"client_message_id": "fresh-flow-msg-1", "content": "identity check"},
        headers=_auth_headers(tokens["access"]),
    )
    assert send_message.status_code == 201

    bootstrap = client.get("/v1/sync/bootstrap", headers=_auth_headers(tokens["access"]))
    assert bootstrap.status_code == 200
    bootstrap_payload = bootstrap.json()["data"]
    hydrated_user_ids = {user["id"] for user in bootstrap_payload["users"]}

    list_conversations = client.get("/v1/conversations", headers=_auth_headers(tokens["access"]))
    assert list_conversations.status_code == 200
    conversations = list_conversations.json()["data"]

    list_messages = client.get(
        f"/v1/conversations/{conversation_id}/messages",
        headers=_auth_headers(tokens["access"]),
    )
    assert list_messages.status_code == 200
    messages = list_messages.json()["data"]["messages"]

    referenced = _collect_referenced_user_ids(conversations, messages)
    assert referenced.issubset(hydrated_user_ids)
