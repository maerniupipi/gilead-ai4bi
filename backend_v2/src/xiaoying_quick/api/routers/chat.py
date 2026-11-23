from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Header, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...api.dependencies import CurrentPrincipal, DbSession, RunServiceDep, SecretStoreDep
from ...bootstrap.jobs import (
    dispatch_job,
    enqueue_quick_resume,
    enqueue_quick_start,
)
from ...infrastructure.persistence.repositories.chat import (
    SqlAlchemyChatRepository,
    SqlAlchemyClarificationRepository,
)
from ...infrastructure.persistence.repositories.runs import SqlAlchemyRunRepository
from ...modules.chat.contracts import ChatMessage, ChatQuestion, ChatSession
from ...modules.chat.service import ChatService
from ...modules.clarification import (
    ClarificationCase,
    ClarificationQueryService,
)
from ...modules.runs.contracts import RunMode, RunStatus
from ...modules.runs.service import RunService
from ...shared.errors import Conflict, ValidationFailed
from ...shared.ids import new_id
from .chatbots import get_chatbot_store
from .model_configs import get_model_service

router = APIRouter(prefix="/api/v2", tags=["quick-chat"])

ThinkingChoice = Literal["default", "on", "off"]
ThinkingLevel = Literal["low", "medium", "high"]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


ChatMode = Literal["normal", "insight"]


class ChatRequest(StrictRequest):
    question: str = Field(min_length=1, max_length=10_000)
    session_id: str | None = Field(default=None, max_length=64)
    model_config_id: str | None = Field(default=None, max_length=64)
    thinking: ThinkingChoice | None = None
    thinking_level: ThinkingLevel | None = None
    use_memory: bool = True
    mode: ChatMode = "normal"
    insight_custom_prompt: str | None = Field(default=None, max_length=20_000)
    insight_skill_pack_id: str | None = Field(default=None, max_length=64)
    report_context: dict[str, Any] | None = None
    chatbot_id: str = Field(default="ddi", min_length=1, max_length=64)

    @model_validator(mode="after")
    def bound_report_context(self) -> ChatRequest:
        if self.report_context and len(json.dumps(self.report_context)) > 8000:
            raise ValueError("report_context is too large")
        return self


class ChatAcceptedResponse(BaseModel):
    run_id: str
    session_id: str
    status: RunStatus
    created: bool
    events_url: str


class SessionResponse(BaseModel):
    id: str
    title: str
    version: int
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    id: str
    session_id: str
    run_id: str | None
    role: str
    content: str
    fact_ids: list[str]
    created_at: datetime


class QuestionResponse(BaseModel):
    id: str
    session_id: str
    session_title: str
    content: str
    run_id: str | None
    created_at: datetime


class QuestionPageResponse(BaseModel):
    items: list[QuestionResponse]
    total: int
    limit: int
    offset: int


class ClarificationAnswerRequest(StrictRequest):
    question_id: str = Field(min_length=1, max_length=128)
    choice_id: str | None = Field(default=None, max_length=128)
    choice_ids: list[str] = Field(default_factory=list, max_length=8)
    free_text: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def at_least_one_answer_form(self) -> ClarificationAnswerRequest:
        has_choice = bool(self.choice_id) or bool(self.choice_ids)
        has_free_text = bool(self.free_text)
        if not has_choice and not has_free_text:
            raise ValueError("需要 choice_id、choice_ids 或 free_text")
        return self


class ClarificationSubmitRequest(StrictRequest):
    answers: list[ClarificationAnswerRequest] = Field(min_length=1, max_length=12)
    # The resume keeps running with the same model/thinking choice the user
    # made when asking the question.
    model_config_id: str | None = Field(default=None, max_length=64)
    thinking: ThinkingChoice | None = None
    thinking_level: ThinkingLevel | None = None
    use_memory: bool | None = None


class ModelChoiceResponse(BaseModel):
    id: str
    name: str
    model_id: str
    is_active: bool


class ClarificationSubmitResponse(BaseModel):
    run_id: str
    session_id: str
    status: str = "resuming"
    candidate_ids: list[str]


class ClarificationChoiceResponse(BaseModel):
    id: str
    label: str
    explanation: str | None
    recommended: bool = False
    source: str | None = None


class ClarificationGroupResponse(BaseModel):
    question_id: str
    prompt: str
    why: str = ""
    required: bool
    allow_free_text: bool
    multi_select: bool = False
    choices: list[ClarificationChoiceResponse]


class WaitingClarificationResponse(BaseModel):
    case_id: str
    run_id: str
    session_id: str
    groups: list[ClarificationGroupResponse]
    created_at: datetime
    events_url: str
    last_event_cursor: int


@router.post("/chat", response_model=ChatAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
def create_chat_run(
    body: ChatRequest,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    principal: CurrentPrincipal,
    database: DbSession,
    runs: RunServiceDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ChatAcceptedResponse:
    bot_store = get_chatbot_store(request)
    bot = bot_store.require(body.chatbot_id, principal)
    repository = SqlAlchemyChatRepository(database)
    if body.session_id and repository.session_chatbot_id(body.session_id) != bot["id"]:
        raise Conflict("此会话属于另一个 Chatbot，请切换助手或新建对话")
    stored_key = _chat_idempotency_key(idempotency_key)
    existing = runs.find_idempotent(
        principal=principal,
        idempotency_key=stored_key,
    )
    if existing is not None:
        clean_question = body.question.strip()
        clean_session_id = body.session_id.strip() if body.session_id else None
        if existing.question != clean_question:
            raise Conflict("Idempotency-Key was already used with a different request")
        if clean_session_id is not None and existing.session_id != clean_session_id:
            raise Conflict("Idempotency-Key was already used with a different request")
        if existing.session_id is None:
            raise Conflict("Idempotency-Key belongs to an incompatible request")
        if repository.session_chatbot_id(existing.session_id) != bot["id"]:
            raise Conflict("Idempotency-Key belongs to a different Chatbot")
        response.status_code = status.HTTP_200_OK
        return ChatAcceptedResponse(
            run_id=existing.id,
            session_id=existing.session_id,
            status=existing.status,
            created=False,
            events_url=f"/api/v2/runs/{existing.id}/stream",
        )

    from xiaoying_quick.infrastructure.monthly_quota import balance
    from fastapi import HTTPException
    if balance(database, principal.user_id)["remaining"] <= 0:
        raise HTTPException(429, "本月 Token 额度已用完，请联系管理员或等待下月刷新")
    personal_books = None
    if bot.get("personal_uploads"):
        personal_books = bot_store.personal_workbooks(bot["id"], principal.user_id)
        if not personal_books:
            raise ValidationFailed("请先上传至少一个 XLSX 文件，再开始问数")
    chats = ChatService(
        SqlAlchemyChatRepository(database),
        lambda: new_id("session"),
        lambda: new_id("message"),
    )
    session = chats.get_or_create_session(principal, body.session_id, body.question)
    run_mode = RunMode.NORMAL
    insight_meta: dict[str, object] = {}
    if bot["id"] != "ddi":
        insight_meta["chatbot_id"] = bot["id"]
    if personal_books is not None:
        insight_meta["workbook_ids"] = [book["id"] for book in personal_books]
    if body.report_context:
        insight_meta["report_context"] = body.report_context
    if body.insight_skill_pack_id:
        insight_meta["skill_pack_id"] = body.insight_skill_pack_id
    if body.insight_custom_prompt:
        insight_meta["custom_prompt"] = body.insight_custom_prompt
    result = runs.create_run(
        principal=principal,
        question=body.question,
        session_id=session.id,
        idempotency_key=stored_key,
        mode=run_mode,
        insight_meta=insight_meta or None,
    )
    if result.created:
        chats.append_user_message(session, result.run.id, body.question)
        job = enqueue_quick_start(
            app=request.app,
            database=database,
            principal=principal,
            run_id=result.run.id,
            session_id=session.id,
            question=body.question,
            model_config_id=body.model_config_id,
            thinking=body.thinking,
            thinking_level=body.thinking_level,
            use_memory=None if body.use_memory and bot["id"] == "ddi" else False,
            mode=run_mode.value if run_mode is RunMode.INSIGHT else None,
            insight_custom_prompt=(
                body.insight_custom_prompt
            ),
            insight_skill_pack_id=(
                body.insight_skill_pack_id
            ),
        )
        runs.append_event(
            run_id=result.run.id,
            event_type="job.enqueued",
            payload={"job_id": job.id, "kind": job.kind.value},
        )
        dispatch_job(request.app, job.id, background)
    else:
        response.status_code = status.HTTP_200_OK
    return ChatAcceptedResponse(
        run_id=result.run.id,
        session_id=session.id,
        status=result.run.status,
        created=result.created,
        events_url=f"/api/v2/runs/{result.run.id}/stream",
    )


@router.get("/chat/models", response_model=list[ModelChoiceResponse])
def list_model_choices(
    principal: CurrentPrincipal,
    database: DbSession,
    secrets: SecretStoreDep,
) -> list[ModelChoiceResponse]:
    """Model picker options for the composer (no secrets, any signed-in user)."""

    del principal
    service = get_model_service(database, secrets)
    return [
        ModelChoiceResponse(
            id=record.id,
            name=record.name,
            model_id=record.model_id,
            is_active=record.is_active,
        )
        for record in service.list_configs()
    ]


@router.get("/chat/sessions", response_model=list[SessionResponse])
def list_chat_sessions(
    request: Request, principal: CurrentPrincipal, database: DbSession,
    chatbot_id: str = "ddi",
) -> list[SessionResponse]:
    get_chatbot_store(request).require(chatbot_id, principal)
    repository = SqlAlchemyChatRepository(database)
    return [_session(value) for value in repository.list_sessions(
        principal.user_id, chatbot_id=chatbot_id,
    )]


@router.get("/chat/questions", response_model=QuestionPageResponse)
def list_chat_questions(
    request: Request,
    principal: CurrentPrincipal,
    database: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    chatbot_id: str = "ddi",
) -> QuestionPageResponse:
    get_chatbot_store(request).require(chatbot_id, principal)
    items, total = SqlAlchemyChatRepository(database).list_user_questions(
        principal.user_id, limit=limit, offset=offset, chatbot_id=chatbot_id,
    )
    return QuestionPageResponse(
        items=[_question(value) for value in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/chat/sessions/{session_id}/messages", response_model=list[MessageResponse])
def list_chat_messages(
    session_id: str,
    request: Request,
    principal: CurrentPrincipal,
    database: DbSession,
) -> list[MessageResponse]:
    get_chatbot_store(request).require(
        SqlAlchemyChatRepository(database).session_chatbot_id(session_id), principal,
    )
    service = ChatService(
        SqlAlchemyChatRepository(database),
        lambda: new_id("session"),
        lambda: new_id("message"),
    )
    return [_message(value) for value in service.messages(principal, session_id)]


@router.get("/clarifications/waiting", response_model=list[WaitingClarificationResponse])
def list_waiting_clarifications(
    principal: CurrentPrincipal,
    database: DbSession,
    runs: RunServiceDep,
    run_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    session_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
) -> list[WaitingClarificationResponse]:
    service = ClarificationQueryService(SqlAlchemyClarificationRepository(database))
    cases = service.list_waiting(
        principal=principal,
        run_id=run_id,
        session_id=session_id,
    )
    return [
        _waiting_clarification(
            value,
            last_event_cursor=runs.get_run(
                principal=principal,
                run_id=value.run_id,
            ).next_event_cursor,
        )
        for value in cases
    ]


@router.post(
    "/clarifications/{case_id}/answers",
    response_model=ClarificationSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_clarification(
    case_id: str,
    body: ClarificationSubmitRequest,
    request: Request,
    background: BackgroundTasks,
    principal: CurrentPrincipal,
    database: DbSession,
) -> ClarificationSubmitResponse:
    cases = SqlAlchemyClarificationRepository(database)
    case = cases.get(case_id)
    if case is None or case.status.value != "waiting":
        raise ValidationFailed("澄清不存在或已处理")
    answer, answers = _answer_projection(case, body)
    if not answer:
        raise ValidationFailed("澄清答案无效")
    job = enqueue_quick_resume(
        app=request.app,
        database=database,
        principal=principal,
        run_id=case.run_id,
        session_id=case.session_id,
        case_id=case_id,
        answer=answer,
        answers=answers,
        model_config_id=body.model_config_id,
        thinking=body.thinking,
        thinking_level=body.thinking_level,
        use_memory=body.use_memory,
    )
    RunService(SqlAlchemyRunRepository(database)).append_event(
        run_id=case.run_id,
        event_type="job.enqueued",
        payload={"job_id": job.id, "kind": job.kind.value},
    )
    dispatch_job(request.app, job.id, background)
    return ClarificationSubmitResponse(
        run_id=case.run_id,
        session_id=case.session_id,
        candidate_ids=[],
    )


def _answer_projection(
    case: ClarificationCase, body: ClarificationSubmitRequest
) -> tuple[str, tuple[dict[str, str], ...]]:
    """Project structured answers into prose plus a per-question mapping."""

    lines: list[str] = []
    answers: list[dict[str, str]] = []
    for item in body.answers:
        if item.free_text and item.free_text.strip():
            text = item.free_text.strip()
        else:
            question = next(
                (value for value in case.questions if value.question_id == item.question_id),
                None,
            )
            if question is None and len(case.questions) == 1:
                # The live ask_user event carries no question ids; fall back.
                question = case.questions[0]
            if question is None:
                continue
            chosen_ids = set(item.choice_ids or ())
            if item.choice_id:
                chosen_ids.add(item.choice_id)
            labels = [
                choice.label
                for choice in question.choices
                if (choice.choice_id in chosen_ids or choice.label in chosen_ids) and choice.label
            ]
            if not labels:
                continue
            text = "、".join(labels)
        question = next(
            (value for value in case.questions if value.question_id == item.question_id),
            case.questions[0] if len(case.questions) == 1 else None,
        )
        question_id = question.question_id if question is not None else item.question_id
        prompt = question.prompt if question is not None else ""
        if prompt:
            lines.append(f"问：{prompt}\n答：{text}")
        else:
            lines.append(text)
        answers.append({"question_id": question_id, "text": text})
    return "\n".join(lines)[:2_000], tuple(answers)


def _session(value: ChatSession) -> SessionResponse:
    return SessionResponse(
        id=value.id,
        title=value.title,
        version=value.version,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _message(value: ChatMessage) -> MessageResponse:
    return MessageResponse(
        id=value.id,
        session_id=value.session_id,
        run_id=value.run_id,
        role=value.role.value,
        content=value.content,
        fact_ids=list(value.fact_ids),
        created_at=value.created_at,
    )


def _question(value: ChatQuestion) -> QuestionResponse:
    return QuestionResponse(
        id=value.id,
        session_id=value.session_id,
        session_title=value.session_title,
        content=value.content,
        run_id=value.run_id,
        created_at=value.created_at,
    )


def _waiting_clarification(
    value: ClarificationCase,
    *,
    last_event_cursor: int,
) -> WaitingClarificationResponse:
    return WaitingClarificationResponse(
        case_id=value.case_id,
        run_id=value.run_id,
        session_id=value.session_id,
        groups=[
            ClarificationGroupResponse(
                question_id=question.question_id,
                prompt=question.prompt,
                why=question.why,
                required=question.required,
                allow_free_text=question.allow_free_text,
                multi_select=question.multi_select,
                choices=[
                    ClarificationChoiceResponse(
                        id=choice.choice_id,
                        label=choice.label,
                        explanation=choice.explanation,
                        recommended=choice.recommended,
                        source=choice.source or None,
                    )
                    for choice in question.choices
                ],
            )
            for question in value.questions
        ],
        created_at=value.created_at,
        events_url=f"/api/v2/runs/{value.run_id}/stream",
        last_event_cursor=last_event_cursor,
    )


def _chat_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    if not clean:
        return None
    # The storage column is 128 characters and the namespace prevents a key
    # used on the low-level /runs endpoint from colliding with /chat.
    if len(clean) > 123 or any(ord(character) < 32 for character in clean):
        raise ValidationFailed("Idempotency-Key is invalid")
    return f"chat:{clean}"
