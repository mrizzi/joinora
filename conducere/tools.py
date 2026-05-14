from datetime import datetime

from conducere.models import AI_AUTHOR
from conducere.session_store import SessionStore


def _session_to_wire(session, tokens: dict[str, str], host: str, port: int) -> dict:
    base_url = f"http://{host}:{port}/session/{session.id}"
    return {
        "session_id": session.id,
        "session_url": base_url,
        "title": session.title,
        "status": session.status.value,
        "message_count": len(session.messages),
        "participants": [
            {
                "name": p.name,
                "url": f"{base_url}?token={tokens.get(p.name, '')}",
                "last_seen": (p.last_seen.isoformat() if p.last_seen else None),
            }
            for p in session.participants
        ],
    }


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


async def post_message(
    store: SessionStore,
    session_id: str,
    text: str,
    metadata: dict[str, str] | None = None,
) -> dict:
    message = store.add_message(
        session_id=session_id, author=AI_AUTHOR, text=text, metadata=metadata
    )
    return {"message_id": message.id, "message": message}


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
    return _session_to_wire(session, tokens, host, port)


async def get_catchup_summary(
    store: SessionStore,
    session_id: str,
    since: str | None = None,
) -> dict:
    since_dt = datetime.fromisoformat(since) if since else None
    messages = store.get_messages(session_id, since=since_dt)
    return {
        "message_count": len(messages),
        "messages": [m.to_wire() for m in messages],
    }


async def end_session(store: SessionStore, session_id: str) -> dict:
    return store.end_session(session_id)


async def list_sessions(
    store: SessionStore,
    host: str,
    port: int,
) -> dict:
    sessions = store.list_all_sessions()
    result = []
    for session in sessions:
        tokens = store.get_participant_tokens(session.id)
        result.append(_session_to_wire(session, tokens, host, port))
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
