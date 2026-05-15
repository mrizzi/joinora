from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

AI_AUTHOR = "ai"
RESERVED_NAMES = frozenset({"ai", "system", "admin"})


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETE = "complete"


class AgentState(str, Enum):
    LISTENING = "listening"
    PROCESSING = "processing"
    DISCONNECTED = "disconnected"


def _check_not_reserved(v: str) -> str:
    if v.lower() in RESERVED_NAMES:
        raise ValueError(f"Participant name '{v}' is reserved")
    return v


ParticipantName = Annotated[
    str,
    Field(min_length=1, max_length=50, pattern=r"^[\w\- ]+$"),
    AfterValidator(_check_not_reserved),
]


class Participant(BaseModel):
    name: ParticipantName
    last_seen: datetime | None = None


class Message(BaseModel):
    id: str
    author: str = Field(min_length=1)
    text: str = Field(min_length=1)
    timestamp: datetime
    metadata: dict[str, str] | None = None

    def to_wire(self) -> dict:
        return {
            "id": self.id,
            "author": self.author,
            "text": self.text,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


class Session(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    status: SessionStatus = SessionStatus.ACTIVE
    participants: list[Participant] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    created_at: datetime


@dataclass
class MessageEvent:
    message: Message


@dataclass
class ParticipantJoinedEvent:
    name: str


SessionEvent = MessageEvent | ParticipantJoinedEvent
