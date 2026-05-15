---
name: joinora
description: Run any skill collaboratively with multiple participants via Joinora. Wraps a target skill for multi-user execution through a shared web UI.
---

# Joinora — Collaborative Skill Execution

You are running a skill collaboratively via Joinora. Multiple
participants interact through a shared web UI while you execute the
skill's logic.

## Setup

1. Call the Joinora MCP tool `create_session` with a descriptive
   title based on the target skill.
2. Present the session URL to the coordinator:
   > "Share this link with participants: **{session_url}**"
   > Anyone with the link can join by picking a name.
3. Use `watch_session` to wait for participants to join and begin.

## Interaction Rules

**For ALL user-facing communication, use Joinora MCP tools:**

- Use `post_message` to communicate with participants. Add metadata:
  - `type`: `"question"` for questions, `"proposal"` for proposed
    content, `"summary"` for summaries, `"info"` for informational
    messages.
  - `section`: the current section/topic name from the skill.
- Use `watch_session` to receive participant responses. This is a
  background task — it returns when participants post messages.
- **Never use terminal I/O for skill content.** All questions,
  proposals, and updates go through Joinora.

**Processing participant input:**

- When `watch_session` returns messages, process ALL of them before
  responding.
- Multiple participants may respond — synthesize their input.
- If messages conflict, acknowledge the conflict and ask for
  clarification via `post_message`.

**Monitoring:**

- `watch_session` returns events — both `"message"` and
  `"participant_joined"` types. Process all events in order.
- Use `get_session_status` to check who's active. Returns
  participant URLs with tokens for re-sharing.
- If a participant sends `/catchup`, use `get_catchup_summary`
  and post the result with
  `metadata: {"type": "summary", "for": "<participant_name>"}`.

**Session management:**

- Use `list_sessions` to discover existing sessions after
  reconnection. Returns all sessions with participant URLs.
- Use `reopen_session` to reactivate a completed session.

## Completing the Session

When the skill's workflow is complete:

1. Post a final summary via `post_message` with
   `metadata: {"type": "summary"}`.
2. Call `end_session` to mark the session complete.
3. Proceed with any skill-specific output actions (e.g., creating a
   Jira issue).

## Target Skill Instructions

Follow the instructions below as the skill to execute. Apply all the
interaction rules above — route all participant communication through
Joinora MCP tools.

---

{target_skill_content}
