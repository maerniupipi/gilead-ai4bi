from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....modules.chat.contracts import ChatMessage, ChatQuestion, ChatSession, MessageRole
from ....modules.clarification.contracts import (
    ClarificationCase,
    ClarificationStatus,
)
from ..models.chat import (
    ChatMessageModel,
    ChatSessionModel,
    ClarificationCaseModel,
)
from ..models.runs import RunModel


class SqlAlchemyChatRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_session(self, session_id: str) -> ChatSession | None:
        row = self._session.get(ChatSessionModel, session_id)
        return self._session_record(row) if row else None

    def create_session(self, session_id: str, owner_id: str, title: str) -> ChatSession:
        row = ChatSessionModel(id=session_id, owner_id=owner_id, title=title, version=1)
        self._session.add(row)
        self._session.flush()
        return self._session_record(row)

    def session_chatbot_id(self, session_id: str) -> str:
        meta = self._session.scalar(
            select(RunModel.insight_meta).where(RunModel.session_id == session_id)
            .order_by(RunModel.created_at, RunModel.id).limit(1)
        )
        return str((meta or {}).get("chatbot_id") or "ddi")

    @staticmethod
    def _chatbot_filter(chatbot_id: str):
        other = select(RunModel.id).where(
            RunModel.session_id == ChatSessionModel.id,
            func.coalesce(RunModel.insight_meta["chatbot_id"].as_string(), "ddi") != "ddi",
        ).exists()
        if chatbot_id == "ddi":
            return ~other
        return select(RunModel.id).where(
            RunModel.session_id == ChatSessionModel.id,
            RunModel.insight_meta["chatbot_id"].as_string() == chatbot_id,
        ).exists()

    def list_sessions(
        self, owner_id: str, limit: int = 50, *, chatbot_id: str | None = None,
    ) -> list[ChatSession]:
        filters = [ChatSessionModel.owner_id == owner_id]
        if chatbot_id:
            filters.append(self._chatbot_filter(chatbot_id))
        rows = self._session.scalars(
            select(ChatSessionModel)
            .where(*filters)
            .order_by(ChatSessionModel.updated_at.desc())
            .limit(limit)
        ).all()
        return [self._session_record(row) for row in rows]

    def list_user_questions(
        self, owner_id: str, *, limit: int = 20, offset: int = 0,
        chatbot_id: str | None = None,
    ) -> tuple[list[ChatQuestion], int]:
        filters = [
            ChatSessionModel.owner_id == owner_id,
            ChatMessageModel.role == MessageRole.USER.value,
        ]
        if chatbot_id:
            filters.append(self._chatbot_filter(chatbot_id))
        total = self._session.scalar(
            select(func.count(ChatMessageModel.id))
            .join(ChatSessionModel, ChatSessionModel.id == ChatMessageModel.session_id)
            .where(*filters)
        ) or 0
        rows = self._session.execute(
            select(ChatMessageModel, ChatSessionModel.title)
            .join(ChatSessionModel, ChatSessionModel.id == ChatMessageModel.session_id)
            .where(*filters)
            .order_by(ChatMessageModel.created_at.desc(), ChatMessageModel.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [self._question(message, title) for message, title in rows], int(total)

    def append_message(
        self,
        message_id: str,
        session_id: str,
        role: MessageRole,
        content: str,
        run_id: str | None = None,
        fact_ids: tuple[str, ...] = (),
    ) -> ChatMessage:
        row = ChatMessageModel(
            id=message_id,
            session_id=session_id,
            run_id=run_id,
            role=role.value,
            content=content,
            fact_ids=list(fact_ids),
        )
        self._session.add(row)
        session = self._session.get(ChatSessionModel, session_id)
        if session is not None:
            session.updated_at = datetime.now(timezone.utc)
            session.version += 1
        self._session.flush()
        return self._message(row)

    def list_messages(self, session_id: str) -> list[ChatMessage]:
        rows = self._session.scalars(
            select(ChatMessageModel)
            .where(ChatMessageModel.session_id == session_id)
            .order_by(ChatMessageModel.created_at)
        ).all()
        return [self._message(row) for row in rows]

    @staticmethod
    def _session_record(row: ChatSessionModel) -> ChatSession:
        return ChatSession(
            id=row.id,
            owner_id=row.owner_id,
            title=row.title,
            version=row.version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _message(row: ChatMessageModel) -> ChatMessage:
        return ChatMessage(
            id=row.id,
            session_id=row.session_id,
            run_id=row.run_id,
            role=MessageRole(row.role),
            content=row.content,
            fact_ids=tuple(row.fact_ids),
            created_at=row.created_at,
        )

    @staticmethod
    def _question(row: ChatMessageModel, session_title: str) -> ChatQuestion:
        return ChatQuestion(
            id=row.id,
            session_id=row.session_id,
            session_title=session_title,
            content=row.content,
            run_id=row.run_id,
            created_at=row.created_at,
        )


class SqlAlchemyClarificationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, case_id: str) -> ClarificationCase | None:
        row = self._session.get(ClarificationCaseModel, case_id)
        return self._case(row) if row else None

    def for_run(self, run_id: str) -> ClarificationCase | None:
        row = self._session.scalar(
            select(ClarificationCaseModel)
            .where(ClarificationCaseModel.run_id == run_id)
            .order_by(ClarificationCaseModel.revision.desc())
        )
        return self._case(row) if row else None

    def list_answered_for_session(
        self, session_id: str, *, limit: int = 8, workbook_ids: Sequence[str] | None = None
    ) -> list[ClarificationCase]:
        """Answered cases of a session, newest first — the confirmed scopes."""

        statement = (
            select(ClarificationCaseModel, RunModel.insight_meta)
            .join(RunModel, RunModel.id == ClarificationCaseModel.run_id)
            .where(
                ClarificationCaseModel.session_id == session_id,
                ClarificationCaseModel.status == ClarificationStatus.ANSWERED.value,
            )
            .order_by(ClarificationCaseModel.created_at.desc(), ClarificationCaseModel.id.desc())
        )
        if workbook_ids is None:
            statement = statement.limit(limit)
        cases = []
        for row, meta in self._session.execute(statement):
            if (
                workbook_ids is not None
                and set((meta or {}).get("workbook_ids") or []) != set(workbook_ids)
            ):
                continue
            cases.append(self._case(row))
            if len(cases) >= limit:
                break
        return cases

    def list_waiting(
        self,
        *,
        owner_user_id: str,
        run_id: str | None = None,
        session_id: str | None = None,
    ) -> list[ClarificationCase]:
        statement = (
            select(ClarificationCaseModel)
            .join(RunModel, RunModel.id == ClarificationCaseModel.run_id)
            .join(ChatSessionModel, ChatSessionModel.id == ClarificationCaseModel.session_id)
            .where(
                ClarificationCaseModel.status == ClarificationStatus.WAITING.value,
                RunModel.owner_user_id == owner_user_id,
                ChatSessionModel.owner_id == owner_user_id,
            )
        )
        if run_id is not None:
            statement = statement.where(ClarificationCaseModel.run_id == run_id)
        if session_id is not None:
            statement = statement.where(ClarificationCaseModel.session_id == session_id)
        rows = self._session.scalars(
            statement.order_by(ClarificationCaseModel.created_at, ClarificationCaseModel.id)
        ).all()
        return [self._case(row) for row in rows]

    def save(self, case: ClarificationCase) -> None:
        row = self._session.get(ClarificationCaseModel, case.case_id)
        if row is None:
            row = ClarificationCaseModel(
                id=case.case_id,
                run_id=case.run_id,
                session_id=case.session_id,
                frame_id=case.frame_id,
                topic_id=case.topic_id,
                revision=case.version,
                status=case.status.value,
                payload=case.to_record(),
                created_at=case.created_at,
                answered_at=case.answered_at,
            )
            self._session.add(row)
        else:
            row.revision = case.version
            row.status = case.status.value
            row.payload = case.to_record()
            row.topic_id = case.topic_id
            row.answered_at = case.answered_at
        self._session.flush()

    @staticmethod
    def _case(row: ClarificationCaseModel) -> ClarificationCase:
        return ClarificationCase.from_record({**row.payload, "topic_id": row.topic_id})
