# Joinora

Collaborative multi-user runtime for structured prompt/skill execution.
**The skill controls the agenda; participants control the content.**

Any coding agent (Claude Code, Cursor, Windsurf, etc.) runs a skill
through Joinora's MCP server. Participants join via browser and
contribute content asynchronously. BYOS — Bring Your Own Skill.

------------------------------------------------------------------------

# Architecture

Two interfaces, one process, shared state:

- **MCP Server** (FastMCP, Streamable HTTP) — the agent connects here
  and uses 6 tools to drive the session.
- **Web UI Server** (FastAPI, daemon thread) — participants connect
  via browser with WebSocket for real-time sync.
- **Session Store** — in-memory cache + git persistence (pygit2).
  Every mutation is a git commit.

```
joinora/
  models.py           # Pydantic models: Session, Message, Participant
  session_store.py    # Git-backed store with async subscriber notification
  tools.py            # MCP tool functions
  server.py           # FastMCP server, CLI entry point
  web.py              # FastAPI web app (REST + WebSocket)
  git_store.py        # pygit2 wrapper
  ws_manager.py       # WebSocket connection manager
  frontend/           # Vanilla HTML/CSS/JS conversation thread UI
skill/
  skills/joinora/   # /joinora adapter skill (BYOS wrapper)
tests/joinora/      # 65 tests
```

------------------------------------------------------------------------

# Key Concepts

- **Session** — a flat message thread with participants. No sections,
  templates, or proposals. The skill determines the structure.
- **Message** — text with optional metadata (`type`, `section`, `for`)
  for richer UI rendering.
- **Participant** — identified by name, authenticated by token stored
  in SessionStore (never serialized to git).
- **MCP Tasks** — `watch_session` runs as an async background task,
  returning when participants post messages.
- **Adapter Skill** — `/joinora` wraps any target skill with
  interaction rules that route I/O through Joinora MCP tools.

------------------------------------------------------------------------

# Tech Stack

| Component | Choice |
|---|---|
| Language | Python 3.12+ |
| MCP framework | FastMCP |
| Web framework | FastAPI |
| Git operations | pygit2 |
| Frontend | Vanilla HTML/CSS/JS |
| Markdown rendering | marked.js (safe renderer) |

------------------------------------------------------------------------

# Development Commands

```bash
# Install dependencies
pip install -e ".[dev]"

# Run the MCP server (starts web UI on daemon thread)
joinora --repo-path /path/to/data --web-port 24298

# Run tests
pytest tests/

# Format
ruff format .

# Lint
ruff check .

# Quick local test (creates a session, starts web UI)
python3 test_local.py
```

------------------------------------------------------------------------

# MCP Tools

| Tool | Purpose |
|---|---|
| `create_session` | Create session, returns URLs for participants |
| `post_message` | Post AI message with optional metadata |
| `watch_session` | Async MCP Task — waits for participant activity |
| `get_session_status` | Check who's connected, message count |
| `get_catchup_summary` | Messages since timestamp for summary generation |
| `end_session` | Mark session complete |

------------------------------------------------------------------------

# Conventions

- Python code follows ruff defaults for formatting and linting.
- No comments unless the WHY is non-obvious.
- Frontend: no framework, no build step. XSS-safe DOM construction
  (textContent for user data, marked.js with safe renderer for
  markdown).
- Git commit messages: imperative mood, concise.
- Tokens persisted to git (`tokens.json`) for restart recovery.
  Never included in API responses except the join endpoint's
  response to the joining participant.
