import argparse
import tempfile
import threading
from pathlib import Path

from fastmcp import FastMCP

from conducere.session_store import SessionStore


def create_server(
    repo_path: Path | None = None,
    web_host: str = "localhost",
    web_port: int = 24298,
) -> FastMCP:
    if repo_path is None:
        repo_path = Path(tempfile.mkdtemp(prefix="conducere-"))
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
    async def create_session(title: str) -> dict:
        """Create a new collaborative session. Returns session_id and
        a session_url to share with participants."""
        from conducere.tools import create_session as _create

        return await _create(
            store=store,
            title=title,
            host=web_host,
            port=web_port,
        )

    @mcp.tool()
    async def post_message(
        session_id: str,
        text: str,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """Post an AI message visible to all participants in the session."""
        from conducere.tools import post_message as _post

        result = await _post(
            store=store,
            session_id=session_id,
            text=text,
            metadata=metadata,
        )
        web_app = getattr(mcp, "_web_app", None)
        if web_app:
            ws_mgr = web_app.state.ws_manager
            msg = result["message"]
            await ws_mgr.broadcast(
                session_id,
                {"type": "message_added", "message": msg.model_dump(mode="json")},
            )
        return {"message_id": result["message_id"]}

    @mcp.tool(task=True)
    async def watch_session(session_id: str) -> dict:
        """Start monitoring a session for participant activity.
        Returns new messages when participants comment.
        Runs as a background MCP Task."""
        messages = await store.wait_for_activity(session_id, timeout=300.0)
        return {
            "messages": [m.to_wire() for m in messages],
        }

    @mcp.tool()
    async def get_session_status(session_id: str) -> dict:
        """Check session state: who's connected, last activity, message count."""
        from conducere.tools import get_session_status as _status

        return await _status(store=store, session_id=session_id)

    @mcp.tool()
    async def get_catchup_summary(session_id: str, since: str | None = None) -> dict:
        """Get messages since a timestamp for catch-up summary generation."""
        from conducere.tools import get_catchup_summary as _catchup

        return await _catchup(store=store, session_id=session_id, since=since)

    @mcp.tool()
    async def end_session(session_id: str) -> dict:
        """Mark a session as complete and return the conversation record."""
        from conducere.tools import end_session as _end

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

    server = create_server(
        repo_path=args.repo_path,
        web_host=args.web_host,
        web_port=args.web_port,
    )

    from conducere.web import create_web_app

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
