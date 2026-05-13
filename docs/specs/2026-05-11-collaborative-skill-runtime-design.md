# Conducere — Collaborative Skill Runtime

## Mission

Conducere is a collaborative multi-user runtime for structured
prompt/skill execution. **The skill controls the agenda; participants
control the content.**

A skill like `define-feature` runs as a single-user CLI conversation
today. Conducere turns that into a multi-user collaborative session
where the skill's logic orchestrates the workflow while multiple
participants contribute content asynchronously — with real-time sync
and a shared conversation thread.

### BYOS (Bring Your Own Skill)

Users bring any structured skill/prompt and Conducere runs it
collaboratively. The skill is unmodified — Conducere adapts to it,
not the other way around.

------------------------------------------------------------------------

## Architecture

Conducere is an **MCP server** with an embedded **web UI server**
running as a daemon thread in the same process (following the Serena
dashboard pattern). Two interfaces, one process, shared state.

```
┌─────────────────────────────────────────────────────┐
│  Conducere MCP Server Process                     │
│                                                     │
│  ┌──────────────────────┐  ┌──────────────────────┐ │
│  │ MCP Server           │  │ Web UI Server        │ │
│  │ (Streamable HTTP)    │  │ (daemon thread)      │ │
│  │                      │  │                      │ │
│  │ Tools:               │  │ - Static files       │ │
│  │ - create_session     │  │ - WebSocket          │ │
│  │ - post_message       │  │ - REST API           │ │
│  │ - watch_session      │  │                      │ │
│  │ - get_session_status │  │                      │ │
│  │ - get_catchup_summary│  │                      │ │
│  │ - end_session        │  │                      │ │
│  └──────────┬───────────┘  └──────────┬───────────┘ │
│             │       shared state      │             │
│             └────────────┬────────────┘             │
│                          │                          │
│                ┌─────────▼──────────┐               │
│                │ Session Store      │               │
│                │ (in-memory + git)  │               │
│                └────────────────────┘               │
└─────────────────────────────────────────────────────┘
```

**Agent side:** Any coding agent (Claude Code, Cursor, Windsurf, Codex,
etc.) connects via MCP. The agent runs the skill and uses Conducere
MCP tools for all participant interaction.

**Participant side:** Participants open a browser URL and interact via
a shared conversation thread. WebSocket provides real-time updates.

**Transport:** Streamable HTTP — supports persistent SSE connections for
server-to-client event push via MCP Tasks.

------------------------------------------------------------------------

## The `/draftcircle` Adapter Skill

The adapter skill is the bridge between BYOS and Conducere. It is
installed as a plugin/skill in the coding agent.

### Invocation

```
/draftcircle define-feature
/draftcircle any-other-skill
```

### What It Does

1. Reads the target skill's markdown content (the instructions).
2. Connects to the Conducere MCP server.
3. Creates a session — gets back a session URL and ID.
4. Presents the URL to the coordinator:
   "Share this link with participants: http://localhost:24298/session/abc123"
5. Injects a preamble into the agent's context:
   - "You are running a collaborative session. Follow the target skill's
     instructions, but for all user interaction, use Conducere MCP
     tools: `post_message()` to communicate, `watch_session()` to
     receive participant input. Never use terminal I/O for skill
     content."
   - "When posting messages, classify them with metadata — set `type`
     to `question`, `proposal`, `summary`, etc. based on the nature
     of your message. Set `section` based on which part of the skill
     you're currently working on."
6. Appends the target skill's original instructions.
7. The agent executes — following the skill's logic but routing all
   interaction through Conducere.

### What It Does NOT Do

- Parse or understand the target skill's structure.
- Know about sections, Jira, or any domain concept.
- Modify the target skill's instructions.

It is purely an I/O redirect: "follow these instructions, but talk
through Conducere instead of the terminal."

------------------------------------------------------------------------

## Event Flow

### Participant → Agent

1. Participant comments in browser.
2. Comment goes via WebSocket to the web UI server thread.
3. Web server writes to shared session store, signals waiting
   subscribers (threading Event/Queue).
4. `watch_session` MCP Task wakes up, transitions to `input_required`.
5. Agent polls `tasks/get`, sees `input_required`.
6. Agent calls `tasks/result`, gets the new comment(s).
7. Agent processes (follows skill instructions), decides next action.
8. Agent calls `post_message()` with response and optional metadata.
9. Agent calls `tasks/input_response` to resume the task.

### Agent → Participants

1. Agent calls `post_message(session_id, text, metadata?)`.
2. MCP tool writes message to shared session store.
3. Web server broadcasts via WebSocket to all connected browsers.
4. All participants see the message in real time.

### MCP Tasks Pattern

The agent never blocks on a long-poll. It starts an async MCP Task
and checks on it — standard MCP Tasks protocol:

```
Agent: tools/call watch_session(session_id)
Server: returns taskId, status: "working"

... participant comments ...

Server: transitions task to status: "input_required"
Agent: tasks/get → sees input_required
Agent: tasks/result → gets comments
Agent: processes, calls post_message()
Agent: tasks/input_response → task resumes to "working"

... repeat until session ends ...
```

If multiple participants comment before the agent processes, all
comments are batched and returned together in `tasks/result`.

If the agent disconnects and reconnects, it starts a new
`watch_session` task. Messages posted while disconnected are not lost
(persisted in the session store) and are returned on the next
`tasks/result` call.

------------------------------------------------------------------------

## MCP Tools

| Tool | Parameters | Returns | Purpose |
|------|-----------|---------|---------|
| `create_session` | `title`, `participants?` | `session_id`, `session_url` | Create a new collaborative session |
| `post_message` | `session_id`, `text`, `metadata?` | `message_id` | Post an AI message visible to all participants |
| `watch_session` | `session_id` | MCP Task (async) | Start monitoring session for participant activity |
| `get_session_status` | `session_id` | participants, last activity, message count | Check session state |
| `get_catchup_summary` | `session_id`, `since?` | messages since timestamp | Raw messages for summary generation |
| `end_session` | `session_id` | conversation record | Mark session complete |

### Message Metadata

Metadata is optional and agent-supplied. The `/draftcircle` adapter
skill instructs the agent to add it when possible. The web UI uses
metadata for richer rendering but degrades gracefully without it.

Suggested metadata fields:

| Field | Values | Purpose |
|-------|--------|---------|
| `type` | `question`, `proposal`, `summary`, `info` | Message classification for UI styling |
| `section` | free-form string | Grouping/filtering in UI |
| `for` | participant name | Targeted messages (e.g., catch-up summaries) |

------------------------------------------------------------------------

## Session Model

Flat and simple. Conducere does not model the skill's structure —
sections, approval gates, and workflow logic are the skill's concern.

### Session

- `id` — unique identifier
- `title` — display name
- `status` — `active` or `complete`
- `participants` — list of connected users with invite tokens
- `messages` — chronologically ordered thread
- `created_at` — timestamp

### Message

- `id` — unique identifier
- `author` — participant name or `"ai"`
- `text` — message content
- `metadata` — optional key-value pairs (agent-supplied)
- `timestamp` — when posted

### Participant

- `name` — display name
- `token` — invite/auth token, embedded in the session URL
  (e.g., `http://localhost:24298/session/abc123?token=xyz`)
- `last_seen` — timestamp of last activity

### Persistence

All session data is persisted via git commits (existing Conducere
pattern). Every message is a commit with a semantic message.

------------------------------------------------------------------------

## Web UI

A real-time shared conversation thread. All participants see the same
view.

### Core View

- Message thread — chronological, real-time via WebSocket.
- Comment input — always available at the bottom.
- Participant list — who's connected, last active.

### Message Rendering

Based on optional metadata:

- No metadata → plain message bubble.
- `type: "question"` → highlighted, visually distinct.
- `type: "proposal"` → content preview, possibly collapsible.
- `type: "summary"` → catch-up summary styling.
- `section` present → groupable/filterable.
- `for` present → shown only (or highlighted) to the named participant.

### Catch-up Summary

When a participant reconnects after being away:

1. Web UI detects gap between `last_seen` and current time.
2. Shows banner: "N new messages since you were last here. Want a
   summary?"
3. If participant clicks yes → session event sent to agent.
4. Agent generates summary from recent messages, posts with
   `metadata: {"type": "summary", "for": "alice"}`.
5. Web UI shows the summary to the returning participant.
6. If participant declines → they scroll through messages themselves.

### No Special Coordinator UI

The coordinator interacts through their coding agent. The web UI is
the same for all participants. The agent is just another participant
in the thread (posting AI messages).

------------------------------------------------------------------------

## What Conducere Provides vs. What the Skill Provides

| Concern | Conducere | Skill |
|---------|-------------|-------|
| Multi-user input | Yes — comment thread | — |
| Real-time sync | Yes — WebSocket | — |
| Participant management | Yes — invites, tokens, presence | — |
| Session persistence | Yes — git-backed | — |
| Catch-up summaries | Yes — reconnect detection + event | Generates the summary text |
| Conversation structure | No — flat messages | Yes — decides section order, priorities |
| Domain logic | No — skill-agnostic | Yes — what to ask, how to verify, when to move on |
| Approval workflow | No | Yes — managed through conversation |
| Output/publish | No | Yes — skill publishes to Jira, Confluence, etc. |
| AI capabilities | No — no internal AI | Yes — web search, API verification, etc. |

------------------------------------------------------------------------

## Relationship to Current Conducere

This design represents a significant evolution of Conducere's
architecture. The current system has an internal AI orchestrator,
structured templates with sections, proposal accept/reject workflow,
and output plugins.

### What Changes

- **AI orchestrator** — removed (or optional). The agent running the
  skill provides all AI capabilities.
- **Templates** — no longer needed as a Conducere concept. The skill
  defines the structure.
- **Sections** — removed from the data model. The skill manages
  structure through conversation and metadata.
- **Proposals with accept/reject** — removed. The skill handles
  approval through conversation.
- **Output plugins** — removed. The skill publishes to external systems
  directly.

### What Stays

- **Session management** — creating sessions, managing participants.
- **Git persistence** — every mutation is a commit.
- **WebSocket real-time sync** — broadcasting events to connected
  browsers.
- **Web UI** — the participant interface (simplified to a conversation
  thread).
- **Participant authentication** — invite tokens, coordinator role.

### Migration Path

The current Conducere can continue to work for template-driven
sessions. The new skill-driven mode is an addition, not a replacement.
Over time, template-driven sessions could be expressed as skills,
converging on a single model.
