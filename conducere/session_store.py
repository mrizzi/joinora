import asyncio
import json
import logging
import secrets
import threading
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from conducere.git_store import GitStore
from conducere.models import AgentState, Message, Participant, Session, SessionStatus


logger = logging.getLogger(__name__)


class SessionStore:
    def __init__(self, repo_path: Path):
        self._git = GitStore(repo_path)
        self._sessions: dict[str, Session] = {}
        self._tokens: dict[str, dict[str, str]] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._loops: dict[str, asyncio.AbstractEventLoop] = {}
        self._pending: dict[str, list[dict]] = {}
        self._lock = threading.Lock()
        self.on_agent_state_change: (
            Callable[[str, AgentState], Awaitable[None]] | None
        ) = None
        self._load_from_git()

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

    def _session_dir(self, session_id: str) -> str:
        return f"sessions/{session_id}"

    def _save_session(self, session: Session, message: str) -> str:
        path = f"{self._session_dir(session.id)}/session.json"
        return self._git.commit(message, {path: session.model_dump_json(indent=2)})

    def _save_messages(self, session: Session, commit_message: str) -> str:
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
                f"{base}/tokens.json": json.dumps(self._tokens[session_id], indent=2),
            },
        )
        with self._lock:
            event = self._events.get(session_id)
            loop = self._loops.get(session_id)
        if event and loop:
            loop.call_soon_threadsafe(event.set)
        return token

    def get_session(self, session_id: str) -> Session | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            return session.model_copy(deep=True)

    def authenticate(self, session_id: str, token: str) -> str | None:
        with self._lock:
            session_tokens = self._tokens.get(session_id, {})
            for name, t in session_tokens.items():
                if t == token:
                    return name
        return None

    def get_participant_tokens(self, session_id: str) -> dict[str, str]:
        with self._lock:
            return dict(self._tokens.get(session_id, {}))

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

            msg_id = f"msg-{len(session.messages) + 1:04d}"
            message = Message(
                id=msg_id,
                author=author,
                text=text,
                timestamp=datetime.now(timezone.utc),
                metadata=metadata,
            )
            session.messages.append(message)
            self._pending.setdefault(session_id, []).append(
                {"type": "message", "message": message}
            )

        self._save_messages(session, f"message: {author} in {session_id}")
        with self._lock:
            event = self._events.get(session_id)
            loop = self._loops.get(session_id)
        if event and loop:
            loop.call_soon_threadsafe(event.set)
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

    async def wait_for_activity(
        self, session_id: str, timeout: float = 300.0
    ) -> list[dict]:
        event = asyncio.Event()
        loop = asyncio.get_running_loop()
        with self._lock:
            self._events[session_id] = event
            self._loops[session_id] = loop
            self._pending[session_id] = []

        if self.on_agent_state_change:
            try:
                await self.on_agent_state_change(session_id, AgentState.LISTENING)
            except Exception:
                logger.warning("agent state callback failed", exc_info=True)

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

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
