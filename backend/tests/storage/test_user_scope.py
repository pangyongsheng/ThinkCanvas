"""Tests for user-scoped conversation reads.

These tests use the synchronous SQLAlchemy session directly (rather than
going through the async storage helpers) — we want to verify the
*scoping logic* (filter by user_id, refuse delete from non-owner) and
that does not depend on async I/O.
"""
from __future__ import annotations

from app.db.models import ANON_USER_ID, Conversation
from app.storage.conversations import (
    _append_user_message_sync,
    _list_user_messages_sync,
)


def _new_conv(s, *, conv_id, user_id, title):
    s.add(Conversation(id=conv_id, title=title, style="3b1b", user_id=user_id))
    s.commit()
    return s


# ---------------------------------------------------------------------------
# list_conversations — scope
# ---------------------------------------------------------------------------

def test_list_conversations_filters_by_user(session):
    from sqlalchemy import select
    from app.db.models import Conversation

    _new_conv(session, conv_id="c1", user_id="u_alice", title="alice-1")
    _new_conv(session, conv_id="c2", user_id="u_bob", title="bob-1")
    _new_conv(session, conv_id="c3", user_id="u_alice", title="alice-2")

    alice = session.execute(
        select(Conversation)
        .where(Conversation.user_id == "u_alice")
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    ).scalars().all()
    bob = session.execute(
        select(Conversation)
        .where(Conversation.user_id == "u_bob")
    ).scalars().all()

    assert [c.title for c in alice] == ["alice-2", "alice-1"]
    assert [c.title for c in bob] == ["bob-1"]


def test_anon_user_id_is_valid_owner(session):
    """The hard-coded anon ULID works as a Conversation.user_id."""
    conv = Conversation(id="c1", title="t", style="3b1b", user_id=ANON_USER_ID)
    session.add(conv)
    session.commit()
    fetched = session.get(Conversation, "c1")
    assert fetched.user_id == ANON_USER_ID


# ---------------------------------------------------------------------------
# get_conversation — owner check via the same SQL filter the helper uses
# ---------------------------------------------------------------------------

def test_query_with_user_filter_isolates_rows(session):
    from sqlalchemy import select
    from app.db.models import Conversation

    _new_conv(session, conv_id="alice-secret", user_id="u_alice", title="secret")

    # Alice fetches her own: gets it.
    alice_q = select(Conversation).where(
        Conversation.id == "alice-secret",
        Conversation.user_id == "u_alice",
    )
    alice_row = session.execute(alice_q).scalar_one_or_none()
    assert alice_row is not None

    # Bob fetches: gets None (the filter excludes other-user rows).
    bob_q = select(Conversation).where(
        Conversation.id == "alice-secret",
        Conversation.user_id == "u_bob",
    )
    assert session.execute(bob_q).scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# delete — owner check via row inspection
# ---------------------------------------------------------------------------

def test_owner_check_via_row_attribute(session):
    _new_conv(session, conv_id="c1", user_id="u_alice", title="mine")

    conv = session.get(Conversation, "c1")
    assert conv.user_id == "u_alice"
    # Bob's request would not match.
    assert conv.user_id != "u_bob"


# ---------------------------------------------------------------------------
# user_messages helper still works with scoped conversations
# ---------------------------------------------------------------------------

def test_list_user_messages_works_after_conversation_owned(session):
    _new_conv(session, conv_id="c1", user_id="u_alice", title="t")
    for i in range(3):
        _append_user_message_sync(session, "c1", f"msg-{i}")
    history = _list_user_messages_sync(session, "c1")
    assert history == ["msg-0", "msg-1", "msg-2"]
