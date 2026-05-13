# Agent Status Indicator

Visual indicators in the Conducere web UI showing whether the agent is
listening (connected via MCP `watch_session`), processing a reply, or
disconnected.

## Problem

Participants in a Conducere session have no visibility into whether the
agent is connected or working. After posting a message, they see nothing
until the agent's reply appears — no feedback on whether anyone is
listening.

## Design

Two UI elements, three states, driven by real-time WebSocket events from
the backend.

### States

| State | Header Dot | Thread Indicator |
|---|---|---|
| **Listening** | Purple (#a78bfa), soft glow, slow pulse animation (2s ease-in-out) | Hidden |
| **Processing** | Purple (#a78bfa), steady (no pulse) | Animated bar (24px × 3px, purple, opacity pulse 1.2s) + "thinking..." text |
| **Disconnected** | Gray (#666), no glow, no animation | Hidden |

Initial state on page load is Disconnected.

### Backend: WebSocket Events

Three new event types broadcast over the existing WebSocket channel:

| Event | Trigger | Payload |
|---|---|---|
| `agent_listening` | `wait_for_activity()` entry | `{"type": "agent_listening"}` |
| `agent_processing` | `wait_for_activity()` returns with pending messages | `{"type": "agent_processing"}` |
| `agent_disconnected` | `wait_for_activity()` times out with no messages | `{"type": "agent_disconnected"}` |

#### Callback Pattern

`session_store.py` stays decoupled from the WebSocket layer. It accepts
an `on_agent_state_change` callback — an async function
`(session_id: str, state: str) -> None`. The store calls it at
entry/exit of `wait_for_activity()` with the state string (`"listening"`,
`"processing"`, or `"disconnected"`).

`server.py` wires the callback at startup to broadcast via
`ws_manager`:

```python
async def _notify_agent_state(sid: str, state: str) -> None:
    await ws_manager.broadcast(sid, {"type": f"agent_{state}"})

store.on_agent_state_change = _notify_agent_state
```

### Frontend: Header Dot

An 8px-diameter dot element placed immediately left of the session title
in the `<header>`. CSS classes toggle appearance:

- `.agent-dot.listening` — purple with glow and pulse keyframe
- `.agent-dot.processing` — purple with glow, no pulse
- `.agent-dot.disconnected` — gray, no glow

JavaScript in `app.js` listens for the three new WebSocket event types
and sets the appropriate class.

### Frontend: Thread Typing Indicator

A transient `div#agent-typing` appended to the bottom of `#messages`
when the agent is processing:

- Contains an animated bar and "thinking..." label
- Auto-scrolls into view (only if user is near bottom, matching
  existing new-message scroll behavior)
- Removed instantly on `message_added` or `agent_listening` events
- Pure CSS animation (`@keyframes` opacity pulse on the bar)

### Data Flow

```
Agent calls watch_session()
  → wait_for_activity() entry
    → callback("listening")
      → broadcast {type: "agent_listening"}
        → dot: purple+pulse, typing: hidden

Participant posts message
  → wait_for_activity() wakes, returns messages
    → callback("processing")
      → broadcast {type: "agent_processing"}
        → dot: purple steady, typing: shown

Agent calls post_message()
  → broadcast {type: "message_added"}
    → typing: removed instantly

Agent calls watch_session() again
  → cycle repeats

wait_for_activity() times out (300s)
  → callback("disconnected")
    → broadcast {type: "agent_disconnected"}
      → dot: gray, typing: hidden
```

### Edge Cases

- **Agent never re-watches after posting:** Frontend stays in
  "processing" until the next event. Acceptable — the agent may be
  doing further work.
- **Multiple rapid participant messages:** All batch into `_pending`.
  `agent_processing` fires once when `wait_for_activity` first wakes.
  No duplicate indicators.
- **Page refresh:** Dot starts as Disconnected. Correct state arrives
  with the next agent state event.

## Files Changed

| File | Change |
|---|---|
| `conducere/session_store.py` | Add `on_agent_state_change` callback. Invoke at entry/exit of `wait_for_activity()`. |
| `conducere/server.py` | Wire callback to `ws_manager.broadcast()` at startup. |
| `conducere/frontend/index.html` | Add `.agent-dot` element in header. |
| `conducere/frontend/style.css` | Styles for `.agent-dot` states, `#agent-typing`, `@keyframes` for pulse and bar animations. |
| `conducere/frontend/app.js` | Handle `agent_listening`, `agent_processing`, `agent_disconnected` WebSocket events. Manage dot class and typing indicator lifecycle. |
| `tests/conducere/` | Tests for callback invocation in `wait_for_activity` and WebSocket event broadcasting. |

No new files. No changes to MCP tools or Pydantic models.
