# Conducere — Project Overview

Collaborative multi-user runtime for structured prompt/skill execution.
Any coding agent runs a skill through Conducere's MCP server.
Participants join via browser and contribute content asynchronously.

## Architecture
- **MCP Server** (FastMCP, Streamable HTTP) — agent connects here, uses 6 tools
- **Web UI Server** (FastAPI, daemon thread) — participants connect via browser + WebSocket
- **Session Store** — in-memory cache + git persistence (pygit2)

## Tech Stack
| Component | Choice |
|---|---|
| Language | Python 3.12+ |
| MCP framework | FastMCP |
| Web framework | FastAPI |
| Git operations | pygit2 |
| Frontend | Vanilla HTML/CSS/JS |
| Markdown rendering | marked.js |

## Codebase Structure
```
conducere/
  models.py           # Pydantic models: Session, Message, Participant
  session_store.py    # Git-backed store with async subscriber notification
  tools.py            # MCP tool functions
  server.py           # FastMCP server, CLI entry point
  web.py              # FastAPI web app (REST + WebSocket)
  git_store.py        # pygit2 wrapper
  ws_manager.py       # WebSocket connection manager
  frontend/           # Vanilla HTML/CSS/JS conversation thread UI
skill/
  skills/conducere/   # /conducere adapter skill (BYOS wrapper)
tests/conducere/      # ~88 tests
```
