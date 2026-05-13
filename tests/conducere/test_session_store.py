import asyncio
from datetime import datetime, timezone

import pytest

from conducere.models import SessionStatus
from conducere.session_store import SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(repo_path=tmp_path)


class TestCreateSession:
    def test_create_returns_session_and_tokens(self, store):
        session, tokens = store.create_session(title="Test Session")
        assert session.id
        assert session.status == SessionStatus.ACTIVE
        assert tokens == {}

    def test_create_with_participants(self, store):
        session, tokens = store.create_session(
            title="Team Session",
            participant_names=["alice", "bob"],
        )
        assert len(session.participants) == 2
        assert session.participants[0].name == "alice"
        assert "alice" in tokens
        assert "bob" in tokens

    def test_create_generates_unique_ids(self, store):
        s1, _ = store.create_session(title="A")
        s2, _ = store.create_session(title="B")
        assert s1.id != s2.id

    def test_create_persists_to_git(self, store):
        session, _ = store.create_session(title="Persisted")
        content = store._git.read_file(f"sessions/{session.id}/session.json")
        assert content is not None
        assert "Persisted" in content

    def test_git_does_not_contain_tokens(self, store):
        session, tokens = store.create_session(
            title="Secrets", participant_names=["alice"]
        )
        content = store._git.read_file(f"sessions/{session.id}/session.json")
        assert tokens["alice"] not in content

    def test_returns_copy_not_reference(self, store):
        session, _ = store.create_session(title="Test")
        session.title = "Mutated"
        fetched = store.get_session(session.id)
        assert fetched.title == "Test"


class TestAuthenticate:
    def test_valid_token(self, store):
        session, tokens = store.create_session(
            title="Test", participant_names=["alice"]
        )
        user = store.authenticate(session.id, tokens["alice"])
        assert user == "alice"

    def test_invalid_token(self, store):
        session, _ = store.create_session(title="Test", participant_names=["alice"])
        assert store.authenticate(session.id, "bad-token") is None

    def test_nonexistent_session(self, store):
        assert store.authenticate("no-such-id", "token") is None


class TestGetSession:
    def test_get_existing_session(self, store):
        created, _ = store.create_session(title="Test")
        fetched = store.get_session(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_nonexistent_returns_none(self, store):
        assert store.get_session("no-such-id") is None

    def test_get_returns_copy(self, store):
        session, _ = store.create_session(title="Test")
        fetched = store.get_session(session.id)
        fetched.messages.append(None)
        refetched = store.get_session(session.id)
        assert len(refetched.messages) == 0


class TestAddMessage:
    def test_add_message_returns_message(self, store):
        session, _ = store.create_session(title="Test")
        msg = store.add_message(
            session_id=session.id,
            author="alice",
            text="Hello",
        )
        assert msg.id.startswith("msg-")
        assert msg.author == "alice"
        assert msg.text == "Hello"

    def test_add_message_with_metadata(self, store):
        session, _ = store.create_session(title="Test")
        msg = store.add_message(
            session_id=session.id,
            author="ai",
            text="What is the feature?",
            metadata={"type": "question"},
        )
        assert msg.metadata == {"type": "question"}

    def test_messages_are_ordered(self, store):
        session, _ = store.create_session(title="Test")
        store.add_message(session.id, "alice", "First")
        store.add_message(session.id, "bob", "Second")
        messages = store.get_messages(session.id)
        assert len(messages) == 2
        assert messages[0].text == "First"
        assert messages[1].text == "Second"

    def test_add_to_nonexistent_session_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.add_message("no-such-id", "alice", "Hello")

    def test_add_to_complete_session_raises(self, store):
        session, _ = store.create_session(title="Test")
        store.end_session(session.id)
        with pytest.raises(ValueError, match="not active"):
            store.add_message(session.id, "alice", "Hello")

    def test_add_message_creates_git_commit(self, store):
        session, _ = store.create_session(title="Test")
        store.add_message(session.id, "alice", "Hello")
        log = store._git.log(f"sessions/{session.id}")
        assert any("message: alice" in entry["message"] for entry in log)


class TestGetMessages:
    def test_get_messages_since(self, store):
        session, _ = store.create_session(title="Test")
        msg1 = store.add_message(session.id, "alice", "First")
        store.add_message(session.id, "bob", "Second")
        since = msg1.timestamp
        messages = store.get_messages(session.id, since=since)
        assert len(messages) == 1
        assert messages[0].text == "Second"


class TestEndSession:
    def test_end_session_marks_complete(self, store):
        session, _ = store.create_session(title="Test")
        record = store.end_session(session.id)
        assert record["status"] == "complete"
        updated = store.get_session(session.id)
        assert updated.status == SessionStatus.COMPLETE

    def test_end_nonexistent_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.end_session("no-such-id")


class TestSubscriberNotification:
    @pytest.mark.asyncio
    async def test_wait_for_activity_returns_on_message(self, store):
        session, _ = store.create_session(title="Test")

        async def post_after_delay():
            await asyncio.sleep(0.1)
            store.add_message(session.id, "alice", "Hello")

        asyncio.create_task(post_after_delay())
        messages = await store.wait_for_activity(session.id, timeout=2.0)
        assert len(messages) >= 1
        assert messages[0].author == "alice"

    @pytest.mark.asyncio
    async def test_wait_for_activity_timeout_returns_empty(self, store):
        session, _ = store.create_session(title="Test")
        messages = await store.wait_for_activity(session.id, timeout=0.1)
        assert messages == []

    @pytest.mark.asyncio
    async def test_wait_returns_batched_messages(self, store):
        session, _ = store.create_session(title="Test")

        async def post_two():
            await asyncio.sleep(0.05)
            store.add_message(session.id, "alice", "First")
            store.add_message(session.id, "bob", "Second")

        asyncio.create_task(post_two())
        messages = await store.wait_for_activity(session.id, timeout=2.0)
        assert len(messages) >= 2


class TestUpdateLastSeen:
    def test_update_last_seen(self, store):
        session, _ = store.create_session(title="Test", participant_names=["alice"])
        now = datetime.now(timezone.utc)
        store.update_last_seen(session.id, "alice", now)
        updated = store.get_session(session.id)
        assert updated.participants[0].last_seen == now
