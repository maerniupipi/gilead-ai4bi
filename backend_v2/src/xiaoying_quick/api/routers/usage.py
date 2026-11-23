"""Administrator token-consumption ledger APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, or_, select

from xiaoying_quick.api.dependencies import DbSession, require_roles
from xiaoying_quick.infrastructure.persistence.models.runs import RunModel
from xiaoying_quick.infrastructure.persistence.models.usage import UsageEventModel
from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal, Role

router = APIRouter(prefix="/api/v2/admin/usage", tags=["usage-admin"])
AdminPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_roles(Role.ADMIN))]


personal_router = APIRouter(prefix="/api/v2/usage", tags=["quota"])
from xiaoying_quick.api.dependencies import CurrentPrincipal
from xiaoying_quick.infrastructure.monthly_quota import balance, lock_user
from xiaoying_quick.infrastructure.persistence.models.identity import IdentityUserModel
from xiaoying_quick.infrastructure.persistence.models.usage import QuotaResetModel
from fastapi import HTTPException


@personal_router.get("/me")
def my_quota(session: DbSession, principal: CurrentPrincipal):
    return balance(session, principal.user_id)


@router.get("/quotas")
def all_quotas(session: DbSession, _admin: AdminPrincipal):
    users = session.scalars(select(IdentityUserModel).order_by(IdentityUserModel.username)).all()
    return [{"username":u.username, "display_name":u.display_name, **balance(session, u.id)} for u in users]


@router.post("/quotas/{user_id}/reset")
def reset_quota(user_id: str, session: DbSession, admin: AdminPrincipal):
    if not lock_user(session, user_id):
        raise HTTPException(404, "账号不存在")
    state = balance(session, user_id)
    if not state["exhausted"]:
        raise HTTPException(409, "账号本月仍有可用额度")
    from xiaoying_quick.infrastructure.monthly_quota import exhausted_id
    from xiaoying_quick.infrastructure.persistence.models.usage import QuotaHoldModel
    marker = session.get(QuotaHoldModel, exhausted_id(user_id,state["period"]))
    if marker:
        session.delete(marker)
    row = session.get(QuotaResetModel, (user_id,state["period"]))
    if not row:
        row = QuotaResetModel(user_id=user_id, period=state["period"], baseline=0)
        session.add(row)
    from datetime import timezone
    row.baseline += state["used"]
    row.actor_id = admin.user_id
    row.updated_at = datetime.now(timezone.utc)
    session.flush()
    return balance(session, user_id)


class UsageEventResponse(BaseModel):
    id: str
    created_at: datetime
    user_id: str
    username: str
    display_name: str
    run_id: str | None = None
    session_id: str | None = None
    mode: str
    purpose: str = ""
    question: str = ""
    model_id: str
    request_id: str = ""
    status: str = "ok"
    error_code: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int
    event_count: int = 1
    note: str | None = None


class UsageSummaryRow(BaseModel):
    user_id: str
    username: str
    display_name: str
    event_count: int
    total_tokens: int


class UsageListResponse(BaseModel):
    items: list[UsageEventResponse]
    total: int = Field(description="Matching row count (before pagination)")
    sum_total_tokens: int = 0
    group_by: str = "run"


class UsageTrendPoint(BaseModel):
    bucket: str
    total_tokens: int
    event_count: int


class UsageTrendResponse(BaseModel):
    points: list[UsageTrendPoint]
    sum_total_tokens: int = 0
    event_count: int = 0


def _filters(
    statement: Select[Any],
    *,
    user_id: str | None,
    username: str | None,
    purpose: str | None,
    mode: str | None,
    run_id: str | None,
    model_id: str | None,
    status: str | None,
    since: datetime | None,
    until: datetime | None,
) -> Select[Any]:
    if user_id:
        statement = statement.where(UsageEventModel.user_id == user_id)
    if username:
        statement = statement.where(UsageEventModel.username == username)
    if purpose:
        statement = statement.where(UsageEventModel.purpose.like(f"{purpose}%"))
    if mode:
        statement = statement.where(UsageEventModel.mode == mode)
    if run_id:
        # Match the bill run itself or any insight child attributed under it.
        child_ids = select(RunModel.id).where(RunModel.parent_run_id == run_id)
        statement = statement.where(
            or_(UsageEventModel.run_id == run_id, UsageEventModel.run_id.in_(child_ids))
        )
    if model_id:
        statement = statement.where(UsageEventModel.model_id == model_id)
    if status:
        statement = statement.where(UsageEventModel.status == status)
    if since:
        statement = statement.where(UsageEventModel.created_at >= since)
    if until:
        statement = statement.where(UsageEventModel.created_at <= until)
    return statement


@router.get("/events", response_model=UsageListResponse)
def list_usage_events(
    session: DbSession,
    _admin: AdminPrincipal,
    user_id: Annotated[str | None, Query(max_length=64)] = None,
    username: Annotated[str | None, Query(max_length=64)] = None,
    purpose: Annotated[str | None, Query(max_length=96)] = None,
    mode: Annotated[str | None, Query(max_length=16)] = None,
    run_id: Annotated[str | None, Query(max_length=64)] = None,
    model_id: Annotated[str | None, Query(max_length=128)] = None,
    status: Annotated[str | None, Query(max_length=16)] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    group_by: Annotated[str, Query(pattern="^(run|event)$")] = "run",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UsageListResponse:
    """List usage rows.

    Default ``group_by=run`` collapses one user question (one run) into a single
    row with summed tokens — admin UI shows questions, not every LLM step.
    """

    filt = dict(
        user_id=user_id,
        username=username,
        purpose=purpose,
        mode=mode,
        run_id=run_id,
        model_id=model_id,
        status=status,
        since=since,
        until=until,
    )
    sum_tokens = int(
        session.scalar(
            _filters(
                select(func.coalesce(func.sum(UsageEventModel.total_tokens), 0)),
                **filt,
            )
        )
        or 0
    )
    if group_by == "event":
        total = int(
            session.scalar(
                _filters(select(func.count()).select_from(UsageEventModel), **filt)
            )
            or 0
        )
        rows = session.scalars(
            _filters(select(UsageEventModel), **filt)
            .order_by(UsageEventModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return UsageListResponse(
            items=[
                UsageEventResponse(
                    id=row.id,
                    created_at=row.created_at,
                    user_id=row.user_id,
                    username=row.username,
                    display_name=row.display_name,
                    run_id=row.run_id,
                    session_id=row.session_id,
                    mode=row.mode,
                    purpose=row.purpose,
                    question=getattr(row, "question", "") or "",
                    model_id=row.model_id,
                    request_id=row.request_id,
                    status=row.status,
                    error_code=row.error_code,
                    prompt_tokens=row.prompt_tokens,
                    completion_tokens=row.completion_tokens,
                    reasoning_tokens=row.reasoning_tokens,
                    total_tokens=row.total_tokens,
                    event_count=1,
                    note=row.note,
                )
                for row in rows
            ],
            total=int(total),
            sum_total_tokens=int(sum_tokens),
            group_by="event",
        )

    # One row per user question. Insight child runs roll up to parent_run_id
    # (also repairs historical rows that stored the child id).
    bill_run_id = func.coalesce(
        RunModel.parent_run_id, UsageEventModel.run_id, UsageEventModel.id
    )
    grouped = (
        _filters(
            select(
                bill_run_id.label("run_key"),
                func.max(UsageEventModel.created_at).label("created_at"),
                func.max(UsageEventModel.user_id).label("user_id"),
                func.max(UsageEventModel.username).label("username"),
                func.max(UsageEventModel.display_name).label("display_name"),
                bill_run_id.label("run_id"),
                func.max(UsageEventModel.session_id).label("session_id"),
                func.max(UsageEventModel.mode).label("mode"),
                func.max(UsageEventModel.question).label("question"),
                func.max(UsageEventModel.model_id).label("model_id"),
                func.coalesce(func.sum(UsageEventModel.total_tokens), 0).label(
                    "total_tokens"
                ),
                func.count().label("event_count"),
                func.max(UsageEventModel.status).label("status"),
            )
            .select_from(UsageEventModel)
            .outerjoin(RunModel, RunModel.id == UsageEventModel.run_id),
            **filt,
        )
        .group_by(bill_run_id)
        .order_by(func.max(UsageEventModel.created_at).desc())
    )
    total = int(
        session.scalar(select(func.count()).select_from(grouped.subquery())) or 0
    )
    rows = session.execute(grouped.offset(offset).limit(limit)).all()
    return UsageListResponse(
        items=[
            UsageEventResponse(
                id=str(row.run_key),
                created_at=row.created_at,
                user_id=row.user_id or "",
                username=row.username or "",
                display_name=row.display_name or "",
                run_id=row.run_id,
                session_id=row.session_id,
                mode=row.mode or "normal",
                question=row.question or "",
                model_id=row.model_id or "",
                status=row.status or "ok",
                total_tokens=int(row.total_tokens),
                event_count=int(row.event_count),
            )
            for row in rows
        ],
        total=int(total),
        sum_total_tokens=int(sum_tokens),
        group_by="run",
    )


@router.get("/summary", response_model=list[UsageSummaryRow])
def summarize_usage_by_user(
    session: DbSession,
    _admin: AdminPrincipal,
    user_id: Annotated[str | None, Query(max_length=64)] = None,
    username: Annotated[str | None, Query(max_length=64)] = None,
    purpose: Annotated[str | None, Query(max_length=96)] = None,
    mode: Annotated[str | None, Query(max_length=16)] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[UsageSummaryRow]:
    statement = _filters(
        select(
            UsageEventModel.user_id,
            UsageEventModel.username,
            UsageEventModel.display_name,
            func.count().label("event_count"),
            func.coalesce(func.sum(UsageEventModel.total_tokens), 0).label("total_tokens"),
        ),
        user_id=user_id,
        username=username,
        purpose=purpose,
        mode=mode,
        run_id=None,
        model_id=None,
        status=None,
        since=since,
        until=until,
    ).group_by(
        UsageEventModel.user_id,
        UsageEventModel.username,
        UsageEventModel.display_name,
    ).order_by(func.sum(UsageEventModel.total_tokens).desc()).limit(limit)
    rows = session.execute(statement).all()
    return [
        UsageSummaryRow(
            user_id=row.user_id,
            username=row.username,
            display_name=row.display_name,
            event_count=int(row.event_count),
            total_tokens=int(row.total_tokens),
        )
        for row in rows
    ]


@router.get("/trend", response_model=UsageTrendResponse)
def usage_trend(
    session: DbSession,
    _admin: AdminPrincipal,
    username: Annotated[str | None, Query(max_length=64)] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> UsageTrendResponse:
    """Daily platform token totals for the operations line chart."""

    filt = dict(
        user_id=None,
        username=username,
        purpose=None,
        mode=None,
        run_id=None,
        model_id=None,
        status=None,
        since=since,
        until=until,
    )
    # DATE() works on MySQL (POC) and SQLite tests.
    day_expr = func.date(UsageEventModel.created_at)
    statement = (
        _filters(
            select(
                day_expr.label("bucket"),
                func.coalesce(func.sum(UsageEventModel.total_tokens), 0).label(
                    "total_tokens"
                ),
                func.count().label("event_count"),
            ),
            **filt,
        )
        .group_by(day_expr)
        .order_by(day_expr.asc())
    )
    rows = session.execute(statement).all()
    points = [
        UsageTrendPoint(
            bucket=str(row.bucket),
            total_tokens=int(row.total_tokens),
            event_count=int(row.event_count),
        )
        for row in rows
        if row.bucket is not None
    ]
    return UsageTrendResponse(
        points=points,
        sum_total_tokens=sum(point.total_tokens for point in points),
        event_count=sum(point.event_count for point in points),
    )
