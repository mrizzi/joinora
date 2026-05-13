---
name: conducere
description: Run any skill collaboratively with multiple participants via Conducere. Wraps a target skill for multi-user execution through a shared web UI.
---

# Conducere — Collaborative Skill Execution

You are running a skill collaboratively via Conducere. Multiple
participants interact through a shared web UI while you execute the
skill's logic.

## Setup

1. Call the Conducere MCP tool `create_session` with a descriptive
   title based on the target skill.
2. Present the session URL to the coordinator:
   > "Share this link with participants: **{session_url}**"
   > Individual participant links: {participant_urls}
3. Wait briefly for participants to connect, then begin.

## Interaction Rules

**For ALL user-facing communication, use Conducere MCP tools:**

- Use `post_message` to communicate with participants. Add metadata:
  - `type`: `"question"` for questions, `"proposal"` for proposed
    content, `"summary"` for summaries, `"info"` for informational
    messages.
  - `section`: the current section/topic name from the skill.
- Use `watch_session` to receive participant responses. This is a
  background task — it returns when participants post messages.
- **Never use terminal I/O for skill content.** All questions,
  proposals, and updates go through Conducere.

**Processing participant input:**

- When `watch_session` returns messages, process ALL of them before
  responding.
- Multiple participants may respond — synthesize their input.
- If messages conflict, acknowledge the conflict and ask for
  clarification via `post_message`.

**Monitoring:**

- Use `get_session_status` to check who's active.
- If a participant reconnects and the `watch_session` returns a
  `/catchup` message, generate a summary of recent activity using
  `get_catchup_summary` and post it with
  `metadata: {"type": "summary", "for": "<participant_name>"}`.

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
Conducere MCP tools.

---

{target_skill_content}
