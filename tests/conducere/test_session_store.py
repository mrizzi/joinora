import asyncio
from datetime import datetime, timezone

import pytest

from conducere.models import AgentState, SessionStatus
from conducere.session_store import SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(repo_path=tmp_path)


class TestCreateSession:
    def test_create_returns_session(self, store):
        session = store.create_session(title="Test Session")
        assert session.id
        assert session.status == SessionStatus.ACTIVE
        assert len(session.participants) == 0

    def test_create_generates_unique_ids(self, store):
        s1 = store.create_session(title="A")
        s2 = store.create_session(title="B")
        assert s1.id != s2.id

    def test_create_persists_to_git(self, store):
        session = store.create_session(title="Persisted")
        content = store._git.read_file(f"sessions/{session.id}/session.json")
        assert content is not None
        assert "Persisted" in content

    def test_session_json_does_not_contain_tokens(self, store):
        session = store.create_session(title="Secrets")
        token = store.add_participant(session.id, "alice")
        content = store._git.read_file(f"sessions/{session.id}/session.json")
        assert token not in content

    def test_returns_copy_not_reference(self, store):
        session = store.create_session(title="Test")
        session.title = "Mutated"
        fetched = store.get_session(session.id)
        assert fetched.title == "Test"


class TestAuthenticate:
    def test_valid_token(self, store):
        session = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        user = store.authenticate(session.id, token)
        assert user == "alice"

    def test_invalid_token(self, store):
        session = store.create_session(title="Test")
        store.add_participant(session.id, "alice")
        assert store.authenticate(session.id, "bad-token") is None

    def test_nonexistent_session(self, store):
        assert store.authenticate("no-such-id", "token") is None


class TestGetSession:
    def test_get_existing_session(self, store):
        created = store.create_session(title="Test")
        fetched = store.get_session(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_nonexistent_returns_none(self, store):
        assert store.get_session("no-such-id") is None

    def test_get_returns_copy(self, store):
        session = store.create_session(title="Test")
        fetched = store.get_session(session.id)
        fetched.messages.append(None)
        refetched = store.get_session(session.id)
        assert len(refetched.messages) == 0


class TestAddMessage:
    def test_add_message_returns_message(self, store):
        session = store.create_session(title="Test")
        msg = store.add_message(
            session_id=session.id,
            author="alice",
            text="Hello",
        )
        assert msg.id.startswith("msg-")
        assert msg.author == "alice"
        assert msg.text == "Hello"

    def test_add_message_with_metadata(self, store):
        session = store.create_session(title="Test")
        msg = store.add_message(
            session_id=session.id,
            author="ai",
            text="What is the feature?",
            metadata={"type": "question"},
        )
        assert msg.metadata == {"type": "question"}

    def test_messages_are_ordered(self, store):
        session = store.create_session(title="Test")
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
        session = store.create_session(title="Test")
        store.end_session(session.id)
        with pytest.raises(ValueError, match="not active"):
            store.add_message(session.id, "alice", "Hello")

    def test_add_message_creates_git_commit(self, store):
        session = store.create_session(title="Test")
        store.add_message(session.id, "alice", "Hello")
        log = store._git.log(f"sessions/{session.id}")
        assert any("message: alice" in entry["message"] for entry in log)


class TestGetMessages:
    def test_get_messages_since(self, store):
        session = store.create_session(title="Test")
        msg1 = store.add_message(session.id, "alice", "First")
        store.add_message(session.id, "bob", "Second")
        since = msg1.timestamp
        messages = store.get_messages(session.id, since=since)
        assert len(messages) == 1
        assert messages[0].text == "Second"


class TestEndSession:
    def test_end_session_marks_complete(self, store):
        session = store.create_session(title="Test")
        record = store.end_session(session.id)
        assert record["status"] == "complete"
        updated = store.get_session(session.id)
        assert updated.status == SessionStatus.COMPLETE

    def test_end_nonexistent_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.end_session("no-such-id")


class TestUpdateLastSeen:
    def test_update_last_seen(self, store):
        session = store.create_session(title="Test")
        store.add_participant(session.id, "alice")
        now = datetime.now(timezone.utc)
        store.update_last_seen(session.id, "alice", now)
        updated = store.get_session(session.id)
        assert updated.participants[0].last_seen == now


class TestAddParticipant:
    def test_add_participant_returns_token(self, store):
        session = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_add_participant_appears_in_session(self, store):
        session = store.create_session(title="Test")
        store.add_participant(session.id, "alice")
        updated = store.get_session(session.id)
        assert len(updated.participants) == 1
        assert updated.participants[0].name == "alice"

    def test_add_participant_token_authenticates(self, store):
        session = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        assert store.authenticate(session.id, token) == "alice"

    def test_duplicate_name_raises(self, store):
        session = store.create_session(title="Test")
        store.add_participant(session.id, "alice")
        with pytest.raises(ValueError, match="already taken"):
            store.add_participant(session.id, "alice")

    def test_reserved_name_raises(self, store):
        session = store.create_session(title="Test")
        with pytest.raises(ValueError, match="reserved"):
            store.add_participant(session.id, "ai")

    def test_nonexistent_session_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.add_participant("no-such-id", "alice")

    def test_completed_session_raises(self, store):
        session = store.create_session(title="Test")
        store.end_session(session.id)
        with pytest.raises(ValueError, match="not active"):
            store.add_participant(session.id, "alice")

    def test_persists_token_to_git(self, store):
        session = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        content = store._git.read_file(f"sessions/{session.id}/tokens.json")
        assert content is not None
        import json

        tokens = json.loads(content)
        assert tokens["alice"] == token

    def test_persists_participant_to_git(self, store):
        session = store.create_session(title="Test")
        store.add_participant(session.id, "alice")
        content = store._git.read_file(f"sessions/{session.id}/session.json")
        assert "alice" in content


class TestGetParticipantTokens:
    def test_returns_tokens_for_session(self, store):
        session = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        tokens = store.get_participant_tokens(session.id)
        assert tokens == {"alice": token}

    def test_returns_empty_for_no_participants(self, store):
        session = store.create_session(title="Test")
        assert store.get_participant_tokens(session.id) == {}

    def test_returns_empty_for_nonexistent_session(self, store):
        assert store.get_participant_tokens("no-such-id") == {}


class TestSubscriberNotification:
    @pytest.mark.asyncio
    async def test_wait_for_activity_returns_on_message(self, store):
        session = store.create_session(title="Test")

        async def post_after_delay():
            await asyncio.sleep(0.1)
            store.add_message(session.id, "alice", "Hello")

        asyncio.create_task(post_after_delay())
        events = await store.wait_for_activity(session.id, timeout=2.0)
        assert len(events) >= 1
        assert events[0]["type"] == "message"
        assert events[0]["message"].author == "alice"

    @pytest.mark.asyncio
    async def test_wait_for_activity_timeout_returns_empty(self, store):
        session = store.create_session(title="Test")
        events = await store.wait_for_activity(session.id, timeout=0.1)
        assert events == []

    @pytest.mark.asyncio
    async def test_wait_returns_batched_messages(self, store):
        session = store.create_session(title="Test")

        async def post_two():
            await asyncio.sleep(0.05)
            store.add_message(session.id, "alice", "First")
            store.add_message(session.id, "bob", "Second")

        asyncio.create_task(post_two())
        events = await store.wait_for_activity(session.id, timeout=2.0)
        assert len(events) >= 2
        assert all(e["type"] == "message" for e in events)


class TestJoinWakesWatch:
    @pytest.mark.asyncio
    async def test_add_participant_wakes_watch(self, store):
        session = store.create_session(title="Test")

        async def join_after_delay():
            await asyncio.sleep(0.1)
            store.add_participant(session.id, "alice")

        asyncio.create_task(join_after_delay())
        events = await store.wait_for_activity(session.id, timeout=2.0)
        assert len(events) >= 1
        assert events[0]["type"] == "participant_joined"
        assert events[0]["participant"]["name"] == "alice"


class TestAgentStateCallback:
    @pytest.mark.asyncio
    async def test_callback_called_with_listening_on_entry(self, store):
        session = store.create_session(title="Test")
        states = []

        async def on_change(sid, state):
            states.append((sid, state))

        store.on_agent_state_change = on_change

        async def post_soon():
            await asyncio.sleep(0.05)
            store.add_message(session.id, "alice", "Hi")

        asyncio.create_task(post_soon())
        await store.wait_for_activity(session.id, timeout=2.0)
        assert states[0] == (session.id, AgentState.LISTENING)

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_abort_wait(self, store):
        session = store.create_session(title="Test")

        async def failing_callback(sid, state):
            raise RuntimeError("callback failure")

        store.on_agent_state_change = failing_callback

        async def post_soon():
            await asyncio.sleep(0.05)
            store.add_message(session.id, "alice", "Hi")

        asyncio.create_task(post_soon())
        events = await store.wait_for_activity(session.id, timeout=2.0)
        assert len(events) >= 1
        assert events[0]["message"].text == "Hi"

    @pytest.mark.asyncio
    async def test_callback_called_with_processing_on_message(self, store):
        session = store.create_session(title="Test")
        states = []

        async def on_change(sid, state):
            states.append((sid, state))

        store.on_agent_state_change = on_change

        async def post_soon():
            await asyncio.sleep(0.05)
            store.add_message(session.id, "alice", "Hi")

        asyncio.create_task(post_soon())
        await store.wait_for_activity(session.id, timeout=2.0)
        state_names = [s[1] for s in states]
        assert AgentState.PROCESSING in state_names

    @pytest.mark.asyncio
    async def test_callback_called_with_disconnected_on_timeout(self, store):
        session = store.create_session(title="Test")
        states = []

        async def on_change(sid, state):
            states.append((sid, state))

        store.on_agent_state_change = on_change
        await store.wait_for_activity(session.id, timeout=0.1)
        state_names = [s[1] for s in states]
        assert AgentState.LISTENING in state_names
        assert AgentState.DISCONNECTED in state_names

    @pytest.mark.asyncio
    async def test_no_callback_by_default(self, store):
        assert store.on_agent_state_change is None
        session = store.create_session(title="Test")
        await store.wait_for_activity(session.id, timeout=0.1)

    @pytest.mark.asyncio
    async def test_callback_receives_correct_session_id(self, store):
        session = store.create_session(title="Test")
        received_ids = []

        async def on_change(sid, state):
            received_ids.append(sid)

        store.on_agent_state_change = on_change
        await store.wait_for_activity(session.id, timeout=0.1)
        assert all(sid == session.id for sid in received_ids)

    @pytest.mark.asyncio
    async def test_state_transitions_are_ordered(self, store):
        session = store.create_session(title="Test")
        states = []

        async def on_change(sid, state):
            states.append(state)

        store.on_agent_state_change = on_change

        async def post_soon():
            await asyncio.sleep(0.05)
            store.add_message(session.id, "alice", "Hi")

        asyncio.create_task(post_soon())
        await store.wait_for_activity(session.id, timeout=2.0)
        assert len(states) == 2
        assert states[0] == AgentState.LISTENING
        assert states[1] == AgentState.PROCESSING


class TestStartupLoading:
    def test_loads_session_from_git(self, tmp_path):
        store1 = SessionStore(repo_path=tmp_path)
        session = store1.create_session(title="Persisted")
        store1.add_participant(session.id, "alice")
        store1.add_message(session.id, "alice", "Hello")

        store2 = SessionStore(repo_path=tmp_path)
        loaded = store2.get_session(session.id)
        assert loaded is not None
        assert loaded.title == "Persisted"
        assert len(loaded.participants) == 1
        assert loaded.participants[0].name == "alice"
        assert len(loaded.messages) == 1
        assert loaded.messages[0].text == "Hello"

    def test_loads_tokens_from_git(self, tmp_path):
        store1 = SessionStore(repo_path=tmp_path)
        session = store1.create_session(title="Test")
        token = store1.add_participant(session.id, "alice")

        store2 = SessionStore(repo_path=tmp_path)
        assert store2.authenticate(session.id, token) == "alice"

    def test_empty_repo_loads_nothing(self, tmp_path):
        store = SessionStore(repo_path=tmp_path)
        assert store.get_session("anything") is None

    def test_loads_multiple_sessions(self, tmp_path):
        store1 = SessionStore(repo_path=tmp_path)
        s1 = store1.create_session(title="First")
        s2 = store1.create_session(title="Second")

        store2 = SessionStore(repo_path=tmp_path)
        assert store2.get_session(s1.id) is not None
        assert store2.get_session(s2.id) is not None

    def test_loads_completed_session(self, tmp_path):
        store1 = SessionStore(repo_path=tmp_path)
        session = store1.create_session(title="Done")
        store1.end_session(session.id)

        store2 = SessionStore(repo_path=tmp_path)
        loaded = store2.get_session(session.id)
        assert loaded.status == SessionStatus.COMPLETE
