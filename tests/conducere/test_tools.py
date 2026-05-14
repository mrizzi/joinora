import pytest

from conducere.session_store import SessionStore
from conducere.tools import (
    create_session,
    end_session,
    get_catchup_summary,
    get_session_status,
    post_message,
)


@pytest.fixture
def store(tmp_path):
    return SessionStore(repo_path=tmp_path)


class TestCreateSessionTool:
    @pytest.mark.asyncio
    async def test_creates_session_returns_id_and_url(self, store):
        result = await create_session(
            store=store,
            title="Define Feature X",
            host="localhost",
            port=24298,
        )
        assert "session_id" in result
        assert "session_url" in result
        assert "localhost:24298" in result["session_url"]
        assert "participant_urls" not in result


class TestPostMessageTool:
    @pytest.mark.asyncio
    async def test_post_plain_message(self, store):
        session = store.create_session(title="Test")
        result = await post_message(
            store=store, session_id=session.id, text="Hello everyone"
        )
        assert "message_id" in result
        messages = store.get_messages(session.id)
        assert len(messages) == 1
        assert messages[0].author == "ai"

    @pytest.mark.asyncio
    async def test_post_message_with_metadata(self, store):
        session = store.create_session(title="Test")
        await post_message(
            store=store,
            session_id=session.id,
            text="What is this feature?",
            metadata={"type": "question", "section": "overview"},
        )
        messages = store.get_messages(session.id)
        assert messages[0].metadata["type"] == "question"

    @pytest.mark.asyncio
    async def test_post_to_nonexistent_raises(self, store):
        with pytest.raises(ValueError):
            await post_message(store=store, session_id="no-such-id", text="Hello")


class TestGetSessionStatusTool:
    @pytest.mark.asyncio
    async def test_returns_status(self, store):
        session = store.create_session(title="Test")
        store.add_participant(session.id, "alice")
        store.add_message(session.id, "alice", "Hi")
        result = await get_session_status(store=store, session_id=session.id)
        assert result["status"] == "active"
        assert result["message_count"] == 1
        assert len(result["participants"]) == 1

    @pytest.mark.asyncio
    async def test_nonexistent_session_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            await get_session_status(store=store, session_id="no-such-id")


class TestGetCatchupSummaryTool:
    @pytest.mark.asyncio
    async def test_returns_messages_since(self, store):
        session = store.create_session(title="Test")
        msg1 = store.add_message(session.id, "alice", "First")
        store.add_message(session.id, "bob", "Second")
        result = await get_catchup_summary(
            store=store,
            session_id=session.id,
            since=msg1.timestamp.isoformat(),
        )
        assert len(result["messages"]) == 1
        assert result["messages"][0]["text"] == "Second"

    @pytest.mark.asyncio
    async def test_nonexistent_session_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            await get_catchup_summary(store=store, session_id="no-such-id")

    @pytest.mark.asyncio
    async def test_malformed_since_raises(self, store):
        session = store.create_session(title="Test")
        with pytest.raises(ValueError):
            await get_catchup_summary(
                store=store, session_id=session.id, since="not-a-date"
            )


class TestEndSessionTool:
    @pytest.mark.asyncio
    async def test_ends_session(self, store):
        session = store.create_session(title="Test")
        result = await end_session(store=store, session_id=session.id)
        assert result["status"] == "complete"
        updated = store.get_session(session.id)
        assert updated.status.value == "complete"

    @pytest.mark.asyncio
    async def test_nonexistent_session_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            await end_session(store=store, session_id="no-such-id")


class TestMCPServerCreation:
    def test_server_creates_with_tools(self, tmp_path):
        from conducere.server import create_server

        server = create_server(repo_path=tmp_path)
        assert server is not None
