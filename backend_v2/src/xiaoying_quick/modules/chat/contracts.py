from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from xiaoying_quick.shared.compat import StrEnum


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class ChatSession:
    id: str
    owner_id: str
    title: str
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ChatMessage:
    id: str
    session_id: str
    run_id: str | None
    role: MessageRole
    content: str
    fact_ids: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True)
class ChatQuestion:
    id: str
    session_id: str
    session_title: str
    content: str
    run_id: str | None
    created_at: datetime
