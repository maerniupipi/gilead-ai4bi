from __future__ import annotations

from collections.abc import Callable

from ...shared.errors import Forbidden, NotFound, ValidationFailed
from ..identity import AuthenticatedPrincipal, Role
from .contracts import ChatMessage, ChatQuestion, ChatSession, MessageRole
from .ports import ChatRepository


class ChatService:
    def __init__(
        self,
        repository: ChatRepository,
        session_id_factory: Callable[[], str],
        message_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._session_id_factory = session_id_factory
        self._message_id_factory = message_id_factory or session_id_factory

    def get_or_create_session(
        self, principal: AuthenticatedPrincipal, session_id: str | None, question: str
    ) -> ChatSession:
        if session_id:
            session = self._repository.get_session(session_id)
            if session is None:
                raise NotFound("chat session not found")
            self._authorize(principal, session)
            return session
        title = " ".join(question.strip().split())[:64] or "新对话"
        return self._repository.create_session(
            self._session_id_factory(),
            principal.user_id,
            title,
        )

    def append_user_message(self, session: ChatSession, run_id: str, content: str) -> ChatMessage:
        if not content.strip():
            raise ValidationFailed("message cannot be blank")
        return self._repository.append_message(
            self._message_id_factory(),
            session.id,
            MessageRole.USER,
            content.strip(),
            run_id,
        )

    def append_assistant_message(
        self,
        session: ChatSession,
        run_id: str,
        content: str,
        fact_ids: tuple[str, ...],
    ) -> ChatMessage:
        return self._repository.append_message(
            self._message_id_factory(),
            session.id,
            MessageRole.ASSISTANT,
            content,
            run_id,
            fact_ids,
        )

    def sessions(self, principal: AuthenticatedPrincipal) -> list[ChatSession]:
        return self._repository.list_sessions(principal.user_id)

    def questions(
        self, principal: AuthenticatedPrincipal, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[ChatQuestion], int]:
        return self._repository.list_user_questions(
            principal.user_id, limit=limit, offset=offset
        )

    def messages(self, principal: AuthenticatedPrincipal, session_id: str) -> list[ChatMessage]:
        session = self._repository.get_session(session_id)
        if session is None:
            raise NotFound("chat session not found")
        self._authorize(principal, session)
        return self._repository.list_messages(session_id)

    @staticmethod
    def _authorize(principal: AuthenticatedPrincipal, session: ChatSession) -> None:
        if principal.role is not Role.ADMIN and session.owner_id != principal.user_id:
            raise Forbidden("chat session belongs to another user")
