from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

AI_AUTHOR = "ai"
RESERVED_NAMES = frozenset({"ai", "system", "admin"})


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETE = "complete"


class Participant(BaseModel):
    name: str = Field(min_length=1, max_length=50, pattern=r"^[\w\- ]+$")
    last_seen: datetime | None = None

    @field_validator("name")
    @classmethod
    def name_not_reserved(cls, v: str) -> str:
        if v.lower() in RESERVED_NAMES:
            raise ValueError(f"Participant name '{v}' is reserved")
        return v


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
