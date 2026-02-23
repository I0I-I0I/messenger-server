from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect


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


def test_ws_rejects_invalid_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/v1/ws?access_token=invalid-token") as websocket:
            websocket.receive_json()


def test_ws_subscribe_forbidden_for_non_member(client):
    alice_id = _register(client, "alice")
    bob_id = _register(client, "bob")
    _register(client, "charlie")

    alice_tokens = _login(client, "alice")
    charlie_tokens = _login(client, "charlie")

    conversation_response = client.post(
        "/v1/conversations/direct",
        json={"other_user_id": bob_id},
        headers=_auth_headers(alice_tokens["access"]),
    )
    assert conversation_response.status_code == 200
    conversation_id = conversation_response.json()["data"]["id"]
    assert conversation_id
    assert alice_id != bob_id

    with client.websocket_connect(f"/v1/ws?access_token={charlie_tokens['access']}") as websocket:
        welcome = websocket.receive_json()
        assert welcome["type"] == "connection.welcome"

        websocket.send_json({"op": "subscribe", "conversation_ids": [conversation_id]})
        response = websocket.receive_json()
        assert response["type"] == "error"
        assert response["error"]["code"] == "FORBIDDEN_CONVERSATION"


def test_ws_delivers_message_events_to_subscribers(client):
    alice_id = _register(client, "alice")
    bob_id = _register(client, "bob")

    alice_tokens = _login(client, "alice")
    bob_tokens = _login(client, "bob")

    conversation_response = client.post(
        "/v1/conversations/direct",
        json={"other_user_id": bob_id},
        headers=_auth_headers(alice_tokens["access"]),
    )
    assert conversation_response.status_code == 200
    conversation_id = conversation_response.json()["data"]["id"]
    assert conversation_id
    assert alice_id != bob_id

    with client.websocket_connect(f"/v1/ws?access_token={bob_tokens['access']}") as websocket:
        welcome = websocket.receive_json()
        assert welcome["type"] == "connection.welcome"

        websocket.send_json({"op": "subscribe", "conversation_ids": [conversation_id]})
        ack = websocket.receive_json()
        assert ack["type"] == "ack"
        assert ack["op"] == "subscribe"
        assert ack["ok"] is True

        send_payload = {"client_message_id": "client-msg-realtime-0001", "content": "hello over ws"}
        send_response = client.post(
            f"/v1/conversations/{conversation_id}/messages",
            json=send_payload,
            headers=_auth_headers(alice_tokens["access"]),
        )
        assert send_response.status_code == 201

        event_one = websocket.receive_json()
        event_two = websocket.receive_json()
        event_types = {event_one["type"], event_two["type"]}
        assert "message.created" in event_types
        assert "conversation.updated" in event_types

        message_event = event_one if event_one["type"] == "message.created" else event_two
        assert message_event["conversation_id"] == conversation_id
        assert message_event["payload"]["content"] == send_payload["content"]
