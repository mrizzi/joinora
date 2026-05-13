from datetime import datetime

from conducere.models import AI_AUTHOR
from conducere.session_store import SessionStore


async def create_session(
    store: SessionStore,
    title: str,
    host: str,
    port: int,
    participant_names: list[str] | None = None,
) -> dict:
    session, tokens = store.create_session(
        title=title, participant_names=participant_names
    )
    base_url = f"http://{host}:{port}/session/{session.id}"
    participant_urls = {
        name: f"{base_url}?token={token}" for name, token in tokens.items()
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
        session_id=session_id, author=AI_AUTHOR, text=text, metadata=metadata
    )
    return {"message_id": message.id, "message": message}


async def get_session_status(store: SessionStore, session_id: str) -> dict:
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
    since_dt = datetime.fromisoformat(since) if since else None
    messages = store.get_messages(session_id, since=since_dt)
    return {
        "message_count": len(messages),
        "messages": [m.to_wire() for m in messages],
    }


async def end_session(store: SessionStore, session_id: str) -> dict:
    return store.end_session(session_id)
