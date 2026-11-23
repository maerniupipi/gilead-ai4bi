"""Answer feedback: user submit + admin ops board."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select

from xiaoying_quick.api.dependencies import CurrentPrincipal, DbSession, require_roles
from xiaoying_quick.infrastructure.persistence.base import utc_now
from xiaoying_quick.infrastructure.persistence.models.feedback import AnswerFeedbackModel
from xiaoying_quick.infrastructure.persistence.models.runs import RunModel
from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal, Role
from xiaoying_quick.shared.errors import NotFound, ValidationFailed
from xiaoying_quick.shared.ids import new_id

router = APIRouter(tags=["feedback"])
AdminPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_roles(Role.ADMIN))]

Rating = Literal["up", "down"]


class FeedbackSubmitRequest(BaseModel):
    run_id: str = Field(min_length=1, max_length=64)
    rating: Rating
    question: str = Field(default="", max_length=4000)
    session_id: str | None = Field(default=None, max_length=128)
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackItem(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    user_id: str
    username: str
    display_name: str
    run_id: str
    session_id: str | None = None
    question: str = ""
    rating: str
    comment: str | None = None


class FeedbackListResponse(BaseModel):
    items: list[FeedbackItem]
    total: int = 0
    up_count: int = 0
    down_count: int = 0


def _to_item(row: AnswerFeedbackModel) -> FeedbackItem:
    return FeedbackItem(
        id=row.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        user_id=row.user_id,
        username=row.username,
        display_name=row.display_name,
        run_id=row.run_id,
        session_id=row.session_id,
        question=row.question or "",
        rating=row.rating,
        comment=row.comment,
    )


def _resolve_question(
    session: DbSession,
    *,
    run_id: str,
    provided: str,
) -> str:
    text = (provided or "").strip()
    if text:
        return text[:4000]
    run = session.get(RunModel, run_id)
    if run and run.question:
        return str(run.question)[:4000]
    return ""


@router.post("/api/v2/feedback", response_model=FeedbackItem)
def submit_feedback(
    body: FeedbackSubmitRequest,
    session: DbSession,
    principal: CurrentPrincipal,
) -> FeedbackItem:
    run_id = body.run_id.strip()
    if not run_id:
        raise ValidationFailed("run_id is required")
    run = session.get(RunModel, run_id)
    if run is None:
        raise NotFound(f"run not found: {run_id}")
    if run.owner_user_id != principal.user_id and not principal.has_role(Role.ADMIN):
        raise NotFound(f"run not found: {run_id}")

    question = _resolve_question(session, run_id=run_id, provided=body.question)
    if not question and run.question:
        question = str(run.question)[:4000]

    existing = session.scalar(
        select(AnswerFeedbackModel).where(
            AnswerFeedbackModel.run_id == run_id,
            AnswerFeedbackModel.user_id == principal.user_id,
        )
    )
    now = utc_now()
    if existing:
        existing.rating = body.rating
        existing.question = question or existing.question
        existing.session_id = body.session_id or existing.session_id or run.session_id
        existing.comment = (body.comment or None)
        existing.username = (principal.username or "")[:64]
        existing.display_name = (principal.display_name or principal.username or "")[:128]
        existing.updated_at = now
        session.commit()
        session.refresh(existing)
        return _to_item(existing)

    row = AnswerFeedbackModel(
        id=new_id("fb"),
        user_id=principal.user_id,
        username=(principal.username or "")[:64],
        display_name=(principal.display_name or principal.username or "")[:128],
        run_id=run_id,
        session_id=body.session_id or run.session_id,
        question=question,
        rating=body.rating,
        comment=(body.comment or None),
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_item(row)


@router.get("/api/v2/feedback/{run_id}", response_model=FeedbackItem | None)
def get_my_feedback(
    run_id: str,
    session: DbSession,
    principal: CurrentPrincipal,
) -> FeedbackItem | None:
    row = session.scalar(
        select(AnswerFeedbackModel).where(
            AnswerFeedbackModel.run_id == run_id.strip(),
            AnswerFeedbackModel.user_id == principal.user_id,
        )
    )
    return _to_item(row) if row else None


def _admin_filters(
    statement: Select[Any],
    *,
    username: str | None,
    run_id: str | None,
    rating: str | None,
    since: datetime | None,
    until: datetime | None,
) -> Select[Any]:
    if username:
        statement = statement.where(AnswerFeedbackModel.username == username)
    if run_id:
        statement = statement.where(AnswerFeedbackModel.run_id == run_id)
    if rating:
        statement = statement.where(AnswerFeedbackModel.rating == rating)
    if since:
        statement = statement.where(AnswerFeedbackModel.created_at >= since)
    if until:
        statement = statement.where(AnswerFeedbackModel.created_at <= until)
    return statement


@router.get("/api/v2/admin/feedback", response_model=FeedbackListResponse)
def list_feedback(
    session: DbSession,
    _admin: AdminPrincipal,
    username: Annotated[str | None, Query(max_length=64)] = None,
    run_id: Annotated[str | None, Query(max_length=64)] = None,
    rating: Annotated[str | None, Query(pattern="^(up|down)$")] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FeedbackListResponse:
    filter_kwargs = dict(
        username=username,
        run_id=run_id,
        rating=rating,
        since=since,
        until=until,
    )
    base = _admin_filters(select(AnswerFeedbackModel), **filter_kwargs)
    total = int(
        session.scalar(select(func.count()).select_from(base.subquery())) or 0
    )
    # Stats ignore the rating filter so the summary cards stay comparable.
    stats_kwargs = {**filter_kwargs, "rating": None}
    up_base = _admin_filters(
        select(AnswerFeedbackModel).where(AnswerFeedbackModel.rating == "up"),
        **stats_kwargs,
    )
    down_base = _admin_filters(
        select(AnswerFeedbackModel).where(AnswerFeedbackModel.rating == "down"),
        **stats_kwargs,
    )
    up_count = int(
        session.scalar(select(func.count()).select_from(up_base.subquery())) or 0
    )
    down_count = int(
        session.scalar(select(func.count()).select_from(down_base.subquery())) or 0
    )
    rows = session.scalars(
        base.order_by(AnswerFeedbackModel.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return FeedbackListResponse(
        items=[_to_item(row) for row in rows],
        total=total,
        up_count=up_count,
        down_count=down_count,
    )
