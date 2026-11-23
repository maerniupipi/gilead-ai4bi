from __future__ import annotations

from typing import Protocol

from .contracts import ChatMessage, ChatQuestion, ChatSession, MessageRole


class ChatRepository(Protocol):
    def get_session(self, session_id: str) -> ChatSession | None: ...

    def create_session(self, session_id: str, owner_id: str, title: str) -> ChatSession: ...

    def list_sessions(self, owner_id: str, limit: int = 50) -> list[ChatSession]: ...

    def list_user_questions(
        self, owner_id: str, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[ChatQuestion], int]: ...

    def append_message(
        self,
        message_id: str,
        session_id: str,
        role: MessageRole,
        content: str,
        run_id: str | None = None,
        fact_ids: tuple[str, ...] = (),
    ) -> ChatMessage: ...

    def list_messages(self, session_id: str) -> list[ChatMessage]: ...
