# Collaborative Skill Runtime — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Conducere as an MCP server with embedded web UI that lets any coding agent run structured skills collaboratively with multiple browser-based participants.

**Architecture:** A FastMCP server exposes 6 tools (create_session, post_message, watch_session, get_session_status, get_catchup_summary, end_session). A FastAPI web UI server runs in a daemon thread sharing the same in-memory session store. Participants interact via WebSocket-connected browser. The agent uses MCP Tasks (watch_session) for async event delivery. A `/draftcircle` Claude Code skill wraps any target skill for collaborative execution.

**Tech Stack:** Python 3.12+, FastMCP (MCP server + tasks), FastAPI (web UI + WebSocket), pygit2 (git persistence), vanilla HTML/CSS/JS (browser UI).

**Spec:** `docs/specs/2026-05-11-draftcircle-collaborative-skill-runtime-design.md`

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `mcp_server/models.py` | Pydantic models: Session, Message, Participant (flat, skill-agnostic) |
| `mcp_server/session_store.py` | Session store backed by GitStore (pygit2). In-memory cache for fast reads, git commits for every mutation, asyncio events for subscriber notification |
| `mcp_server/tools.py` | FastMCP tool definitions: create_session, post_message, watch_session, get_session_status, get_catchup_summary, end_session |
| `mcp_server/server.py` | FastMCP server setup, daemon thread for web UI, CLI entry point |
| `mcp_server/web.py` | FastAPI app for web UI: static files, REST API for messages, WebSocket for real-time sync |
| `mcp_server/ws_manager.py` | WebSocket connection manager (reused pattern from existing backend) |
| `mcp_server/__init__.py` | Package init |
| `mcp_server/frontend/index.html` | Conversation thread UI |
| `mcp_server/frontend/style.css` | Styling for message types, participant list, catch-up banner |
| `mcp_server/frontend/app.js` | WebSocket client, message rendering, comment input, catch-up prompt |
| `tests/mcp_server/__init__.py` | Test package init |
| `tests/mcp_server/test_models.py` | Model validation tests |
| `tests/mcp_server/test_session_store.py` | Session store CRUD + subscriber notification tests |
| `tests/mcp_server/test_tools.py` | MCP tool integration tests |
| `tests/mcp_server/test_web.py` | Web UI REST API + WebSocket tests |
| `tests/mcp_server/test_integration.py` | End-to-end integration tests |
| `skill/draftcircle.md` | `/draftcircle` adapter skill for Claude Code |

### Existing files to modify

| File | Change |
|------|--------|
| `pyproject.toml` | Add `fastmcp[tasks]` dependency, add `mcp_server` package, add CLI entry point |

### Not modified (kept for backwards compatibility)

The existing `backend/` and `frontend/` directories are untouched. The new `mcp_server/` package is independent. The current Conducere template-driven mode continues to work.

---

### Task 1: Project setup and models

**Files:**
- Modify: `pyproject.toml`
- Create: `mcp_server/__init__.py`
- Create: `mcp_server/models.py`
- Create: `tests/mcp_server/__init__.py`
- Create: `tests/mcp_server/test_models.py`

- [ ] **Step 1: Write model tests**

Create `tests/mcp_server/__init__.py` (empty) and `tests/mcp_server/test_models.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from mcp_server.models import Message, Participant, Session, SessionStatus


class TestParticipant:
    def test_create_participant(self):
        p = Participant(name="alice", token="abc123")
        assert p.name == "alice"
        assert p.token == "abc123"
        assert p.last_seen is None

    def test_name_required(self):
        with pytest.raises(ValidationError):
            Participant(name="", token="abc123")


class TestMessage:
    def test_create_plain_message(self):
        msg = Message(
            id="msg-001",
            author="alice",
            text="Hello",
            timestamp=datetime.now(timezone.utc),
        )
        assert msg.metadata is None

    def test_create_message_with_metadata(self):
        msg = Message(
            id="msg-002",
            author="ai",
            text="What is the feature?",
            timestamp=datetime.now(timezone.utc),
            metadata={"type": "question", "section": "overview"},
        )
        assert msg.metadata["type"] == "question"

    def test_author_required(self):
        with pytest.raises(ValidationError):
            Message(
                id="msg-003",
                author="",
                text="Hello",
                timestamp=datetime.now(timezone.utc),
            )


class TestSession:
    def test_create_session(self):
        s = Session(
            id="session-001",
            title="Define Feature X",
            created_at=datetime.now(timezone.utc),
        )
        assert s.status == SessionStatus.ACTIVE
        assert s.participants == []
        assert s.messages == []

    def test_default_status_is_active(self):
        s = Session(
            id="s1",
            title="Test",
            created_at=datetime.now(timezone.utc),
        )
        assert s.status == SessionStatus.ACTIVE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/mcp_server/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_server'`

- [ ] **Step 3: Create package init and models**

Create `mcp_server/__init__.py` (empty).

Create `mcp_server/models.py`:

```python
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETE = "complete"


class Participant(BaseModel):
    name: str = Field(min_length=1)
    token: str
    last_seen: datetime | None = None


class Message(BaseModel):
    id: str
    author: str = Field(min_length=1)
    text: str = Field(min_length=1)
    timestamp: datetime
    metadata: dict[str, str] | None = None


class Session(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    status: SessionStatus = SessionStatus.ACTIVE
    participants: list[Participant] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    created_at: datetime
```

- [ ] **Step 4: Update pyproject.toml**

Add `fastmcp[tasks]` to dependencies, add `mcp_server` to packages:

In `pyproject.toml`, add to `dependencies`:
```
    "fastmcp[tasks]>=3.0",
```

In `[tool.setuptools]`, change to:
```
packages = ["backend", "backend.plugins", "mcp_server"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/mcp_server/test_models.py -v`
Expected: All 6 tests PASS

- [ ] **Step 6: Install updated dependencies**

Run: `pip install -e ".[dev]"`

- [ ] **Step 7: Commit**

```bash
git add mcp_server/ tests/mcp_server/ pyproject.toml
git commit -m "feat(mcp): add flat session models for skill runtime"
```

---

### Task 2: Session store with git persistence and subscriber notification

**Files:**
- Create: `mcp_server/session_store.py`
- Create: `tests/mcp_server/test_session_store.py`

The session store uses the existing `backend.git_store.GitStore` for persistence. Every mutation (create session, add message, end session, update last_seen) is a git commit. An in-memory cache provides fast reads and `asyncio.Event` objects notify the `watch_session` MCP Task when new messages arrive.

- [ ] **Step 1: Write session store tests**

Create `tests/mcp_server/test_session_store.py`:

```python
import asyncio
from datetime import datetime, timezone

import pytest

from mcp_server.models import SessionStatus
from mcp_server.session_store import SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(repo_path=tmp_path)


class TestCreateSession:
    def test_create_returns_session_with_id(self, store):
        session = store.create_session(title="Test Session")
        assert session.id
        assert session.status == SessionStatus.ACTIVE

    def test_create_with_participants(self, store):
        session = store.create_session(
            title="Team Session",
            participant_names=["alice", "bob"],
        )
        assert len(session.participants) == 2
        assert session.participants[0].name == "alice"
        assert session.participants[0].token  # auto-generated

    def test_create_generates_unique_ids(self, store):
        s1 = store.create_session(title="A")
        s2 = store.create_session(title="B")
        assert s1.id != s2.id

    def test_create_persists_to_git(self, store):
        session = store.create_session(title="Persisted")
        content = store._git.read_file(f"sessions/{session.id}/session.json")
        assert content is not None
        assert "Persisted" in content


class TestGetSession:
    def test_get_existing_session(self, store):
        created = store.create_session(title="Test")
        fetched = store.get_session(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_nonexistent_returns_none(self, store):
        assert store.get_session("no-such-id") is None


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
        msg2 = store.add_message(session.id, "bob", "Second")
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


class TestSubscriberNotification:
    @pytest.mark.asyncio
    async def test_wait_for_activity_returns_on_message(self, store):
        session = store.create_session(title="Test")

        async def post_after_delay():
            await asyncio.sleep(0.1)
            store.add_message(session.id, "alice", "Hello")

        asyncio.create_task(post_after_delay())
        messages = await store.wait_for_activity(session.id, timeout=2.0)
        assert len(messages) >= 1
        assert messages[0].author == "alice"

    @pytest.mark.asyncio
    async def test_wait_for_activity_timeout_returns_empty(self, store):
        session = store.create_session(title="Test")
        messages = await store.wait_for_activity(session.id, timeout=0.1)
        assert messages == []

    @pytest.mark.asyncio
    async def test_wait_returns_batched_messages(self, store):
        session = store.create_session(title="Test")

        async def post_two():
            await asyncio.sleep(0.05)
            store.add_message(session.id, "alice", "First")
            store.add_message(session.id, "bob", "Second")

        asyncio.create_task(post_two())
        messages = await store.wait_for_activity(session.id, timeout=2.0)
        assert len(messages) >= 2


class TestUpdateLastSeen:
    def test_update_last_seen(self, store):
        session = store.create_session(
            title="Test", participant_names=["alice"]
        )
        now = datetime.now(timezone.utc)
        store.update_last_seen(session.id, "alice", now)
        updated = store.get_session(session.id)
        assert updated.participants[0].last_seen == now
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/mcp_server/test_session_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_server.session_store'`

- [ ] **Step 3: Implement session store**

Create `mcp_server/session_store.py`:

```python
import asyncio
import json
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from backend.git_store import GitStore
from mcp_server.models import Message, Participant, Session, SessionStatus


class SessionStore:
    def __init__(self, repo_path: Path):
        self._git = GitStore(repo_path)
        self._sessions: dict[str, Session] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._pending: dict[str, list[Message]] = {}
        self._lock = threading.Lock()

    def _session_dir(self, session_id: str) -> str:
        return f"sessions/{session_id}"

    def _save_session(self, session: Session, message: str) -> str:
        path = f"{self._session_dir(session.id)}/session.json"
        return self._git.commit(
            message, {path: session.model_dump_json(indent=2)}
        )

    def _save_messages(
        self, session: Session, commit_message: str
    ) -> str:
        base = self._session_dir(session.id)
        return self._git.commit(
            commit_message,
            {
                f"{base}/messages.json": json.dumps(
                    [m.model_dump(mode="json") for m in session.messages],
                    indent=2,
                ),
            },
        )

    def create_session(
        self,
        title: str,
        participant_names: list[str] | None = None,
    ) -> Session:
        session_id = secrets.token_urlsafe(12)
        participants = [
            Participant(name=name, token=secrets.token_urlsafe(16))
            for name in (participant_names or [])
        ]
        session = Session(
            id=session_id,
            title=title,
            participants=participants,
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
        return session

    def get_session(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def add_message(
        self,
        session_id: str,
        author: str,
        text: str,
        metadata: dict[str, str] | None = None,
    ) -> Message:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError(f"Session '{session_id}' not found")
            if session.status != SessionStatus.ACTIVE:
                raise ValueError(f"Session '{session_id}' is not active")

            msg_id = f"msg-{len(session.messages) + 1:03d}"
            message = Message(
                id=msg_id,
                author=author,
                text=text,
                timestamp=datetime.now(timezone.utc),
                metadata=metadata,
            )
            session.messages.append(message)
            self._pending.setdefault(session_id, []).append(message)

        self._save_messages(session, f"message: {author} in {session_id}")
        event = self._events.get(session_id)
        if event:
            event.set()
        return message

    def get_messages(
        self,
        session_id: str,
        since: datetime | None = None,
    ) -> list[Message]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError(f"Session '{session_id}' not found")
            if since is None:
                return list(session.messages)
            return [m for m in session.messages if m.timestamp > since]

    def end_session(self, session_id: str) -> dict:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError(f"Session '{session_id}' not found")
            session.status = SessionStatus.COMPLETE
        self._save_session(session, f"end: session {session_id}")
        return {
            "status": "complete",
            "message_count": len(session.messages),
            "participants": [p.name for p in session.participants],
        }

    def update_last_seen(
        self,
        session_id: str,
        participant_name: str,
        timestamp: datetime,
    ) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError(f"Session '{session_id}' not found")
            for p in session.participants:
                if p.name == participant_name:
                    p.last_seen = timestamp
                    break
        self._save_session(
            session,
            f"seen: {participant_name} in {session_id}",
        )

    async def wait_for_activity(
        self, session_id: str, timeout: float = 300.0
    ) -> list[Message]:
        event = asyncio.Event()
        self._events[session_id] = event
        with self._lock:
            self._pending[session_id] = []

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

        with self._lock:
            messages = self._pending.get(session_id, [])
            self._pending[session_id] = []
        self._events.pop(session_id, None)
        return messages
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/mcp_server/test_session_store.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add mcp_server/session_store.py tests/mcp_server/test_session_store.py
git commit -m "feat(mcp): session store with git persistence and subscriber notification"
```

---

### Task 3: MCP tools

**Files:**
- Create: `mcp_server/tools.py`
- Create: `tests/mcp_server/test_tools.py`

- [ ] **Step 1: Write MCP tool tests**

Create `tests/mcp_server/test_tools.py`:

```python
import pytest

from mcp_server.session_store import SessionStore
from mcp_server.tools import (
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

    @pytest.mark.asyncio
    async def test_creates_session_with_participants(self, store):
        result = await create_session(
            store=store,
            title="Team",
            participant_names=["alice", "bob"],
            host="localhost",
            port=24298,
        )
        session = store.get_session(result["session_id"])
        assert len(session.participants) == 2
        assert "participant_urls" in result
        assert len(result["participant_urls"]) == 2


class TestPostMessageTool:
    @pytest.mark.asyncio
    async def test_post_plain_message(self, store):
        session = store.create_session(title="Test")
        result = await post_message(
            store=store,
            session_id=session.id,
            text="Hello everyone",
        )
        assert "message_id" in result
        messages = store.get_messages(session.id)
        assert len(messages) == 1
        assert messages[0].author == "ai"

    @pytest.mark.asyncio
    async def test_post_message_with_metadata(self, store):
        session = store.create_session(title="Test")
        result = await post_message(
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
            await post_message(
                store=store,
                session_id="no-such-id",
                text="Hello",
            )


class TestGetSessionStatusTool:
    @pytest.mark.asyncio
    async def test_returns_status(self, store):
        session = store.create_session(
            title="Test", participant_names=["alice"]
        )
        store.add_message(session.id, "alice", "Hi")
        result = await get_session_status(store=store, session_id=session.id)
        assert result["status"] == "active"
        assert result["message_count"] == 1
        assert len(result["participants"]) == 1


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


class TestEndSessionTool:
    @pytest.mark.asyncio
    async def test_ends_session(self, store):
        session = store.create_session(title="Test")
        result = await end_session(store=store, session_id=session.id)
        assert result["status"] == "complete"
        updated = store.get_session(session.id)
        assert updated.status.value == "complete"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/mcp_server/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_server.tools'`

- [ ] **Step 3: Implement MCP tools**

Create `mcp_server/tools.py`:

```python
from datetime import datetime

from mcp_server.session_store import SessionStore


async def create_session(
    store: SessionStore,
    title: str,
    host: str,
    port: int,
    participant_names: list[str] | None = None,
) -> dict:
    session = store.create_session(
        title=title,
        participant_names=participant_names,
    )
    base_url = f"http://{host}:{port}/session/{session.id}"
    participant_urls = {
        p.name: f"{base_url}?token={p.token}" for p in session.participants
    }
    return {
        "session_id": session.id,
        "session_url": base_url,
        "participant_urls": participant_urls,
    }


async def post_message(
    store: SessionStore,
    session_id: str,
    text: str,
    metadata: dict[str, str] | None = None,
) -> dict:
    message = store.add_message(
        session_id=session_id,
        author="ai",
        text=text,
        metadata=metadata,
    )
    return {"message_id": message.id}


async def get_session_status(
    store: SessionStore,
    session_id: str,
) -> dict:
    session = store.get_session(session_id)
    if session is None:
        raise ValueError(f"Session '{session_id}' not found")
    return {
        "status": session.status.value,
        "title": session.title,
        "message_count": len(session.messages),
        "participants": [
            {
                "name": p.name,
                "last_seen": p.last_seen.isoformat() if p.last_seen else None,
            }
            for p in session.participants
        ],
    }


async def get_catchup_summary(
    store: SessionStore,
    session_id: str,
    since: str | None = None,
) -> dict:
    since_dt = None
    if since:
        since_dt = datetime.fromisoformat(since)
    messages = store.get_messages(session_id, since=since_dt)
    return {
        "message_count": len(messages),
        "messages": [
            {
                "id": m.id,
                "author": m.author,
                "text": m.text,
                "metadata": m.metadata,
                "timestamp": m.timestamp.isoformat(),
            }
            for m in messages
        ],
    }


async def end_session(
    store: SessionStore,
    session_id: str,
) -> dict:
    return store.end_session(session_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/mcp_server/test_tools.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add mcp_server/tools.py tests/mcp_server/test_tools.py
git commit -m "feat(mcp): implement MCP tool functions"
```

---

### Task 4: FastMCP server with watch_session task

**Files:**
- Create: `mcp_server/server.py`
- Modify: `pyproject.toml` (add entry point)

- [ ] **Step 1: Write server integration test**

Add to `tests/mcp_server/test_tools.py`:

```python
from mcp_server.server import create_mcp_server


class TestMCPServerCreation:
    def test_server_creates_with_tools(self, tmp_path):
        server = create_mcp_server(repo_path=tmp_path)
        assert server is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/mcp_server/test_tools.py::TestMCPServerCreation -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_server.server'`

- [ ] **Step 3: Implement FastMCP server**

Create `mcp_server/server.py`:

```python
import argparse
import threading
from pathlib import Path

from fastmcp import FastMCP

from mcp_server.session_store import SessionStore


def create_mcp_server(
    repo_path: Path | None = None,
    web_host: str = "localhost",
    web_port: int = 24298,
) -> FastMCP:
    store = SessionStore(repo_path=repo_path)
    mcp = FastMCP(
        "Conducere",
        instructions=(
            "Conducere is a collaborative skill runtime. "
            "Use these tools to run interactive, multi-user sessions "
            "where participants contribute via a shared web UI."
        ),
    )

    @mcp.tool()
    async def create_session(
        title: str,
        participant_names: list[str] | None = None,
    ) -> dict:
        """Create a new collaborative session. Returns session_id and
        a session_url to share with participants."""
        from mcp_server.tools import create_session as _create

        return await _create(
            store=store,
            title=title,
            host=web_host,
            port=web_port,
            participant_names=participant_names,
        )

    @mcp.tool()
    async def post_message(
        session_id: str,
        text: str,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """Post an AI message visible to all participants in the session."""
        from mcp_server.tools import post_message as _post

        result = await _post(
            store=store,
            session_id=session_id,
            text=text,
            metadata=metadata,
        )
        web_app = getattr(mcp, "_web_app", None)
        if web_app:
            ws_mgr = web_app.state.ws_manager
            msg = store.get_messages(session_id)[-1]
            await ws_mgr.broadcast(
                session_id,
                {
                    "type": "message_added",
                    "message": msg.model_dump(mode="json"),
                },
            )
        return result

    @mcp.tool(task=True)
    async def watch_session(session_id: str) -> dict:
        """Start monitoring a session for participant activity.
        Returns new messages when participants comment.
        Runs as a background MCP Task."""
        messages = await store.wait_for_activity(
            session_id, timeout=300.0
        )
        return {
            "messages": [
                {
                    "id": m.id,
                    "author": m.author,
                    "text": m.text,
                    "metadata": m.metadata,
                    "timestamp": m.timestamp.isoformat(),
                }
                for m in messages
            ],
        }

    @mcp.tool()
    async def get_session_status(session_id: str) -> dict:
        """Check session state: who's connected, last activity,
        message count."""
        from mcp_server.tools import get_session_status as _status

        return await _status(store=store, session_id=session_id)

    @mcp.tool()
    async def get_catchup_summary(
        session_id: str, since: str | None = None
    ) -> dict:
        """Get messages since a timestamp for catch-up summary
        generation."""
        from mcp_server.tools import get_catchup_summary as _catchup

        return await _catchup(
            store=store, session_id=session_id, since=since
        )

    @mcp.tool()
    async def end_session(session_id: str) -> dict:
        """Mark a session as complete and return the conversation
        record."""
        from mcp_server.tools import end_session as _end

        return await _end(store=store, session_id=session_id)

    mcp._store = store
    mcp._web_host = web_host
    mcp._web_port = web_port

    return mcp


def main():
    parser = argparse.ArgumentParser(description="Conducere MCP Server")
    parser.add_argument(
        "--repo-path",
        type=Path,
        default=None,
        help="Git repository path for session persistence",
    )
    parser.add_argument(
        "--web-host",
        default="localhost",
        help="Host for the web UI server (default: localhost)",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=24298,
        help="Port for the web UI server (default: 24298)",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    args = parser.parse_args()

    server = create_mcp_server(
        repo_path=args.repo_path,
        web_host=args.web_host,
        web_port=args.web_port,
    )

    from mcp_server.web import create_web_app

    web_app = create_web_app(store=server._store)
    server._web_app = web_app

    def run_web():
        import uvicorn

        uvicorn.run(
            web_app, host=args.web_host, port=args.web_port, log_level="warning"
        )

    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()

    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Add CLI entry point to pyproject.toml**

In `pyproject.toml`, add after `[tool.setuptools]`:

```toml
[project.scripts]
draftcircle-mcp = "mcp_server.server:main"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/mcp_server/test_tools.py::TestMCPServerCreation -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add mcp_server/server.py pyproject.toml
git commit -m "feat(mcp): FastMCP server with watch_session task and CLI"
```

---

### Task 5: Web UI server (FastAPI + WebSocket)

**Files:**
- Create: `mcp_server/ws_manager.py`
- Create: `mcp_server/web.py`
- Create: `tests/mcp_server/test_web.py`

- [ ] **Step 1: Write web API tests**

Create `tests/mcp_server/test_web.py`:

```python
import pytest
from fastapi.testclient import TestClient

from mcp_server.session_store import SessionStore
from mcp_server.web import create_web_app


@pytest.fixture
def store(tmp_path):
    return SessionStore(repo_path=tmp_path)


@pytest.fixture
def client(store):
    app = create_web_app(store=store)
    return TestClient(app)


class TestSessionAPI:
    def test_get_nonexistent_session(self, client):
        resp = client.get("/api/sessions/no-such-id")
        assert resp.status_code == 404

    def test_get_existing_session(self, client, store):
        session = store.create_session(title="Test")
        resp = client.get(f"/api/sessions/{session.id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Test"


class TestMessageAPI:
    def test_post_message(self, client, store):
        session = store.create_session(
            title="Test", participant_names=["alice"]
        )
        token = session.participants[0].token
        resp = client.post(
            f"/api/sessions/{session.id}/messages",
            json={"author": "alice", "text": "Hello"},
            params={"token": token},
        )
        assert resp.status_code == 201
        assert resp.json()["author"] == "alice"

    def test_post_without_auth_rejected(self, client, store):
        session = store.create_session(title="Test")
        resp = client.post(
            f"/api/sessions/{session.id}/messages",
            json={"author": "alice", "text": "Hello"},
        )
        assert resp.status_code == 401

    def test_get_messages(self, client, store):
        session = store.create_session(
            title="Test", participant_names=["alice"]
        )
        token = session.participants[0].token
        client.post(
            f"/api/sessions/{session.id}/messages",
            json={"author": "alice", "text": "Hello"},
            params={"token": token},
        )
        resp = client.get(f"/api/sessions/{session.id}/messages")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestWebSocket:
    def test_websocket_receives_messages(self, client, store):
        session = store.create_session(
            title="Test", participant_names=["alice"]
        )
        token = session.participants[0].token
        with client.websocket_connect(
            f"/ws/sessions/{session.id}?token={token}"
        ) as ws:
            client.post(
                f"/api/sessions/{session.id}/messages",
                json={"author": "alice", "text": "Hello"},
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/mcp_server/test_web.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_server.web'`

- [ ] **Step 3: Create WebSocket manager**

Create `mcp_server/ws_manager.py`:

```python
from collections import defaultdict


class WebSocketManager:
    def __init__(self):
        self._connections: dict[str, list] = defaultdict(list)

    def connect(self, session_id: str, websocket) -> None:
        self._connections[session_id].append(websocket)

    def disconnect(self, session_id: str, websocket) -> None:
        conns = self._connections.get(session_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns and session_id in self._connections:
            del self._connections[session_id]

    async def broadcast(self, session_id: str, message: dict) -> None:
        for ws in list(self._connections.get(session_id, [])):
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(session_id, ws)

    def connection_count(self, session_id: str) -> int:
        return len(self._connections.get(session_id, []))
```

- [ ] **Step 4: Implement web app**

Create `mcp_server/web.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from mcp_server.session_store import SessionStore
from mcp_server.ws_manager import WebSocketManager


class PostMessageRequest(BaseModel):
    author: str = Field(min_length=1)
    text: str = Field(min_length=1)
    metadata: dict[str, str] | None = None


def create_web_app(store: SessionStore) -> FastAPI:
    app = FastAPI()
    ws_manager = WebSocketManager()
    app.state.ws_manager = ws_manager
    app.state.store = store

    def _authenticate(session_id: str, token: str | None) -> str | None:
        if not token:
            return None
        session = store.get_session(session_id)
        if session is None:
            return None
        for p in session.participants:
            if p.token == token:
                return p.name
        return None

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str, token: str | None = None):
        session = store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        data = session.model_dump(mode="json")
        if token:
            for p in session.participants:
                if p.token == token:
                    data["current_user"] = p.name
                    data["last_seen"] = (
                        p.last_seen.isoformat() if p.last_seen else None
                    )
                    break
        for p in data.get("participants", []):
            p.pop("token", None)
        data.pop("messages", None)
        return data

    @app.get("/api/sessions/{session_id}/messages")
    def get_messages(session_id: str, since: str | None = None):
        since_dt = None
        if since:
            since_dt = datetime.fromisoformat(since)
        try:
            return [
                m.model_dump(mode="json")
                for m in store.get_messages(session_id, since=since_dt)
            ]
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.post("/api/sessions/{session_id}/messages", status_code=201)
    async def post_message(
        session_id: str,
        req: PostMessageRequest,
        token: str | None = None,
    ):
        user = _authenticate(session_id, token)
        if user is None:
            raise HTTPException(
                status_code=401, detail="Authentication required"
            )

        try:
            message = store.add_message(
                session_id=session_id,
                author=req.author,
                text=req.text,
                metadata=req.metadata,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        await ws_manager.broadcast(
            session_id,
            {
                "type": "message_added",
                "message": message.model_dump(mode="json"),
            },
        )
        return message.model_dump(mode="json")

    @app.websocket("/ws/sessions/{session_id}")
    async def websocket_endpoint(websocket: WebSocket, session_id: str):
        token = websocket.query_params.get("token")
        user = _authenticate(session_id, token)
        if user is None:
            await websocket.close(
                code=4001, reason="Authentication required"
            )
            return

        await websocket.accept()
        ws_manager.connect(session_id, websocket)

        now = datetime.now(timezone.utc)
        store.update_last_seen(session_id, user, now)

        await ws_manager.broadcast(
            session_id,
            {"type": "participant_joined", "user": user},
        )

        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(session_id, websocket)
            store.update_last_seen(
                session_id, user, datetime.now(timezone.utc)
            )
            await ws_manager.broadcast(
                session_id,
                {"type": "participant_left", "user": user},
            )

    frontend_dir = Path(__file__).parent / "frontend"

    @app.get("/session/{session_id}")
    async def spa_route(session_id: str):
        index = frontend_dir / "index.html"
        if index.exists():
            return FileResponse(str(index))
        raise HTTPException(status_code=404, detail="Frontend not found")

    if frontend_dir.exists():
        app.mount(
            "/",
            StaticFiles(directory=str(frontend_dir), html=True),
            name="static",
        )

    return app
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/mcp_server/test_web.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add mcp_server/web.py mcp_server/ws_manager.py tests/mcp_server/test_web.py
git commit -m "feat(mcp): web UI server with REST API and WebSocket"
```

---

### Task 6: Frontend — conversation thread UI

**Files:**
- Create: `mcp_server/frontend/index.html`
- Create: `mcp_server/frontend/style.css`
- Create: `mcp_server/frontend/app.js`

- [ ] **Step 1: Create HTML shell**

Create `mcp_server/frontend/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Conducere</title>
    <link rel="stylesheet" href="/style.css">
</head>
<body>
    <div id="app">
        <header id="header">
            <h1 id="session-title">Conducere</h1>
            <div id="participants"></div>
        </header>
        <div id="catchup-banner" class="hidden">
            <span id="catchup-text"></span>
            <button id="catchup-yes">Show summary</button>
            <button id="catchup-dismiss">Dismiss</button>
        </div>
        <main id="messages"></main>
        <footer id="input-area">
            <textarea id="comment-input" placeholder="Type your message..." rows="2"></textarea>
            <button id="send-btn">Send</button>
        </footer>
    </div>
    <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create CSS**

Create `mcp_server/frontend/style.css`:

```css
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #1a1a2e;
    color: #e0e0e0;
    height: 100vh;
}

#app {
    display: flex;
    flex-direction: column;
    height: 100vh;
    max-width: 800px;
    margin: 0 auto;
}

header {
    padding: 16px;
    border-bottom: 1px solid #333;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

header h1 { font-size: 1.2rem; color: #fff; }

#participants {
    display: flex;
    gap: 8px;
    font-size: 0.8rem;
    color: #888;
}

.participant-badge {
    background: #2a2a4a;
    padding: 2px 8px;
    border-radius: 12px;
}

.participant-badge.online { color: #4caf50; }

#catchup-banner {
    padding: 12px 16px;
    background: #2a2a4a;
    border-bottom: 1px solid #333;
    display: flex;
    align-items: center;
    gap: 12px;
}

#catchup-banner.hidden { display: none; }
#catchup-banner button {
    padding: 4px 12px;
    border-radius: 4px;
    border: none;
    cursor: pointer;
    font-size: 0.85rem;
}
#catchup-yes { background: #4a6cf7; color: #fff; }
#catchup-dismiss { background: #444; color: #ccc; }

#messages {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.message {
    padding: 10px 14px;
    border-radius: 8px;
    max-width: 85%;
    line-height: 1.5;
}

.message.ai { background: #2a2a4a; align-self: flex-start; }
.message.human { background: #1e3a5f; align-self: flex-end; }
.message.question {
    background: #3a2a1a;
    border-left: 3px solid #f0a030;
    align-self: flex-start;
}
.message.proposal {
    background: #1a3a2a;
    border-left: 3px solid #4caf50;
    align-self: flex-start;
}
.message.summary {
    background: #2a1a3a;
    border-left: 3px solid #9c27b0;
    align-self: flex-start;
    font-style: italic;
}

.message .author {
    font-weight: 600;
    font-size: 0.8rem;
    margin-bottom: 4px;
    color: #aaa;
}

.message .section-tag {
    display: inline-block;
    background: #444;
    padding: 1px 6px;
    border-radius: 4px;
    font-size: 0.7rem;
    margin-left: 8px;
    color: #ccc;
}

.message .timestamp {
    font-size: 0.7rem;
    color: #666;
    margin-top: 4px;
}

#input-area {
    padding: 12px 16px;
    border-top: 1px solid #333;
    display: flex;
    gap: 8px;
}

#comment-input {
    flex: 1;
    background: #2a2a4a;
    color: #e0e0e0;
    border: 1px solid #444;
    border-radius: 8px;
    padding: 10px;
    font-family: inherit;
    font-size: 0.95rem;
    resize: none;
}

#send-btn {
    padding: 10px 20px;
    background: #4a6cf7;
    color: #fff;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    font-size: 0.95rem;
    align-self: flex-end;
}

#send-btn:hover { background: #3a5ce7; }
```

- [ ] **Step 3: Create JavaScript (XSS-safe DOM construction)**

Create `mcp_server/frontend/app.js`:

```javascript
(function () {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    const sessionId = window.location.pathname.split("/session/")[1];

    if (!sessionId) return;

    const messagesEl = document.getElementById("messages");
    const inputEl = document.getElementById("comment-input");
    const sendBtn = document.getElementById("send-btn");
    const titleEl = document.getElementById("session-title");
    const participantsEl = document.getElementById("participants");
    const catchupBanner = document.getElementById("catchup-banner");
    const catchupText = document.getElementById("catchup-text");
    const catchupYes = document.getElementById("catchup-yes");
    const catchupDismiss = document.getElementById("catchup-dismiss");

    let currentUser = null;
    let ws = null;

    async function init() {
        const resp = await fetch(
            "/api/sessions/" + sessionId + (token ? "?token=" + token : "")
        );
        if (!resp.ok) {
            messagesEl.textContent = "Session not found.";
            return;
        }
        const session = await resp.json();
        titleEl.textContent = session.title;
        currentUser = session.current_user || null;
        renderParticipants(session.participants);

        const msgResp = await fetch("/api/sessions/" + sessionId + "/messages");
        const messages = await msgResp.json();
        messages.forEach(renderMessage);
        scrollToBottom();

        if (session.last_seen && messages.length > 0) {
            const lastSeen = new Date(session.last_seen);
            const newCount = messages.filter(
                function (m) { return new Date(m.timestamp) > lastSeen; }
            ).length;
            if (newCount > 0) {
                catchupText.textContent =
                    newCount + " new message" + (newCount > 1 ? "s" : "") +
                    " since you were last here. Want a summary?";
                catchupBanner.classList.remove("hidden");
            }
        }

        connectWebSocket();

        if (!token) {
            inputEl.disabled = true;
            sendBtn.disabled = true;
            inputEl.placeholder = "Join with an invite link to participate";
        }
    }

    function renderParticipants(participants) {
        participantsEl.textContent = "";
        participants.forEach(function (p) {
            var badge = document.createElement("span");
            badge.className = "participant-badge";
            badge.textContent = p.name;
            participantsEl.appendChild(badge);
        });
    }

    function renderMessage(msg) {
        var div = document.createElement("div");
        var meta = msg.metadata || {};
        var isAI = msg.author === "ai";
        var typeClass = meta.type || (isAI ? "ai" : "human");
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
        textEl.textContent = msg.text;
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
                renderMessage(data.message);
                scrollToBottom();
            } else if (data.type === "participant_joined") {
                var badge = document.createElement("span");
                badge.className = "participant-badge online";
                badge.textContent = data.user;
                participantsEl.appendChild(badge);
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
                    author: currentUser || "anonymous",
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
                    author: currentUser || "anonymous",
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

- [ ] **Step 4: Manually test the web UI**

Start a Python REPL to create a test session:
```python
from mcp_server.session_store import SessionStore
from mcp_server.web import create_web_app
from pathlib import Path

store = SessionStore(repo_path=Path("/tmp/draftcircle-test"))
session = store.create_session(title="Test", participant_names=["alice"])
print(f"URL: http://localhost:24298/session/{session.id}?token={session.participants[0].token}")

import uvicorn
app = create_web_app(store=store)
uvicorn.run(app, host="localhost", port=24298)
```

Open the URL in a browser. Verify:
- Session title displays
- Message thread is empty
- Comment input is active
- Typing a message and pressing Enter posts it
- Messages render with correct styling

- [ ] **Step 5: Commit**

```bash
git add mcp_server/frontend/
git commit -m "feat(mcp): conversation thread web UI"
```

---

### Task 7: End-to-end integration test

**Files:**
- Create: `tests/mcp_server/test_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/mcp_server/test_integration.py`:

```python
import asyncio

import pytest
from fastapi.testclient import TestClient

from mcp_server.server import create_mcp_server
from mcp_server.web import create_web_app


@pytest.fixture
def setup(tmp_path):
    server = create_mcp_server(repo_path=tmp_path, web_port=24299)
    store = server._store
    web_app = create_web_app(store=store)
    server._web_app = web_app
    client = TestClient(web_app)
    return server, store, client


class TestFullFlow:
    @pytest.mark.asyncio
    async def test_agent_creates_session_posts_question_receives_answer(
        self, setup
    ):
        server, store, client = setup

        from mcp_server.tools import create_session, post_message

        result = await create_session(
            store=store,
            title="Define Feature X",
            host="localhost",
            port=24299,
            participant_names=["alice", "bob"],
        )
        session_id = result["session_id"]
        assert result["session_url"]

        await post_message(
            store=store,
            session_id=session_id,
            text="What problem does this feature solve?",
            metadata={"type": "question", "section": "overview"},
        )

        messages = store.get_messages(session_id)
        assert len(messages) == 1
        assert messages[0].metadata["type"] == "question"

        alice_token = store.get_session(session_id).participants[0].token
        resp = client.post(
            f"/api/sessions/{session_id}/messages?token={alice_token}",
            json={
                "author": "alice",
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

        from mcp_server.tools import create_session

        result = await create_session(
            store=store,
            title="Test Watch",
            host="localhost",
            port=24299,
            participant_names=["alice"],
        )
        session_id = result["session_id"]

        async def post_after_delay():
            await asyncio.sleep(0.1)
            store.add_message(session_id, "alice", "My answer")

        asyncio.create_task(post_after_delay())

        activity = await store.wait_for_activity(session_id, timeout=2.0)
        assert len(activity) >= 1
        assert activity[0].author == "alice"
        assert activity[0].text == "My answer"

    @pytest.mark.asyncio
    async def test_session_lifecycle(self, setup):
        server, store, client = setup

        from mcp_server.tools import (
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

        status = await get_session_status(
            store=store, session_id=session_id
        )
        assert status["status"] == "active"
        assert status["message_count"] == 1

        record = await end_session(store=store, session_id=session_id)
        assert record["status"] == "complete"
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/mcp_server/test_integration.py -v`
Expected: All tests PASS

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/mcp_server/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/mcp_server/test_integration.py
git commit -m "test(mcp): end-to-end integration tests for skill runtime"
```

---

### Task 8: `/draftcircle` adapter skill

**Files:**
- Create: `skill/draftcircle.md`

- [ ] **Step 1: Write the adapter skill**

Create `skill/draftcircle.md`:

````markdown
---
name: draftcircle
description: Run any skill collaboratively with multiple participants via Conducere. Wraps a target skill for multi-user execution through a shared web UI.
---

# Conducere — Collaborative Skill Execution

You are running a skill collaboratively via Conducere. Multiple
participants interact through a shared web UI while you execute the
skill's logic.

## Setup

1. Call the Conducere MCP tool `create_session` with a descriptive
   title based on the target skill.
2. Present the session URL to the coordinator:
   > "Share this link with participants: **{session_url}**"
   > Individual participant links: {participant_urls}
3. Wait briefly for participants to connect, then begin.

## Interaction Rules

**For ALL user-facing communication, use Conducere MCP tools:**

- Use `post_message` to communicate with participants. Add metadata:
  - `type`: `"question"` for questions, `"proposal"` for proposed
    content, `"summary"` for summaries, `"info"` for informational
    messages.
  - `section`: the current section/topic name from the skill.
- Use `watch_session` to receive participant responses. This is a
  background task — it returns when participants post messages.
- **Never use terminal I/O for skill content.** All questions,
  proposals, and updates go through Conducere.

**Processing participant input:**

- When `watch_session` returns messages, process ALL of them before
  responding.
- Multiple participants may respond — synthesize their input.
- If messages conflict, acknowledge the conflict and ask for
  clarification via `post_message`.

**Monitoring:**

- Use `get_session_status` to check who's active.
- If a participant reconnects and the `watch_session` returns a
  `/catchup` message, generate a summary of recent activity using
  `get_catchup_summary` and post it with
  `metadata: {"type": "summary", "for": "<participant_name>"}`.

## Completing the Session

When the skill's workflow is complete:

1. Post a final summary via `post_message` with
   `metadata: {"type": "summary"}`.
2. Call `end_session` to mark the session complete.
3. Proceed with any skill-specific output actions (e.g., creating a
   Jira issue).

## Target Skill Instructions

Follow the instructions below as the skill to execute. Apply all the
interaction rules above — route all participant communication through
Conducere MCP tools.

---

{target_skill_content}
````

- [ ] **Step 2: Verify the skill file is valid markdown**

Read through the file and confirm:
- The frontmatter has `name` and `description`.
- The `{target_skill_content}` placeholder is at the end for appending.
- The interaction rules are clear and unambiguous.

- [ ] **Step 3: Commit**

```bash
git add skill/draftcircle.md
git commit -m "feat: /draftcircle adapter skill for collaborative execution"
```

---

### Task 9: Final verification

**Files:**
- Verify: `pyproject.toml`

- [ ] **Step 1: Verify pyproject.toml is complete**

Confirm `pyproject.toml` contains:
- `fastmcp[tasks]>=3.0` in dependencies
- `mcp_server` in packages
- `draftcircle-mcp` entry point
- No references to `data_dir` (should be `repo_path` throughout)

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/mcp_server/ -v`
Expected: All tests PASS

- [ ] **Step 3: Run linter**

Run: `ruff check mcp_server/ tests/mcp_server/`
Expected: No errors

Run: `ruff format --check mcp_server/ tests/mcp_server/`
Expected: No formatting issues

- [ ] **Step 4: Fix any lint/format issues**

Run: `ruff format mcp_server/ tests/mcp_server/`
Run: `ruff check --fix mcp_server/ tests/mcp_server/`

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: final cleanup and verification"
```
