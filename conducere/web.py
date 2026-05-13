from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from conducere.ws_manager import WebSocketManager
from conducere.session_store import SessionStore


class PostMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    metadata: dict[str, str] | None = None


def create_web_app(store: SessionStore) -> FastAPI:
    app = FastAPI()
    ws_manager = WebSocketManager()
    app.state.ws_manager = ws_manager
    app.state.store = store

    async def _notify_agent_state(session_id: str, state: str) -> None:
        await ws_manager.broadcast(session_id, {"type": f"agent_{state}"})

    store.on_agent_state_change = _notify_agent_state

    csp = (
        "default-src 'self'; "
        "script-src 'self' cdn.jsdelivr.net; "
        "style-src 'self'; "
        "connect-src 'self' ws: wss:; "
        "img-src 'self' data:"
    )

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            response.headers["Content-Security-Policy"] = csp
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response

    app.add_middleware(SecurityHeadersMiddleware)

    def _authenticate(session_id: str, token: str | None) -> str | None:
        if not token:
            return None
        return store.authenticate(session_id, token)

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str, token: str | None = None):
        user = _authenticate(session_id, token)
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        session = store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        data = session.model_dump(mode="json")
        data["current_user"] = user
        participant = next((p for p in session.participants if p.name == user), None)
        data["last_seen"] = (
            participant.last_seen.isoformat()
            if participant and participant.last_seen
            else None
        )
        for p in data.get("participants", []):
            p.pop("token", None)
        data.pop("messages", None)
        return data

    @app.get("/api/sessions/{session_id}/messages")
    def get_messages(
        session_id: str, since: str | None = None, token: str | None = None
    ):
        user = _authenticate(session_id, token)
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
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
            raise HTTPException(status_code=401, detail="Authentication required")
        try:
            message = store.add_message(
                session_id=session_id,
                author=user,
                text=req.text,
                metadata=req.metadata,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await ws_manager.broadcast(
            session_id,
            {"type": "message_added", "message": message.model_dump(mode="json")},
        )
        return message.model_dump(mode="json")

    @app.websocket("/ws/sessions/{session_id}")
    async def websocket_endpoint(websocket: WebSocket, session_id: str):
        token = websocket.query_params.get("token")
        user = _authenticate(session_id, token)
        if user is None:
            await websocket.close(code=4001, reason="Authentication required")
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
            store.update_last_seen(session_id, user, datetime.now(timezone.utc))
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
            "/", StaticFiles(directory=str(frontend_dir), html=True), name="static"
        )

    return app
