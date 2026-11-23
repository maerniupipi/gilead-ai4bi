"""Published knowledge, user candidates, and administrator review endpoints."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from functools import partial
from typing import Annotated, TypeVar

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import IntegrityError

from xiaoying_quick.api.dependencies import (
    CurrentPrincipal,
    DbSession,
    KnowledgeServiceDep,
    RunServiceDep,
    require_roles,
)
from xiaoying_quick.infrastructure.persistence.repositories.artifacts import (
    SqlAlchemyArtifactRepository,
)
from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal, Role
from xiaoying_quick.modules.knowledge.content_guard import (
    KnowledgeContentGuard,
    UnsafeKnowledgeContent,
)
from xiaoying_quick.modules.knowledge.contracts import (
    CandidateRequest,
    KnowledgeCandidate,
    KnowledgeEntry,
    KnowledgeScope,
    KnowledgeState,
    ReviewDecision,
    validate_validity_window,
)
from xiaoying_quick.modules.knowledge.service import (
    InvalidKnowledgeTransition,
    KnowledgeNotFound,
)
from xiaoying_quick.shared.errors import Conflict, NotFound, ValidationFailed
from xiaoying_quick.infrastructure.search.business_library import BusinessLibrary, index_published_document
from xiaoying_quick.modules.knowledge.library import MAX_MARKDOWN_BYTES, document_id, upload_name
from xiaoying_quick.modules.usage import UsageAttribution, bind_usage_attribution

router = APIRouter(tags=["knowledge"])
ReviewerPrincipal = Annotated[
    AuthenticatedPrincipal,
    Depends(require_roles(Role.ADMIN, Role.KNOWLEDGE_REVIEWER)),
]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CandidateBody(StrictRequest):
    scope: KnowledgeScope
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=8000)
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    domain_id: str | None = Field(default=None, max_length=64)
    source_run_id: str | None = Field(default=None, max_length=64)
    source_question: str | None = Field(default=None, max_length=10_000)
    applicability: str | None = Field(default=None, max_length=8_000)
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def validity_window_is_ordered(self) -> CandidateBody:
        validate_validity_window(self.valid_from, self.valid_until)
        return self


class ReviewBody(StrictRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    comment: str | None = Field(default=None, max_length=2000)
    edited_content: str | None = Field(default=None, max_length=MAX_MARKDOWN_BYTES)


class KnowledgeEntryResponse(BaseModel):
    id: str
    scope: KnowledgeScope
    domain_id: str | None
    title: str
    content: str
    version: int
    content_hash: str
    source_candidate_id: str | None
    state: KnowledgeState
    published_by: str
    published_at: datetime
    applicability: str | None
    valid_from: datetime | None
    valid_until: datetime | None


class CandidateResponse(BaseModel):
    id: str
    scope: KnowledgeScope
    domain_id: str | None
    title: str
    content: str
    rationale: str
    evidence_refs: list[str]
    source_run_id: str | None
    source_question: str | None
    clarification_question: str | None
    clarification_answer: str | None
    applicability: str | None
    valid_from: datetime | None
    valid_until: datetime | None
    source_user_id: str
    state: KnowledgeState
    created_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_comment: str | None
    published_conflicts: list[KnowledgeEntryResponse] = Field(default_factory=list)


class ReviewResultResponse(BaseModel):
    candidate: CandidateResponse | None = None
    published: KnowledgeEntryResponse | None = None


T = TypeVar("T")


def _translate(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except (KnowledgeNotFound, LookupError) as exc:
        raise NotFound("knowledge candidate not found") from exc
    except IntegrityError as exc:
        raise Conflict("knowledge request references an unavailable resource") from exc
    except (InvalidKnowledgeTransition, UnsafeKnowledgeContent, ValueError) as exc:
        raise ValidationFailed(str(exc)) from exc


def _candidate(
    value: KnowledgeCandidate,
    *,
    published_conflicts: list[KnowledgeEntry] | None = None,
) -> CandidateResponse:
    return CandidateResponse(
        id=value.id,
        scope=value.scope,
        domain_id=value.domain_id,
        title=value.title,
        content=value.content,
        rationale=value.rationale,
        evidence_refs=list(value.evidence_refs),
        source_run_id=value.source_run_id,
        source_question=value.source_question,
        clarification_question=value.clarification_question,
        clarification_answer=value.clarification_answer,
        applicability=value.applicability,
        valid_from=value.valid_from,
        valid_until=value.valid_until,
        source_user_id=value.source_user_id,
        state=value.state,
        created_at=value.created_at,
        reviewed_by=value.reviewed_by,
        reviewed_at=value.reviewed_at,
        review_comment=value.review_comment,
        published_conflicts=[_entry(entry) for entry in published_conflicts or ()],
    )


def _entry(value: KnowledgeEntry) -> KnowledgeEntryResponse:
    return KnowledgeEntryResponse(
        id=value.id,
        scope=value.scope,
        domain_id=value.domain_id,
        title=value.title,
        content=value.content,
        version=value.version,
        content_hash=value.content_hash,
        source_candidate_id=value.source_candidate_id,
        state=value.state,
        published_by=value.published_by,
        published_at=value.published_at,
        applicability=value.applicability,
        valid_from=value.valid_from,
        valid_until=value.valid_until,
    )


def _trusted_source_question(
    frame_payload: dict[str, object] | None,
    *,
    run_question: str,
) -> str:
    if frame_payload is not None:
        for key in ("raw_question", "standalone_question"):
            value = frame_payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return run_question


@router.get("/api/v2/knowledge/documents")
def list_documents(request: Request, database: DbSession, principal: CurrentPrincipal):
    documents = BusinessLibrary(database, request.app.state.settings).documents().values()
    return [doc.info() for doc in sorted(documents, key=lambda doc: (doc.reference, -doc.updated_at.timestamp(), doc.filename))]


@router.get("/api/v2/knowledge/search")
def search_documents(request: Request, database: DbSession, principal: CurrentPrincipal,
                     q: Annotated[str, Query(min_length=1, max_length=1000)],
                     limit: Annotated[int, Query(ge=1, le=20)] = 10):
    attribution = UsageAttribution(user_id=principal.user_id, username=principal.username,
                                   display_name=principal.display_name, question=q)
    with bind_usage_attribution(attribution):
        return BusinessLibrary(database, request.app.state.settings).search(q, limit, include_references=True)


@router.get("/api/v2/knowledge/documents/{doc_id}")
def read_document(doc_id: str, request: Request, database: DbSession, principal: CurrentPrincipal):
    document = BusinessLibrary(database, request.app.state.settings).documents().get(doc_id)
    if document is None:
        raise NotFound("找不到已发布的文档")
    return {**document.info(), "sections": [{"heading": heading, "content": content} for heading, content in document.sections]}


@router.post("/api/v2/knowledge/documents")
def upload_document(request: Request, background: BackgroundTasks, principal: CurrentPrincipal,
                    service: KnowledgeServiceDep, file: Annotated[UploadFile, File()]):
    name = _translate(lambda: upload_name(file.filename or ""))
    data = file.file.read(MAX_MARKDOWN_BYTES + 1)
    if len(data) > MAX_MARKDOWN_BYTES:
        raise ValidationFailed("Markdown 文件最大为 1 MiB")
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationFailed("请使用 UTF-8 编码的 Markdown 文件") from None
    candidate = _translate(lambda: service.propose(principal.user_id, CandidateRequest(
        scope=KnowledgeScope.BUSINESS, title=name, content=content, rationale="上传共享业务 Markdown 文档")))
    if not principal.has_role(Role.KNOWLEDGE_REVIEWER):
        return {"state": "pending_review", "candidate_id": candidate.id}
    entry = _translate(lambda: service.review(candidate_id=candidate.id, reviewer_id=principal.user_id,
                                               decision=ReviewDecision.APPROVE))
    doc_id = document_id(entry.scope, entry.domain_id, entry.title)
    background.add_task(index_published_document, request.app.state.session_factory, request.app.state.settings, doc_id)
    return {"state": "published", "document_id": doc_id, "version": entry.version}


@router.get("/api/v2/knowledge/published", response_model=list[KnowledgeEntryResponse])
def list_published_knowledge(
    principal: CurrentPrincipal,
    service: KnowledgeServiceDep,
    scope: Annotated[KnowledgeScope | None, Query()] = None,
    domain_id: Annotated[str | None, Query(max_length=64)] = None,
) -> list[KnowledgeEntryResponse]:
    del principal
    if scope is KnowledgeScope.PERSONAL:
        raise ValidationFailed("personal memory is not part of published knowledge")
    return [
        _entry(value)
        for value in _translate(lambda: service.published(scope=scope, domain_id=domain_id))
    ]


@router.get("/api/v2/knowledge/candidates", response_model=list[CandidateResponse])
def list_my_candidates(
    principal: CurrentPrincipal,
    service: KnowledgeServiceDep,
    state_filter: Annotated[KnowledgeState | None, Query(alias="state")] = None,
) -> list[CandidateResponse]:
    candidates = _translate(lambda: service.list_candidates(state_filter))
    return [_candidate(value) for value in candidates if value.source_user_id == principal.user_id]


@router.post(
    "/api/v2/knowledge/candidates",
    response_model=CandidateResponse,
    status_code=status.HTTP_201_CREATED,
)
def propose_candidate(
    body: CandidateBody,
    principal: CurrentPrincipal,
    service: KnowledgeServiceDep,
    run_service: RunServiceDep,
    database: DbSession,
) -> CandidateResponse:
    source_question = body.source_question
    if body.source_run_id:
        source_run = run_service.get_run(principal=principal, run_id=body.source_run_id)
        frame_payload = SqlAlchemyArtifactRepository(database).latest(
            run_id=body.source_run_id,
            kind="query_frame",
        )
        source_question = _trusted_source_question(
            frame_payload,
            run_question=source_run.question,
        )
    guard = KnowledgeContentGuard()
    safe_title = _translate(lambda: guard.validate(body.title))
    safe_rationale = _translate(lambda: guard.validate(body.rationale))
    safe_evidence_refs = tuple(
        _translate(partial(guard.validate, evidence_ref)) for evidence_ref in body.evidence_refs
    )
    value = _translate(
        lambda: service.propose(
            principal.user_id,
            CandidateRequest(
                scope=body.scope,
                title=safe_title,
                content=body.content,
                rationale=safe_rationale,
                evidence_refs=safe_evidence_refs,
                domain_id=body.domain_id,
                source_run_id=body.source_run_id,
                source_question=source_question,
                applicability=body.applicability,
                valid_from=body.valid_from,
                valid_until=body.valid_until,
            ),
        )
    )
    return _candidate(value)


@router.get(
    "/api/v2/admin/knowledge/reviews",
    response_model=list[CandidateResponse],
    tags=["knowledge-admin"],
)
def list_reviews(
    service: KnowledgeServiceDep,
    _reviewer: ReviewerPrincipal,
    state_filter: Annotated[
        KnowledgeState | None, Query(alias="state")
    ] = KnowledgeState.PENDING_REVIEW,
) -> list[CandidateResponse]:
    candidates = _translate(lambda: service.list_candidates(state_filter))
    return [
        _candidate(
            value,
            published_conflicts=_translate(partial(service.published_conflicts, value)),
        )
        for value in candidates
    ]


@router.post(
    "/api/v2/admin/knowledge/reviews/{candidate_id}/approve",
    response_model=ReviewResultResponse,
    tags=["knowledge-admin"],
)
def approve_candidate(
    candidate_id: str,
    body: ReviewBody,
    request: Request,
    background: BackgroundTasks,
    service: KnowledgeServiceDep,
    reviewer: ReviewerPrincipal,
) -> ReviewResultResponse:
    comment = body.comment
    if comment:
        _translate(lambda: KnowledgeContentGuard().validate(comment))
    value = _translate(
        lambda: service.review(
            candidate_id=candidate_id,
            reviewer_id=reviewer.user_id,
            decision=ReviewDecision.APPROVE,
            comment=body.comment,
            edited_content=body.edited_content,
        )
    )
    if isinstance(value, KnowledgeEntry):
        background.add_task(index_published_document, request.app.state.session_factory, request.app.state.settings,
                            document_id(value.scope, value.domain_id, value.title))
        return ReviewResultResponse(published=_entry(value))
    return ReviewResultResponse(candidate=_candidate(value))


@router.post(
    "/api/v2/admin/knowledge/reviews/{candidate_id}/reject",
    response_model=ReviewResultResponse,
    tags=["knowledge-admin"],
)
def reject_candidate(
    candidate_id: str,
    body: ReviewBody,
    service: KnowledgeServiceDep,
    reviewer: ReviewerPrincipal,
) -> ReviewResultResponse:
    comment = body.comment
    if comment:
        _translate(lambda: KnowledgeContentGuard().validate(comment))
    value = _translate(
        lambda: service.review(
            candidate_id=candidate_id,
            reviewer_id=reviewer.user_id,
            decision=ReviewDecision.REJECT,
            comment=body.comment,
        )
    )
    if isinstance(value, KnowledgeEntry):
        return ReviewResultResponse(published=_entry(value))
    return ReviewResultResponse(candidate=_candidate(value))
