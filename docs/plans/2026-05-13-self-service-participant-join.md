# Self-Service Participant Join — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace pre-declared participants with a self-service invite link. Anyone with the session URL picks a name and joins. Sessions survive restarts.

**Architecture:** SessionStore gains `add_participant()` (creates participant + token on the fly), event-based pending queue (messages + joins wake `watch_session`), git-persisted tokens, and startup loading. A new `POST /api/sessions/{id}/join` web endpoint backs a frontend join overlay. Two new MCP tools (`list_sessions`, `reopen_session`) enable agent reconnection.

**Tech Stack:** Python 3.12+, FastMCP, FastAPI, pygit2, vanilla JS

**Spec:** `docs/specs/2026-05-13-self-service-participant-join-design.md`

---

### Task 1: Event model + add_participant in SessionStore

**Files:**
- Modify: `joinora/session_store.py`
- Test: `tests/joinora/test_session_store.py`

This task changes `_pending` from `list[Message]` to `list[dict]` (event dicts),
updates `add_message` / `wait_for_activity` to use events, and adds
`add_participant` + `get_participant_tokens`.

- [ ] **Step 1: Write failing tests for add_participant**

Add a new `TestAddParticipant` class to `tests/joinora/test_session_store.py`:

```python
class TestAddParticipant:
    def test_add_participant_returns_token(self, store):
        session, _ = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_add_participant_appears_in_session(self, store):
        session, _ = store.create_session(title="Test")
        store.add_participant(session.id, "alice")
        updated = store.get_session(session.id)
        assert len(updated.participants) == 1
        assert updated.participants[0].name == "alice"

    def test_add_participant_token_authenticates(self, store):
        session, _ = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        assert store.authenticate(session.id, token) == "alice"

    def test_duplicate_name_raises(self, store):
        session, _ = store.create_session(title="Test")
        store.add_participant(session.id, "alice")
        with pytest.raises(ValueError, match="already taken"):
            store.add_participant(session.id, "alice")

    def test_reserved_name_raises(self, store):
        session, _ = store.create_session(title="Test")
        with pytest.raises(ValueError, match="reserved"):
            store.add_participant(session.id, "ai")

    def test_nonexistent_session_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.add_participant("no-such-id", "alice")

    def test_completed_session_raises(self, store):
        session, _ = store.create_session(title="Test")
        store.end_session(session.id)
        with pytest.raises(ValueError, match="not active"):
            store.add_participant(session.id, "alice")

    def test_persists_token_to_git(self, store):
        session, _ = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        content = store._git.read_file(f"sessions/{session.id}/tokens.json")
        assert content is not None
        import json
        tokens = json.loads(content)
        assert tokens["alice"] == token

    def test_persists_participant_to_git(self, store):
        session, _ = store.create_session(title="Test")
        store.add_participant(session.id, "alice")
        content = store._git.read_file(f"sessions/{session.id}/session.json")
        assert "alice" in content
```

- [ ] **Step 2: Write failing tests for event model**

Add a new `TestGetParticipantTokens` class and update `TestSubscriberNotification`:

```python
class TestGetParticipantTokens:
    def test_returns_tokens_for_session(self, store):
        session, _ = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        tokens = store.get_participant_tokens(session.id)
        assert tokens == {"alice": token}

    def test_returns_empty_for_no_participants(self, store):
        session, _ = store.create_session(title="Test")
        assert store.get_participant_tokens(session.id) == {}

    def test_returns_empty_for_nonexistent_session(self, store):
        assert store.get_participant_tokens("no-such-id") == {}
```

Update `TestSubscriberNotification` to use event dicts:

```python
class TestSubscriberNotification:
    @pytest.mark.asyncio
    async def test_wait_for_activity_returns_on_message(self, store):
        session, _ = store.create_session(title="Test")

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
        session, _ = store.create_session(title="Test")
        events = await store.wait_for_activity(session.id, timeout=0.1)
        assert events == []

    @pytest.mark.asyncio
    async def test_wait_returns_batched_messages(self, store):
        session, _ = store.create_session(title="Test")

        async def post_two():
            await asyncio.sleep(0.05)
            store.add_message(session.id, "alice", "First")
            store.add_message(session.id, "bob", "Second")

        asyncio.create_task(post_two())
        events = await store.wait_for_activity(session.id, timeout=2.0)
        assert len(events) >= 2
        assert all(e["type"] == "message" for e in events)
```

Add a test for join events waking `watch_session`:

```python
class TestJoinWakesWatch:
    @pytest.mark.asyncio
    async def test_add_participant_wakes_watch(self, store):
        session, _ = store.create_session(title="Test")

        async def join_after_delay():
            await asyncio.sleep(0.1)
            store.add_participant(session.id, "alice")

        asyncio.create_task(join_after_delay())
        events = await store.wait_for_activity(session.id, timeout=2.0)
        assert len(events) >= 1
        assert events[0]["type"] == "participant_joined"
        assert events[0]["participant"]["name"] == "alice"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/joinora/test_session_store.py -v -x 2>&1 | tail -20`

Expected: FAIL — `add_participant`, `get_participant_tokens` not defined; existing
`wait_for_activity` tests fail on return format.

- [ ] **Step 4: Implement event model + add_participant**

In `joinora/session_store.py`, make these changes:

1. Change `_pending` type annotation in `__init__` (line 24):

```python
        self._pending: dict[str, list[dict]] = {}
```

2. Update `add_message` (around line 120) — change the line that appends to `_pending`:

```python
            self._pending.setdefault(session_id, []).append(
                {"type": "message", "message": message}
            )
```

3. Update `wait_for_activity` (around line 191-194) — change variable names from `messages` to `events`:

```python
        with self._lock:
            events = self._pending.get(session_id, [])
            self._pending[session_id] = []
            self._events.pop(session_id, None)
            self._loops.pop(session_id, None)

        if self.on_agent_state_change:
            state = AgentState.PROCESSING if events else AgentState.DISCONNECTED
            try:
                await self.on_agent_state_change(session_id, state)
            except Exception:
                logger.warning("agent state callback failed", exc_info=True)

        return events
```

4. Add `add_participant` method after `create_session`:

```python
    def add_participant(self, session_id: str, name: str) -> str:
        participant = Participant(name=name)
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError(f"Session '{session_id}' not found")
            if session.status != SessionStatus.ACTIVE:
                raise ValueError(f"Session '{session_id}' is not active")
            if any(p.name == name for p in session.participants):
                raise ValueError(f"Name '{name}' is already taken in this session")

            token = secrets.token_urlsafe(16)
            session.participants.append(participant)
            self._tokens.setdefault(session_id, {})[name] = token
            self._pending.setdefault(session_id, []).append(
                {"type": "participant_joined", "participant": {"name": name}}
            )

        base = self._session_dir(session_id)
        self._git.commit(
            f"join: {name} in {session_id}",
            {
                f"{base}/session.json": session.model_dump_json(indent=2),
                f"{base}/tokens.json": json.dumps(
                    self._tokens[session_id], indent=2
                ),
            },
        )
        with self._lock:
            event = self._events.get(session_id)
            loop = self._loops.get(session_id)
        if event and loop:
            loop.call_soon_threadsafe(event.set)
        return token
```

5. Add `get_participant_tokens` method after `authenticate`:

```python
    def get_participant_tokens(self, session_id: str) -> dict[str, str]:
        with self._lock:
            return dict(self._tokens.get(session_id, {}))
```

6. Update `TestAgentStateCallback.test_callback_exception_does_not_abort_wait` to
use event format (the assertion at the end):

```python
        events = await store.wait_for_activity(session.id, timeout=2.0)
        assert len(events) >= 1
        assert events[0]["message"].text == "Hi"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/joinora/test_session_store.py -v 2>&1 | tail -30`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add joinora/session_store.py tests/joinora/test_session_store.py
git commit -m "feat: add event model + add_participant to SessionStore"
```

---

### Task 2: Remove participant_names from create_session

**Files:**
- Modify: `joinora/session_store.py:49-80`
- Modify: `joinora/tools.py:7-25`
- Modify: `joinora/server.py:28-43`
- Modify: `joinora/web.py:55-74`
- Modify: `tests/joinora/test_session_store.py`
- Modify: `tests/joinora/test_tools.py`
- Modify: `tests/joinora/test_web.py`
- Modify: `tests/joinora/test_integration.py`

This is a large mechanical refactor. `create_session` drops `participant_names`,
its return type changes from `tuple[Session, dict]` to `Session`, and every caller
and test is updated to use `add_participant` instead.

- [ ] **Step 1: Update SessionStore.create_session**

Replace `create_session` in `joinora/session_store.py` (lines 49-80):

```python
    def create_session(self, title: str) -> Session:
        session_id = secrets.token_urlsafe(12)
        session = Session(
            id=session_id,
            title=title,
            created_at=datetime.now(timezone.utc),
        )
        base = self._session_dir(session_id)
        self._git.commit(
            f"init: session '{title}'",
            {
                f"{base}/session.json": session.model_dump_json(indent=2),
                f"{base}/messages.json": "[]",
            },
        )
        with self._lock:
            self._sessions[session_id] = session
            self._pending[session_id] = []
        return session.model_copy(deep=True)
```

- [ ] **Step 2: Update tools.create_session**

Replace in `joinora/tools.py` (lines 7-25):

```python
async def create_session(
    store: SessionStore,
    title: str,
    host: str,
    port: int,
) -> dict:
    session = store.create_session(title=title)
    base_url = f"http://{host}:{port}/session/{session.id}"
    return {
        "session_id": session.id,
        "session_url": base_url,
    }
```

- [ ] **Step 3: Update server.py MCP tool**

Replace in `joinora/server.py` (lines 28-43):

```python
    @mcp.tool()
    async def create_session(title: str) -> dict:
        """Create a new collaborative session. Returns session_id and
        a session_url to share with participants."""
        from joinora.tools import create_session as _create

        return await _create(
            store=store,
            title=title,
            host=web_host,
            port=web_port,
        )
```

- [ ] **Step 4: Update test_session_store.py**

Apply these changes throughout `tests/joinora/test_session_store.py`:

**Pattern A** — change destructuring (most tests):
`session, _ = store.create_session(title="Test")` becomes `session = store.create_session(title="Test")`

This applies to every test in: `TestCreateSession` (except the ones below),
`TestGetSession`, `TestAddMessage`, `TestGetMessages`, `TestEndSession`,
`TestSubscriberNotification`, `TestAgentStateCallback`, `TestAddParticipant`,
`TestGetParticipantTokens`, `TestJoinWakesWatch`.

**Specific test changes:**

Delete `test_create_with_participants` (no longer applicable).

Rewrite `test_git_does_not_contain_tokens`:

```python
    def test_session_json_does_not_contain_tokens(self, store):
        session = store.create_session(title="Secrets")
        token = store.add_participant(session.id, "alice")
        content = store._git.read_file(f"sessions/{session.id}/session.json")
        assert token not in content
```

Rewrite `TestAuthenticate`:

```python
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
```

Rewrite `TestUpdateLastSeen`:

```python
class TestUpdateLastSeen:
    def test_update_last_seen(self, store):
        session = store.create_session(title="Test")
        store.add_participant(session.id, "alice")
        now = datetime.now(timezone.utc)
        store.update_last_seen(session.id, "alice", now)
        updated = store.get_session(session.id)
        assert updated.participants[0].last_seen == now
```

- [ ] **Step 5: Update test_tools.py**

In `tests/joinora/test_tools.py`:

Rewrite `TestCreateSessionTool`:

```python
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
```

Delete `test_creates_session_with_participants`.

Update all other tests — change `session, _tokens = store.create_session(...)` to
`session = store.create_session(...)`.

For `TestGetSessionStatusTool`, add a participant via `add_participant`:

```python
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
```

- [ ] **Step 6: Update test_web.py**

In `tests/joinora/test_web.py`, every test that uses `participant_names` must
switch to `add_participant`. Here is the full updated file:

```python
import asyncio
import threading

import pytest
from fastapi.testclient import TestClient

from joinora.session_store import SessionStore
from joinora.web import create_web_app


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
        assert data["title"] == "Test"
        assert "current_user" not in data
        assert "messages" not in data

    def test_get_existing_session(self, client, store):
        session = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        resp = client.get(
            f"/api/sessions/{session.id}", params={"token": token}
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Test"
        assert resp.json()["current_user"] == "alice"

    def test_current_user_reflects_caller(self, client, store):
        session = store.create_session(title="Test")
        token_a = store.add_participant(session.id, "alice")
        token_b = store.add_participant(session.id, "bob")
        resp_alice = client.get(
            f"/api/sessions/{session.id}", params={"token": token_a}
        )
        resp_bob = client.get(
            f"/api/sessions/{session.id}", params={"token": token_b}
        )
        assert resp_alice.json()["current_user"] == "alice"
        assert resp_bob.json()["current_user"] == "bob"

    def test_nonexistent_session_returns_404(self, client):
        resp = client.get("/api/sessions/no-such-id")
        assert resp.status_code == 404


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
        with client.websocket_connect(
            f"/ws/sessions/{session.id}?token={token}"
        ) as ws:
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
            with client.websocket_connect(
                f"/ws/sessions/{session.id}"
            ) as ws:
                ws.receive_json()


class TestAgentStateWebSocket:
    def test_agent_listening_broadcast_on_watch(self, client, store):
        session = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")

        async def trigger_watch():
            await asyncio.sleep(0.05)
            await store.wait_for_activity(session.id, timeout=0.1)

        with client.websocket_connect(
            f"/ws/sessions/{session.id}?token={token}"
        ) as ws:
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

        with client.websocket_connect(
            f"/ws/sessions/{session.id}?token={token}"
        ) as ws:
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
```

- [ ] **Step 7: Update web.py — allow unauthenticated session info**

Replace `get_session` endpoint in `joinora/web.py` (lines 55-74):

```python
    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str, token: str | None = None):
        session = store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        user = _authenticate(session_id, token)
        if user is None:
            return {
                "id": session.id,
                "title": session.title,
                "status": session.status.value,
                "participant_count": len(session.participants),
            }

        data = session.model_dump(mode="json")
        data["current_user"] = user
        participant = next(
            (p for p in session.participants if p.name == user), None
        )
        data["last_seen"] = (
            participant.last_seen.isoformat()
            if participant and participant.last_seen
            else None
        )
        for p in data.get("participants", []):
            p.pop("token", None)
        data.pop("messages", None)
        return data
```

- [ ] **Step 8: Update test_integration.py**

Replace the full file:

```python
import asyncio

import pytest
from fastapi.testclient import TestClient

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
    async def test_agent_creates_session_participant_joins_and_posts(self, setup):
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
        assert "participant_urls" not in result

        await post_message(
            store=store,
            session_id=session_id,
            text="What problem does this feature solve?",
            metadata={"type": "question", "section": "overview"},
        )

        messages = store.get_messages(session_id)
        assert len(messages) == 1
        assert messages[0].metadata["type"] == "question"

        alice_token = store.add_participant(session_id, "alice")
        resp = client.post(
            f"/api/sessions/{session_id}/messages?token={alice_token}",
            json={"text": "It solves the onboarding problem"},
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

        async def post_after_delay():
            await asyncio.sleep(0.1)
            store.add_message(session_id, "alice", "My answer")

        asyncio.create_task(post_after_delay())

        events = await store.wait_for_activity(session_id, timeout=2.0)
        assert len(events) >= 1
        assert events[0]["type"] == "message"
        assert events[0]["message"].author == "alice"
        assert events[0]["message"].text == "My answer"

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
```

- [ ] **Step 9: Run the full test suite**

Run: `python3 -m pytest tests/ -v 2>&1 | tail -30`

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add joinora/session_store.py joinora/tools.py joinora/server.py joinora/web.py tests/
git commit -m "refactor: remove participant_names from create_session, use add_participant"
```

---

### Task 3: Startup loading in SessionStore

**Files:**
- Modify: `joinora/session_store.py`
- Test: `tests/joinora/test_session_store.py`

`SessionStore.__init__` loads all sessions, messages, and tokens from the git
repo so sessions survive server restarts.

- [ ] **Step 1: Write failing tests**

Add to `tests/joinora/test_session_store.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/joinora/test_session_store.py::TestStartupLoading -v`

Expected: FAIL — `store2.get_session()` returns None because sessions aren't loaded
on startup.

- [ ] **Step 3: Implement startup loading**

Add `_load_from_git` method to `SessionStore` in `joinora/session_store.py`, and
call it at the end of `__init__`:

At the end of `__init__`, after `self.on_agent_state_change = None`, add:

```python
        self._load_from_git()
```

Add the method after `__init__`:

```python
    def _load_from_git(self) -> None:
        for sid in self._git.list_directory("sessions"):
            session_json = self._git.read_file(f"sessions/{sid}/session.json")
            if session_json is None:
                continue
            session = Session.model_validate_json(session_json)

            messages_json = self._git.read_file(f"sessions/{sid}/messages.json")
            if messages_json:
                session.messages = [
                    Message.model_validate(m) for m in json.loads(messages_json)
                ]

            tokens_json = self._git.read_file(f"sessions/{sid}/tokens.json")
            if tokens_json:
                self._tokens[sid] = json.loads(tokens_json)

            self._sessions[sid] = session
            self._pending[sid] = []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/joinora/test_session_store.py -v 2>&1 | tail -30`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add joinora/session_store.py tests/joinora/test_session_store.py
git commit -m "feat: load sessions, messages, and tokens from git on startup"
```

---

### Task 4: New MCP tools — list_sessions + reopen_session

**Files:**
- Modify: `joinora/session_store.py`
- Modify: `joinora/tools.py`
- Modify: `joinora/server.py`
- Test: `tests/joinora/test_session_store.py`
- Test: `tests/joinora/test_tools.py`

Adds `list_all_sessions()` and `reopen_session()` to `SessionStore`, tool functions
in `tools.py`, and MCP wrappers in `server.py`.

- [ ] **Step 1: Write failing tests for SessionStore methods**

Add to `tests/joinora/test_session_store.py`:

```python
class TestListAllSessions:
    def test_returns_all_sessions(self, store):
        s1 = store.create_session(title="First")
        s2 = store.create_session(title="Second")
        sessions = store.list_all_sessions()
        ids = {s.id for s in sessions}
        assert s1.id in ids
        assert s2.id in ids

    def test_returns_empty_when_none(self, store):
        assert store.list_all_sessions() == []

    def test_returns_copies(self, store):
        store.create_session(title="Test")
        sessions = store.list_all_sessions()
        sessions[0].title = "Mutated"
        fresh = store.list_all_sessions()
        assert fresh[0].title == "Test"


class TestReopenSession:
    def test_reopen_completed_session(self, store):
        session = store.create_session(title="Test")
        store.end_session(session.id)
        store.reopen_session(session.id)
        updated = store.get_session(session.id)
        assert updated.status == SessionStatus.ACTIVE

    def test_reopen_active_session_raises(self, store):
        session = store.create_session(title="Test")
        with pytest.raises(ValueError, match="not complete"):
            store.reopen_session(session.id)

    def test_reopen_nonexistent_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.reopen_session("no-such-id")

    def test_reopen_persists_to_git(self, store):
        session = store.create_session(title="Test")
        store.end_session(session.id)
        store.reopen_session(session.id)
        content = store._git.read_file(f"sessions/{session.id}/session.json")
        assert '"active"' in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/joinora/test_session_store.py::TestListAllSessions tests/joinora/test_session_store.py::TestReopenSession -v`

Expected: FAIL — methods not defined.

- [ ] **Step 3: Implement SessionStore methods**

Add to `joinora/session_store.py`, after `get_session`:

```python
    def list_all_sessions(self) -> list[Session]:
        with self._lock:
            return [s.model_copy(deep=True) for s in self._sessions.values()]
```

Add after `end_session`:

```python
    def reopen_session(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError(f"Session '{session_id}' not found")
            if session.status != SessionStatus.COMPLETE:
                raise ValueError(f"Session '{session_id}' is not complete")
            session.status = SessionStatus.ACTIVE
        self._save_session(session, f"reopen: session {session_id}")
```

- [ ] **Step 4: Run SessionStore tests**

Run: `python3 -m pytest tests/joinora/test_session_store.py -v 2>&1 | tail -20`

Expected: all pass.

- [ ] **Step 5: Write failing tests for tool functions**

Add to `tests/joinora/test_tools.py`:

```python
from joinora.tools import list_sessions, reopen_session


class TestListSessionsTool:
    @pytest.mark.asyncio
    async def test_returns_sessions_with_urls(self, store):
        session = store.create_session(title="Test")
        store.add_participant(session.id, "alice")
        result = await list_sessions(
            store=store, host="localhost", port=24298
        )
        assert len(result["sessions"]) == 1
        entry = result["sessions"][0]
        assert entry["session_id"] == session.id
        assert "localhost:24298" in entry["session_url"]
        assert entry["title"] == "Test"
        assert len(entry["participants"]) == 1
        assert "token=" in entry["participants"][0]["url"]

    @pytest.mark.asyncio
    async def test_empty_when_no_sessions(self, store):
        result = await list_sessions(
            store=store, host="localhost", port=24298
        )
        assert result["sessions"] == []


class TestReopenSessionTool:
    @pytest.mark.asyncio
    async def test_reopens_completed_session(self, store):
        session = store.create_session(title="Test")
        store.end_session(session.id)
        result = await reopen_session(store=store, session_id=session.id)
        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_reopen_nonexistent_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            await reopen_session(store=store, session_id="no-such-id")
```

- [ ] **Step 6: Implement tool functions**

Add to `joinora/tools.py`:

```python
async def list_sessions(
    store: SessionStore,
    host: str,
    port: int,
) -> dict:
    sessions = store.list_all_sessions()
    result = []
    for session in sessions:
        tokens = store.get_participant_tokens(session.id)
        base_url = f"http://{host}:{port}/session/{session.id}"
        result.append(
            {
                "session_id": session.id,
                "session_url": base_url,
                "title": session.title,
                "status": session.status.value,
                "message_count": len(session.messages),
                "participants": [
                    {
                        "name": p.name,
                        "url": f"{base_url}?token={tokens.get(p.name, '')}",
                        "last_seen": (
                            p.last_seen.isoformat() if p.last_seen else None
                        ),
                    }
                    for p in session.participants
                ],
            }
        )
    return {"sessions": result}


async def reopen_session(store: SessionStore, session_id: str) -> dict:
    store.reopen_session(session_id)
    session = store.get_session(session_id)
    return {
        "status": session.status.value,
        "title": session.title,
        "message_count": len(session.messages),
        "participants": [p.name for p in session.participants],
    }
```

- [ ] **Step 7: Add MCP wrappers in server.py**

Add after the `end_session` MCP tool in `joinora/server.py`:

```python
    @mcp.tool()
    async def list_sessions() -> dict:
        """List all sessions (active and complete) with participant URLs.
        Use to discover existing sessions after agent reconnection."""
        from joinora.tools import list_sessions as _list

        return await _list(store=store, host=web_host, port=web_port)

    @mcp.tool()
    async def reopen_session(session_id: str) -> dict:
        """Reopen a completed session, changing its status back to active."""
        from joinora.tools import reopen_session as _reopen

        return await _reopen(store=store, session_id=session_id)
```

- [ ] **Step 8: Run full test suite**

Run: `python3 -m pytest tests/ -v 2>&1 | tail -30`

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add joinora/session_store.py joinora/tools.py joinora/server.py tests/
git commit -m "feat: add list_sessions and reopen_session tools"
```

---

### Task 5: Update get_session_status + watch_session in server.py

**Files:**
- Modify: `joinora/tools.py`
- Modify: `joinora/server.py:70-78`
- Test: `tests/joinora/test_tools.py`

`get_session_status` gains URLs with participant tokens. `watch_session` returns
`{ events: [...] }` instead of `{ messages: [...] }`.

- [ ] **Step 1: Write failing tests for updated get_session_status**

Update `TestGetSessionStatusTool` in `tests/joinora/test_tools.py`:

```python
class TestGetSessionStatusTool:
    @pytest.mark.asyncio
    async def test_returns_status_with_urls(self, store):
        session = store.create_session(title="Test")
        token = store.add_participant(session.id, "alice")
        store.add_message(session.id, "alice", "Hi")
        result = await get_session_status(
            store=store,
            session_id=session.id,
            host="localhost",
            port=24298,
        )
        assert result["status"] == "active"
        assert result["message_count"] == 1
        assert "session_url" in result
        assert "localhost:24298" in result["session_url"]
        assert len(result["participants"]) == 1
        assert f"token={token}" in result["participants"][0]["url"]

    @pytest.mark.asyncio
    async def test_nonexistent_session_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            await get_session_status(
                store=store,
                session_id="no-such-id",
                host="localhost",
                port=24298,
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/joinora/test_tools.py::TestGetSessionStatusTool -v`

Expected: FAIL — `get_session_status()` doesn't accept host/port.

- [ ] **Step 3: Update get_session_status in tools.py**

Replace `get_session_status` in `joinora/tools.py`:

```python
async def get_session_status(
    store: SessionStore,
    session_id: str,
    host: str = "localhost",
    port: int = 24298,
) -> dict:
    session = store.get_session(session_id)
    if session is None:
        raise ValueError(f"Session '{session_id}' not found")
    tokens = store.get_participant_tokens(session_id)
    base_url = f"http://{host}:{port}/session/{session.id}"
    return {
        "session_id": session.id,
        "session_url": base_url,
        "status": session.status.value,
        "title": session.title,
        "message_count": len(session.messages),
        "participants": [
            {
                "name": p.name,
                "url": f"{base_url}?token={tokens.get(p.name, '')}",
                "last_seen": (
                    p.last_seen.isoformat() if p.last_seen else None
                ),
            }
            for p in session.participants
        ],
    }
```

- [ ] **Step 4: Update get_session_status MCP wrapper in server.py**

Replace in `joinora/server.py`:

```python
    @mcp.tool()
    async def get_session_status(session_id: str) -> dict:
        """Check session state: who's connected, last activity, message count."""
        from joinora.tools import get_session_status as _status

        return await _status(
            store=store,
            session_id=session_id,
            host=web_host,
            port=web_port,
        )
```

- [ ] **Step 5: Update watch_session MCP tool in server.py**

Replace the `watch_session` MCP tool in `joinora/server.py`:

```python
    @mcp.tool(task=True)
    async def watch_session(session_id: str) -> dict:
        """Start monitoring a session for participant activity.
        Returns events (messages and joins) when participants interact.
        Runs as a background MCP Task."""
        events = await store.wait_for_activity(session_id, timeout=300.0)
        wire_events = []
        for evt in events:
            if evt["type"] == "message":
                wire_events.append(
                    {"type": "message", "message": evt["message"].to_wire()}
                )
            else:
                wire_events.append(evt)
        return {"events": wire_events}
```

- [ ] **Step 6: Run full test suite**

Run: `python3 -m pytest tests/ -v 2>&1 | tail -30`

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add joinora/tools.py joinora/server.py tests/joinora/test_tools.py
git commit -m "feat: add URLs to get_session_status, event format to watch_session"
```

---

### Task 6: Web join endpoint

**Files:**
- Modify: `joinora/web.py`
- Test: `tests/joinora/test_web.py`

Adds `POST /api/sessions/{session_id}/join` for self-service participant join.

- [ ] **Step 1: Write failing tests**

Add to `tests/joinora/test_web.py`:

```python
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

    def test_join_reserved_name_returns_400(self, client, store):
        session = store.create_session(title="Test")
        resp = client.post(
            f"/api/sessions/{session.id}/join",
            json={"name": "ai"},
        )
        assert resp.status_code == 400

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/joinora/test_web.py::TestJoinAPI -v`

Expected: FAIL — 404 because the endpoint doesn't exist.

- [ ] **Step 3: Implement the join endpoint**

Add a request model and endpoint to `joinora/web.py`.

Add after the `PostMessageRequest` class:

```python
class JoinRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50, pattern=r"^[\w\- ]+$")
```

Add the endpoint inside `create_web_app`, after the `post_message` endpoint:

```python
    @app.post("/api/sessions/{session_id}/join", status_code=201)
    async def join_session(session_id: str, req: JoinRequest):
        session = store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if session.status.value == "complete":
            raise HTTPException(status_code=410, detail="Session has ended")
        try:
            token = store.add_participant(session_id, req.name)
        except ValueError as e:
            msg = str(e)
            if "already taken" in msg:
                raise HTTPException(status_code=409, detail=msg)
            raise HTTPException(status_code=400, detail=msg)
        await ws_manager.broadcast(
            session_id,
            {"type": "participant_joined", "user": req.name},
        )
        return {"name": req.name, "token": token}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/joinora/test_web.py -v 2>&1 | tail -30`

Expected: all pass.

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest tests/ -v 2>&1 | tail -10`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add joinora/web.py tests/joinora/test_web.py
git commit -m "feat: add POST /api/sessions/{id}/join endpoint"
```

---

### Task 7: Frontend — localStorage + join overlay

**Files:**
- Modify: `joinora/frontend/index.html`
- Modify: `joinora/frontend/style.css`
- Modify: `joinora/frontend/app.js`

Switch from `sessionStorage` to `localStorage`. Add a join overlay when no token
is present. Remove read-only observer mode.

- [ ] **Step 1: Add join overlay HTML**

Add the join overlay `div` to `joinora/frontend/index.html`, right after the
opening `<div id="app">` and before `<header>`:

```html
        <div id="join-overlay" class="hidden">
            <div class="join-card">
                <h2 id="join-title"></h2>
                <p id="join-ended" class="hidden">This session has ended.</p>
                <form id="join-form">
                    <input type="text" id="join-name" placeholder="Your name" maxlength="50" required autocomplete="off">
                    <div id="join-error" class="hidden"></div>
                    <button type="submit" id="join-btn">Join</button>
                </form>
            </div>
        </div>
```

- [ ] **Step 2: Add join overlay CSS**

Append to `joinora/frontend/style.css`:

```css
/* Join overlay */
#join-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.7);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
}

#join-overlay.hidden { display: none; }

.join-card {
    background: #2a2a4a;
    border-radius: 12px;
    padding: 32px;
    max-width: 400px;
    width: 90%;
    text-align: center;
}

.join-card h2 {
    color: #fff;
    margin-bottom: 20px;
    font-size: 1.3rem;
}

#join-form {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

#join-name {
    padding: 10px;
    background: #1a1a2e;
    border: 1px solid #444;
    border-radius: 8px;
    color: #e0e0e0;
    font-size: 1rem;
    text-align: center;
}

#join-btn {
    padding: 10px;
    background: #4a6cf7;
    color: #fff;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    font-size: 1rem;
}

#join-btn:hover { background: #3a5ce7; }

#join-error {
    color: #ff6b6b;
    font-size: 0.85rem;
}

#join-error.hidden { display: none; }

#join-ended {
    color: #aaa;
    font-size: 0.95rem;
}

#join-ended.hidden { display: none; }
```

- [ ] **Step 3: Rewrite app.js with localStorage + join flow**

Replace `joinora/frontend/app.js` entirely. Key changes from the existing file:

1. `sessionStorage` → `localStorage` (2 occurrences: setItem, getItem)
2. New DOM references for join overlay elements
3. `init()` now branches: if no `current_user` in response, show join overlay instead of read-only mode
4. New `showJoinOverlay()` function and `joinForm` submit handler
5. Remove the old `!token` block that set read-only mode

```javascript
(function () {
    function esc(str) {
        var d = document.createElement("div");
        d.textContent = str;
        return d.innerHTML;
    }

    if (typeof marked !== "undefined") {
        marked.use({
            renderer: {
                html: function (token) { return esc(token.text); },
                link: function (ref) {
                    var href = ref.href, title = ref.title, tokens = ref.tokens;
                    if (href && /^(javascript|data|vbscript):/i.test(href.replace(/\s/g, ""))) {
                        return esc(tokens.map(function (t) { return t.raw; }).join(""));
                    }
                    var titleAttr = title ? ' title="' + esc(title) + '"' : "";
                    return '<a href="' + esc(href) + '"' + titleAttr + ' rel="noopener noreferrer">' + marked.Parser.parseInline(tokens) + "</a>";
                },
            },
        });
    }

    function renderMarkdown(text) {
        if (typeof marked !== "undefined") {
            return marked.parse(text);
        }
        return esc(text);
    }

    var params = new URLSearchParams(window.location.search);
    var sessionId = window.location.pathname.split("/session/")[1];

    if (!sessionId) return;

    var token = params.get("token");
    if (token) {
        localStorage.setItem("dc-token-" + sessionId, token);
        history.replaceState(null, "", window.location.pathname);
    } else {
        token = localStorage.getItem("dc-token-" + sessionId);
    }

    var ALLOWED_TYPES = { question: 1, proposal: 1, summary: 1, info: 1, ai: 1, human: 1 };
    var AGENT_STATES = { agent_listening: "listening", agent_processing: "processing", agent_disconnected: "disconnected" };

    var messagesEl = document.getElementById("messages");
    var inputEl = document.getElementById("comment-input");
    var sendBtn = document.getElementById("send-btn");
    var titleEl = document.getElementById("session-title");
    var participantsEl = document.getElementById("participants");
    var catchupBanner = document.getElementById("catchup-banner");
    var catchupText = document.getElementById("catchup-text");
    var catchupYes = document.getElementById("catchup-yes");
    var catchupDismiss = document.getElementById("catchup-dismiss");
    var agentDot = document.getElementById("agent-dot");

    var joinOverlay = document.getElementById("join-overlay");
    var joinTitle = document.getElementById("join-title");
    var joinForm = document.getElementById("join-form");
    var joinNameInput = document.getElementById("join-name");
    var joinError = document.getElementById("join-error");
    var joinEnded = document.getElementById("join-ended");

    var ws = null;
    var currentUser = null;

    async function init() {
        var resp = await fetch(
            "/api/sessions/" + sessionId + (token ? "?token=" + token : "")
        );
        if (!resp.ok) {
            messagesEl.textContent = "Session not found.";
            return;
        }
        var session = await resp.json();
        currentUser = session.current_user || null;
        titleEl.textContent = session.title;

        if (!currentUser) {
            showJoinOverlay(session);
            return;
        }

        renderParticipants(session.participants);

        var msgResp = await fetch("/api/sessions/" + sessionId + "/messages" + (token ? "?token=" + token : ""));
        var messages = await msgResp.json();
        messages.forEach(renderMessage);
        scrollToBottom();

        if (session.last_seen && messages.length > 0) {
            var lastSeen = new Date(session.last_seen);
            var newCount = messages.filter(
                function (m) { return new Date(m.timestamp) > lastSeen; }
            ).length;
            if (newCount > 0) {
                catchupText.textContent =
                    newCount + " new message" + (newCount > 1 ? "s" : "") +
                    " since you were last here. Want a summary?";
                catchupBanner.classList.remove("hidden");
            }
        }

        inputEl.disabled = false;
        sendBtn.disabled = false;
        inputEl.placeholder = "Type your message...";
        connectWebSocket();
    }

    function showJoinOverlay(session) {
        joinTitle.textContent = session.title;
        if (session.status === "complete") {
            joinForm.classList.add("hidden");
            joinEnded.classList.remove("hidden");
        }
        joinOverlay.classList.remove("hidden");
        inputEl.disabled = true;
        sendBtn.disabled = true;
    }

    joinForm.addEventListener("submit", async function (e) {
        e.preventDefault();
        var name = joinNameInput.value.trim();
        if (!name) return;

        joinError.classList.add("hidden");
        var resp = await fetch("/api/sessions/" + sessionId + "/join", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name }),
        });

        if (!resp.ok) {
            var err = await resp.json();
            joinError.textContent = err.detail || "Join failed";
            joinError.classList.remove("hidden");
            return;
        }

        var data = await resp.json();
        token = data.token;
        localStorage.setItem("dc-token-" + sessionId, token);
        joinOverlay.classList.add("hidden");
        init();
    });

    function badgeClass(name, extra) {
        var cls = "participant-badge";
        if (extra) cls += " " + extra;
        if (name === currentUser) cls += " current-user";
        return cls;
    }

    function renderParticipants(participants) {
        participantsEl.textContent = "";
        participants.forEach(function (p) {
            var badge = document.createElement("span");
            badge.className = badgeClass(p.name);
            badge.textContent = p.name;
            participantsEl.appendChild(badge);
        });
    }

    function renderMessage(msg) {
        var div = document.createElement("div");
        var meta = msg.metadata || {};
        var isAI = msg.author === "ai";
        var rawType = meta.type || (isAI ? "ai" : "human");
        var typeClass = ALLOWED_TYPES[rawType] ? rawType : (isAI ? "ai" : "human");
        div.className = "message " + typeClass;

        var authorEl = document.createElement("div");
        authorEl.className = "author";
        authorEl.textContent = msg.author;
        if (meta.section) {
            var tag = document.createElement("span");
            tag.className = "section-tag";
            tag.textContent = meta.section;
            authorEl.appendChild(tag);
        }
        div.appendChild(authorEl);

        var textEl = document.createElement("div");
        textEl.className = "text";
        textEl.innerHTML = renderMarkdown(msg.text);
        div.appendChild(textEl);

        var timeEl = document.createElement("div");
        timeEl.className = "timestamp";
        timeEl.textContent = formatTime(msg.timestamp);
        div.appendChild(timeEl);

        messagesEl.appendChild(div);
    }

    function scrollToBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function isNearBottom() {
        var threshold = 100;
        return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < threshold;
    }

    function setAgentState(state) {
        agentDot.className = "agent-dot " + state;
        if (state === "processing") {
            showTypingIndicator();
        } else {
            removeTypingIndicator();
        }
    }

    function showTypingIndicator() {
        if (document.getElementById("agent-typing")) return;
        var el = document.createElement("div");
        el.id = "agent-typing";
        var bar = document.createElement("div");
        bar.className = "bar";
        el.appendChild(bar);
        var label = document.createElement("span");
        label.textContent = "thinking…";
        el.appendChild(label);
        messagesEl.appendChild(el);
        if (isNearBottom()) scrollToBottom();
    }

    function removeTypingIndicator() {
        var el = document.getElementById("agent-typing");
        if (el) el.remove();
    }

    function formatTime(ts) {
        return new Date(ts).toLocaleTimeString();
    }

    function connectWebSocket() {
        var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        var url = proto + "//" + window.location.host +
            "/ws/sessions/" + sessionId + "?token=" + (token || "");
        ws = new WebSocket(url);

        ws.onmessage = function (event) {
            var data = JSON.parse(event.data);
            if (data.type === "message_added") {
                removeTypingIndicator();
                renderMessage(data.message);
                scrollToBottom();
            } else if (data.type === "participant_joined") {
                var existing = Array.from(participantsEl.children).some(
                    function (el) { return el.textContent === data.user; }
                );
                if (!existing) {
                    var badge = document.createElement("span");
                    badge.className = badgeClass(data.user, "online");
                    badge.textContent = data.user;
                    participantsEl.appendChild(badge);
                }
            } else if (AGENT_STATES[data.type]) {
                setAgentState(AGENT_STATES[data.type]);
            }
        };

        ws.onclose = function () {
            setTimeout(connectWebSocket, 3000);
        };
    }

    async function sendMessage() {
        var text = inputEl.value.trim();
        if (!text || !token) return;

        var resp = await fetch(
            "/api/sessions/" + sessionId + "/messages?token=" + token,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    text: text,
                }),
            }
        );

        if (resp.ok) {
            inputEl.value = "";
        }
    }

    sendBtn.addEventListener("click", sendMessage);
    inputEl.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    catchupYes.addEventListener("click", async function () {
        catchupBanner.classList.add("hidden");
        await fetch(
            "/api/sessions/" + sessionId + "/messages?token=" + token,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    text: "/catchup",
                }),
            }
        );
    });

    catchupDismiss.addEventListener("click", function () {
        catchupBanner.classList.add("hidden");
    });

    init();
})();
```

- [ ] **Step 4: Manual test in browser**

Run: `python3 test_local.py` (or start the server manually)

1. Open the session URL in a browser — should see join overlay
2. Enter a name, click Join — overlay disappears, thread loads
3. Open a second tab with the same URL — should auto-join (localStorage)
4. Open a different session URL — should show join overlay independently
5. Post a message — should appear in the thread

- [ ] **Step 5: Commit**

```bash
git add joinora/frontend/
git commit -m "feat: add join overlay, switch to localStorage"
```

---

### Task 8: Skill file updates

**Files:**
- Modify: `skill/skills/joinora/SKILL.md`
- Modify: `skill/joinora.md`

Update the adapter skill to reflect the new `create_session` (no participant names),
event-based `watch_session`, and new tools.

- [ ] **Step 1: Update SKILL.md**

Replace the Setup section in `skill/skills/joinora/SKILL.md`:

```markdown
## Setup

1. Call the Joinora MCP tool `create_session` with a descriptive
   title based on the target skill.
2. Present the session URL to the coordinator:
   > "Share this link with participants: **{session_url}**"
   > Anyone with the link can join by picking a name.
3. Use `watch_session` to wait for participants to join and begin.
```

Add a section for new tools after the Monitoring section:

```markdown
**Session management:**

- Use `list_sessions` to discover existing sessions after
  reconnection. Returns all sessions with participant URLs.
- Use `reopen_session` to reactivate a completed session.
```

Update the Monitoring section to reflect event-based watch:

```markdown
**Monitoring:**

- `watch_session` returns events — both `"message"` and
  `"participant_joined"` types. Process all events in order.
- Use `get_session_status` to check who's active. Returns
  participant URLs with tokens for re-sharing.
```

- [ ] **Step 2: Update joinora.md (root-level copy)**

Apply the same changes to `skill/joinora.md` — it has identical content.

- [ ] **Step 3: Commit**

```bash
git add skill/
git commit -m "docs: update skill files for self-service join flow"
```

- [ ] **Step 4: Run final full test suite**

Run: `python3 -m pytest tests/ -v`

Expected: all pass. The implementation is complete.
