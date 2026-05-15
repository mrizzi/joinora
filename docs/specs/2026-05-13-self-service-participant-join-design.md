# Self-Service Participant Join

Replace the pre-declared participant model with a self-service invite
link. Anyone with the session URL can join by picking a name. Sessions
and tokens survive server restarts via git persistence.

## Current State

Participants must be declared at `create_session` time via
`participant_names`. Each gets a unique token embedded in their URL.
No way to add participants after creation. Tokens are in-memory only
and lost on restart.

## Design

### Data Model

**Participant** stays the same: `name` + `last_seen`. The change is
*when* participants are created: at join-time via the web UI, not at
session-creation time.

**Session** starts with an empty `participants` list. Participants are
added dynamically as people join.

**Token storage** moves from in-memory-only to git-persisted. Each
session gets a `tokens.json` file:

```
sessions/{session_id}/
  session.json     # session metadata + participants
  messages.json    # message history
  tokens.json      # NEW: { "Alice": "abc123...", "Bob": "def456..." }
```

**Name uniqueness**: names must be unique within a session. The join
endpoint rejects duplicate names.

### Join Flow

**New endpoint: `POST /api/sessions/{session_id}/join`**

Request: `{ "name": "Alice" }`

1. Validate name (1-50 chars, `[\w\- ]+`, not reserved)
2. Reject if name already taken in this session
3. Create `Participant`, generate token (`secrets.token_urlsafe(16)`)
4. Add participant to session, store token, persist to git
5. Broadcast `participant_joined` via WebSocket
6. Trigger `watch_session` wake-up
7. Return `{ "token": "...", "name": "Alice" }`

No authentication required to call this endpoint. The session URL is
the authorization.

**Error responses:**
- 409: name already taken
- 400: invalid name (validation error)
- 404: session not found
- 410: session ended

### Session Lifecycle

**Server restart recovery**: `SessionStore.__init__` loads all
sessions from git on startup — `session.json`, `messages.json`, and
`tokens.json`. Active sessions are immediately usable.

**Agent reconnection**: new `list_sessions()` MCP tool returns all
sessions (active and complete) with IDs, titles, status, message
counts, and per-participant URLs (with tokens) — the same participant
detail as `get_session_status`. The agent uses existing tools
(`watch_session`, `post_message`, etc.) to resume driving a session.

**Reopen completed session**: new `reopen_session(session_id)` MCP
tool changes status from COMPLETE back to ACTIVE. Commits the change
to git.

### watch_session Event Model

`watch_session` wakes on both messages and participant joins.

Return format changes from `{ "messages": [...] }` to
`{ "events": [...] }` where each event has a `type`:

```json
{
  "events": [
    {
      "type": "participant_joined",
      "participant": {"name": "Bob"}
    },
    {
      "type": "message",
      "message": {"id": "msg-0001", "author": "Bob", "text": "Hello", "timestamp": "..."}
    }
  ]
}
```

Events are ordered chronologically. The skill decides whether to act
on join events (e.g., greet, summarize, or ignore).

**Wake triggers:**
- Message posted -> event added, watch_session wakes
- Participant joins via web -> event added, watch_session wakes

Disconnect events are not included. The agent can check
`get_session_status` for current connection state.

### Frontend

**Token storage**: switch from `sessionStorage` to `localStorage`.
Tokens persist across tabs and browser restarts. Key format:
`dc-token-{session_id}` (unchanged). Different sessions use different
keys, so no collision when joining multiple sessions.

**Join overlay**: when someone opens the session URL without a token
in `localStorage`:
- Session page loads with a centered overlay on top of the thread
- Thread is visible but dimmed behind the overlay (context)
- Overlay shows session title + name input + "Join" button
- After joining: token stored, overlay disappears, textarea unlocks,
  WebSocket connects

**Error handling in join form:**
- Name already taken: inline error, pick another name
- Session ended: "This session has ended" message
- Invalid name: inline validation error

**Read-only observer mode removed.** Without a token, you see the
join form. To see the thread, you join.

**With a token in localStorage**: same as today. No overlay, straight
to the thread, textarea enabled.

### MCP Tool Changes

**Modified:**

| Tool | Change |
|---|---|
| `create_session` | Remove `participant_names`. Returns `{ session_id, session_url }`. |
| `watch_session` | Returns `{ events: [...] }` with `type: "message"` and `type: "participant_joined"`. |
| `get_session_status` | Includes `session_url` and per-participant `url` (with token). |

**New:**

| Tool | Purpose |
|---|---|
| `list_sessions` | All sessions with IDs, titles, participants, URLs. For agent reconnection. |
| `reopen_session` | Change completed session back to active. |

**Unchanged:** `post_message`, `get_catchup_summary`, `end_session`.

### Skill File Update

The `/joinora` adapter skill (`SKILL.md` and `joinora.md`) must
be updated:
- `create_session` no longer takes participant names
- The session URL is the invite link to share
- `watch_session` returns events, not just messages
- New `list_sessions` and `reopen_session` tools documented

### Backend

**New `SessionStore` method:** `add_participant(session_id, name)` —
creates participant, generates token, persists to git, triggers
watch_session wake-up.

**Startup loading in `SessionStore.__init__`:** read all
`sessions/*/session.json`, `sessions/*/messages.json`, and
`sessions/*/tokens.json` from the git repo. Populate `_sessions`
and `_tokens`.

**New web endpoint:** `POST /api/sessions/{session_id}/join` — calls
`add_participant`, broadcasts WebSocket event, returns token.
