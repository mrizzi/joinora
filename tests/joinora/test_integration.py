import asyncio

import pytest
from fastapi.testclient import TestClient

from joinora.models import MessageEvent
from joinora.server import create_server
from joinora.web import create_web_app


@pytest.fixture
def setup(tmp_path):
    server = create_server(repo_path=tmp_path, web_port=24299)
    store = server._store
    web_app = create_web_app(store=store)
    server._web_app = web_app
    client = TestClient(web_app)
    return server, store, client


class TestFullFlow:
    @pytest.mark.asyncio
    async def test_agent_creates_session_posts_question_receives_answer(self, setup):
        server, store, client = setup

        from joinora.tools import create_session, post_message

        result = await create_session(
            store=store,
            title="Define Feature X",
            host="localhost",
            port=24299,
        )
        session_id = result["session_id"]
        assert result["session_url"]

        alice_token = store.add_participant(session_id, "alice")
        store.add_participant(session_id, "bob")

        await post_message(
            store=store,
            session_id=session_id,
            text="What problem does this feature solve?",
            metadata={"type": "question", "section": "overview"},
        )

        messages = store.get_messages(session_id)
        assert len(messages) == 1
        assert messages[0].metadata["type"] == "question"

        resp = client.post(
            f"/api/sessions/{session_id}/messages?token={alice_token}",
            json={
                "text": "It solves the onboarding problem",
            },
        )
        assert resp.status_code == 201

        messages = store.get_messages(session_id)
        assert len(messages) == 2
        assert messages[1].author == "alice"

    @pytest.mark.asyncio
    async def test_watch_session_receives_participant_message(self, setup):
        server, store, client = setup

        from joinora.tools import create_session

        result = await create_session(
            store=store,
            title="Test Watch",
            host="localhost",
            port=24299,
        )
        session_id = result["session_id"]

        store.add_participant(session_id, "alice")

        async def post_after_delay():
            await asyncio.sleep(0.1)
            store.add_message(session_id, "alice", "My answer")

        asyncio.create_task(post_after_delay())

        events = await store.wait_for_activity(session_id, timeout=2.0)
        assert len(events) >= 1
        assert isinstance(events[0], MessageEvent)
        assert events[0].message.author == "alice"
        assert events[0].message.text == "My answer"

    @pytest.mark.asyncio
    async def test_session_lifecycle(self, setup):
        server, store, client = setup

        from joinora.tools import (
            create_session,
            end_session,
            get_session_status,
            post_message,
        )

        result = await create_session(
            store=store,
            title="Lifecycle Test",
            host="localhost",
            port=24299,
        )
        session_id = result["session_id"]

        await post_message(store=store, session_id=session_id, text="Hello")

        status = await get_session_status(store=store, session_id=session_id)
        assert status["status"] == "active"
        assert status["message_count"] == 1

        record = await end_session(store=store, session_id=session_id)
        assert record["status"] == "complete"
