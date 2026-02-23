from __future__ import annotations

from app.services import user_hydration_service


class _MessageObject:
    def __init__(self, sender_id: str) -> None:
        self.sender_id = sender_id


def test_collectors_deduplicate_and_include_all_referenced_ids():
    conversations = [
        {"member_ids": ["u1", "u2"]},
        {"member_ids": ["u2", "u3"]},
        {"member_ids": ["u3", "u3"]},
        {"member_ids": []},
    ]
    messages = [
        {"sender_id": "u2"},
        {"sender_id": "u4"},
        _MessageObject("u1"),
        _MessageObject("u4"),
    ]

    conversation_ids = user_hydration_service.collect_user_ids_from_conversations(conversations)
    message_ids = user_hydration_service.collect_user_ids_from_messages(messages)

    assert conversation_ids == {"u1", "u2", "u3"}
    assert message_ids == {"u1", "u2", "u4"}
