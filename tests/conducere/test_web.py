import asyncio
import threading

import pytest
from fastapi.testclient import TestClient

from conducere.session_store import SessionStore
from conducere.web import create_web_app


@pytest.fixture
def store(tmp_path):
    return SessionStore(repo_path=tmp_path)


@pytest.fixture
def client(store):
    app = create_web_app(store=store)
    return TestClient(app)


class TestSessionAPI:
    def test_get_without_token_returns_limited_info(self, client, store):
        session = store.create_session(title="Test")
        store.add_participant(session.id, "alice")
        resp = client.get(f"/api/sessions/{session.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == session.id
        assert data["title"] == "Test"
        assert data["status"] == "active"
        assert data["participant_count"] == 1
        assert "current_user" not in data
        assert "participants" not in data

    def test_nonexistent_session_returns_404(self, client, store):
        resp = client.get("/api/sessions/no-such-id")
        assert resp.status_code == 404

    def test_get_existing_session(self, client, store):
        session = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        resp = client.get(f"/api/sessions/{session.id}", params={"token": token})
        assert resp.status_code == 200
        assert resp.json()["title"] == "Test"
        assert resp.json()["current_user"] == "alice"

    def test_current_user_reflects_caller(self, client, store):
        session = store.create_session(title="Test")
        token_alice = store.add_participant(session.id, "alice")
        token_bob = store.add_participant(session.id, "bob")
        resp_alice = client.get(
            f"/api/sessions/{session.id}", params={"token": token_alice}
        )
        resp_bob = client.get(
            f"/api/sessions/{session.id}", params={"token": token_bob}
        )
        assert resp_alice.json()["current_user"] == "alice"
        assert resp_bob.json()["current_user"] == "bob"


class TestMessageAPI:
    def test_post_message(self, client, store):
        session = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        resp = client.post(
            f"/api/sessions/{session.id}/messages",
            json={"text": "Hello"},
            params={"token": token},
        )
        assert resp.status_code == 201
        assert resp.json()["author"] == "alice"

    def test_post_without_auth_rejected(self, client, store):
        session = store.create_session(title="Test")
        resp = client.post(
            f"/api/sessions/{session.id}/messages",
            json={"text": "Hello"},
        )
        assert resp.status_code == 401

    def test_get_messages(self, client, store):
        session = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        client.post(
            f"/api/sessions/{session.id}/messages",
            json={"text": "Hello"},
            params={"token": token},
        )
        resp = client.get(
            f"/api/sessions/{session.id}/messages",
            params={"token": token},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_messages_without_auth_rejected(self, client, store):
        session = store.create_session(title="Test")
        resp = client.get(f"/api/sessions/{session.id}/messages")
        assert resp.status_code == 401

    def test_post_to_completed_session_returns_400(self, client, store):
        session = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        store.end_session(session.id)
        resp = client.post(
            f"/api/sessions/{session.id}/messages",
            json={"text": "Too late"},
            params={"token": token},
        )
        assert resp.status_code == 400

    def test_security_headers_present(self, client, store):
        session = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        resp = client.get(
            f"/api/sessions/{session.id}",
            params={"token": token},
        )
        assert "Content-Security-Policy" in resp.headers
        assert "X-Content-Type-Options" in resp.headers
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "no-referrer"


class TestReservedNames:
    def test_reject_ai_participant_name(self, store):
        session = store.create_session(title="Test")
        with pytest.raises(ValueError, match="reserved"):
            store.add_participant(session.id, "ai")

    def test_reject_system_participant_name(self, store):
        session = store.create_session(title="Test")
        with pytest.raises(ValueError, match="reserved"):
            store.add_participant(session.id, "System")


class TestWebSocket:
    def test_websocket_receives_messages(self, client, store):
        session = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        with client.websocket_connect(f"/ws/sessions/{session.id}?token={token}") as ws:
            joined_data = ws.receive_json()
            assert joined_data["type"] == "participant_joined"

            client.post(
                f"/api/sessions/{session.id}/messages",
                json={"text": "Hello"},
                params={"token": token},
            )
            data = ws.receive_json()
            assert data["type"] == "message_added"
            assert data["message"]["text"] == "Hello"

    def test_websocket_without_auth_rejected(self, client, store):
        session = store.create_session(title="Test")
        with pytest.raises(Exception):
            with client.websocket_connect(f"/ws/sessions/{session.id}") as ws:
                ws.receive_json()


class TestAgentStateWebSocket:
    def test_agent_listening_broadcast_on_watch(self, client, store):
        session = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")

        async def trigger_watch():
            await asyncio.sleep(0.05)
            await store.wait_for_activity(session.id, timeout=0.1)

        with client.websocket_connect(f"/ws/sessions/{session.id}?token={token}") as ws:
            ws.receive_json()  # participant_joined

            loop = asyncio.new_event_loop()
            t = threading.Thread(
                target=loop.run_until_complete, args=(trigger_watch(),)
            )
            t.start()
            t.join(timeout=5.0)

            data = ws.receive_json()
            assert data["type"] == "agent_listening"
            data2 = ws.receive_json()
            assert data2["type"] == "agent_disconnected"

    def test_agent_processing_broadcast_on_message(self, client, store):
        session = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")

        async def trigger_watch_with_message():
            async def post_soon():
                await asyncio.sleep(0.1)
                store.add_message(session.id, "alice", "Hi")

            asyncio.ensure_future(post_soon())
            await store.wait_for_activity(session.id, timeout=2.0)

        with client.websocket_connect(f"/ws/sessions/{session.id}?token={token}") as ws:
            ws.receive_json()  # participant_joined

            loop = asyncio.new_event_loop()
            t = threading.Thread(
                target=loop.run_until_complete,
                args=(trigger_watch_with_message(),),
            )
            t.start()
            t.join(timeout=5.0)

            data = ws.receive_json()
            assert data["type"] == "agent_listening"
            data2 = ws.receive_json()
            assert data2["type"] == "agent_processing"


class TestJoinAPI:
    def test_join_session(self, client, store):
        session = store.create_session(title="Test")
        resp = client.post(
            f"/api/sessions/{session.id}/join",
            json={"name": "alice"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "alice"
        assert "token" in data

    def test_join_token_authenticates(self, client, store):
        session = store.create_session(title="Test")
        resp = client.post(
            f"/api/sessions/{session.id}/join",
            json={"name": "alice"},
        )
        token = resp.json()["token"]
        msg_resp = client.post(
            f"/api/sessions/{session.id}/messages",
            json={"text": "Hello"},
            params={"token": token},
        )
        assert msg_resp.status_code == 201
        assert msg_resp.json()["author"] == "alice"

    def test_join_duplicate_name_returns_409(self, client, store):
        session = store.create_session(title="Test")
        client.post(
            f"/api/sessions/{session.id}/join",
            json={"name": "alice"},
        )
        resp = client.post(
            f"/api/sessions/{session.id}/join",
            json={"name": "alice"},
        )
        assert resp.status_code == 409

    def test_join_reserved_name_returns_422(self, client, store):
        session = store.create_session(title="Test")
        resp = client.post(
            f"/api/sessions/{session.id}/join",
            json={"name": "ai"},
        )
        assert resp.status_code == 422

    def test_join_empty_name_returns_422(self, client, store):
        session = store.create_session(title="Test")
        resp = client.post(
            f"/api/sessions/{session.id}/join",
            json={"name": ""},
        )
        assert resp.status_code == 422

    def test_join_nonexistent_session_returns_404(self, client):
        resp = client.post(
            "/api/sessions/no-such-id/join",
            json={"name": "alice"},
        )
        assert resp.status_code == 404

    def test_join_completed_session_returns_410(self, client, store):
        session = store.create_session(title="Test")
        store.end_session(session.id)
        resp = client.post(
            f"/api/sessions/{session.id}/join",
            json={"name": "alice"},
        )
        assert resp.status_code == 410

    def test_join_broadcasts_websocket(self, client, store):
        session = store.create_session(title="Test")
        first_token = store.add_participant(session.id, "alice")
        with client.websocket_connect(
            f"/ws/sessions/{session.id}?token={first_token}"
        ) as ws:
            ws.receive_json()  # alice's own participant_joined
            client.post(
                f"/api/sessions/{session.id}/join",
                json={"name": "bob"},
            )
            data = ws.receive_json()
            assert data["type"] == "participant_joined"
            assert data["user"] == "bob"
