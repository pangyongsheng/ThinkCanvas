"""Tests for ``app.storage.conversations``.

Specifically the user-history cap, which directly affects what we feed
to the refine LLM.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Conversation
from app.storage.conversations import (
    USER_HISTORY_LIMIT,
    _append_user_message_sync,
    _list_user_messages_sync,
    _write_assistant_message_sync,
)


def _new_conv(s: Session, id_: str = "c1") -> Conversation:
    s.add(Conversation(id=id_, title="t", style="3b1b"))
    s.commit()
    return s


def test_list_user_messages_returns_chronological(session):
    _new_conv(session)

    for i in range(3):
        _append_user_message_sync(session, "c1", f"msg-{i}")

    history = _list_user_messages_sync(session, "c1")
    assert history == ["msg-0", "msg-1", "msg-2"]


def test_list_user_messages_caps_at_default_limit(session):
    """Only the most recent USER_HISTORY_LIMIT messages survive.

    If we have more rounds than the cap, oldest ones are dropped so the
    refine prompt doesn't grow unboundedly with long conversations.
    """
    assert USER_HISTORY_LIMIT == 6  # sanity-check the documented value

    _new_conv(session)

    for i in range(10):
        _append_user_message_sync(session, "c1", f"round-{i:02d}")

    history = _list_user_messages_sync(session, "c1")
    assert len(history) == USER_HISTORY_LIMIT
    # Newest 6, in chronological order (oldest of the kept first).
    assert history == [f"round-{i:02d}" for i in range(4, 10)]


def test_list_user_messages_respects_custom_limit(session):
    _new_conv(session)

    for i in range(5):
        _append_user_message_sync(session, "c1", f"msg-{i}")

    history = _list_user_messages_sync(session, "c1", limit=2)
    assert history == ["msg-3", "msg-4"]


def test_list_user_messages_skips_empty_content(session):
    _new_conv(session)

    _append_user_message_sync(session, "c1", "   ")
    _append_user_message_sync(session, "c1", "real message")

    history = _list_user_messages_sync(session, "c1")
    assert history == ["real message"]


def test_list_user_messages_only_user_role(session):
    """Assistant messages must not leak into the user history list."""
    _new_conv(session)

    _append_user_message_sync(session, "c1", "user-1")
    _write_assistant_message_sync(session, "c1", status="ok", content="asst-1")
    _append_user_message_sync(session, "c1", "user-2")

    history = _list_user_messages_sync(session, "c1")
    assert history == ["user-1", "user-2"]
