from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from joinora.models import Message, Participant, Session, SessionStatus


class TestParticipant:
    def test_create_participant(self):
        p = Participant(name="alice")
        assert p.name == "alice"
        assert p.last_seen is None

    def test_name_required(self):
        with pytest.raises(ValidationError):
            Participant(name="")

    def test_reserved_name_rejected(self):
        with pytest.raises(ValidationError, match="reserved"):
            Participant(name="ai")

    def test_reserved_name_case_insensitive(self):
        with pytest.raises(ValidationError, match="reserved"):
            Participant(name="Admin")

    def test_special_characters_rejected(self):
        with pytest.raises(ValidationError):
            Participant(name="alice;DROP")

    def test_max_length_enforced(self):
        with pytest.raises(ValidationError):
            Participant(name="a" * 51)


class TestMessage:
    def test_create_plain_message(self):
        msg = Message(
            id="msg-001",
            author="alice",
            text="Hello",
            timestamp=datetime.now(timezone.utc),
        )
        assert msg.metadata is None

    def test_create_message_with_metadata(self):
        msg = Message(
            id="msg-002",
            author="ai",
            text="What is the feature?",
            timestamp=datetime.now(timezone.utc),
            metadata={"type": "question", "section": "overview"},
        )
        assert msg.metadata["type"] == "question"

    def test_to_wire_format(self):
        ts = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)
        msg = Message(
            id="msg-001",
            author="alice",
            text="Hello",
            timestamp=ts,
            metadata={"type": "question"},
        )
        wire = msg.to_wire()
        assert wire["id"] == "msg-001"
        assert wire["author"] == "alice"
        assert wire["text"] == "Hello"
        assert wire["timestamp"] == "2026-05-11T12:00:00+00:00"
        assert wire["metadata"] == {"type": "question"}

    def test_author_required(self):
        with pytest.raises(ValidationError):
            Message(
                id="msg-003",
                author="",
                text="Hello",
                timestamp=datetime.now(timezone.utc),
            )


class TestSession:
    def test_create_session(self):
        s = Session(
            id="session-001",
            title="Define Feature X",
            created_at=datetime.now(timezone.utc),
        )
        assert s.status == SessionStatus.ACTIVE
        assert s.participants == []
        assert s.messages == []

    def test_default_status_is_active(self):
        s = Session(
            id="s1",
            title="Test",
            created_at=datetime.now(timezone.utc),
        )
        assert s.status == SessionStatus.ACTIVE
