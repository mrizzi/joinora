"""Quick local test: starts web UI with a pre-made session."""

import tempfile
from pathlib import Path

import uvicorn

from conducere.session_store import SessionStore
from conducere.web import create_web_app

repo = Path(tempfile.mkdtemp(prefix="conducere-test-"))
store = SessionStore(repo_path=repo)

session, tokens = store.create_session(
    title="Define Feature X",
    participant_names=["alice", "bob"],
)

store.add_message(
    session.id,
    author="ai",
    text="Welcome! Let's define this feature together. What problem does it solve?",
    metadata={"type": "question", "section": "overview"},
)

print(f"\n  Session: {session.title}")
print(f"  Git repo: {repo}")
print()
for name, token in tokens.items():
    print(f"  {name}: http://localhost:24298/session/{session.id}?token={token}")
print()

app = create_web_app(store=store)
uvicorn.run(app, host="localhost", port=24298)
