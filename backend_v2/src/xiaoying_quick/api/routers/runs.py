"""Authenticated run creation, lookup, event pages, and SSE."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from xiaoying_quick.api.dependencies import CurrentPrincipal, DbSession, RunServiceDep
from xiaoying_quick.api.sse import stream_events
from xiaoying_quick.infrastructure.persistence.repositories.artifacts import (
    SqlAlchemyArtifactRepository,
    SqlAlchemyEvidenceRepository,
    SqlAlchemyFactRepository,
)
from xiaoying_quick.infrastructure.result_xlsx import dump_result_xlsx
from xiaoying_quick.modules.runs.contracts import RunEvent, RunMode, RunRecord, RunStatus
from xiaoying_quick.shared.compat import parse_iso_datetime
from xiaoying_quick.shared.errors import NotFound, ValidationFailed

router = APIRouter(prefix="/api/v2/runs", tags=["runs"])


class RunCreateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=10_000)
    session_id: str | None = Field(default=None, max_length=128)


class RunChildSummary(BaseModel):
    id: str
    question: str
    status: RunStatus
    mode: RunMode
    insight_meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class RunResponse(BaseModel):
    id: str
    owner_user_id: str
    session_id: str | None
    question: str
    status: RunStatus
    mode: RunMode = RunMode.NORMAL
    parent_run_id: str | None = None
    insight_meta: dict[str, Any] = Field(default_factory=dict)
    next_event_cursor: int
    version: int
    created_at: datetime
    updated_at: datetime


class RunCreateResponse(BaseModel):
    run: RunResponse
    created: bool


class RunEventResponse(BaseModel):
    run_id: str
    cursor: int
    type: str
    payload: dict[str, Any]
    created_at: datetime


class RunEventPageResponse(BaseModel):
    items: list[RunEventResponse]
    next_cursor: int
    has_more: bool


class TraceArtifactResponse(BaseModel):
    id: str
    kind: str
    atom_id: str | None
    revision: int
    payload: dict[str, Any]
    created_at: datetime


class TraceEvidenceResponse(BaseModel):
    id: str
    atom_id: str
    execution_id: str
    approved_sql_id: str
    sql_fingerprint: str
    data_source_revision_id: str
    state: str
    columns: list[dict[str, str]]
    row_count: int
    truncated: bool
    result_hash: str
    duration_ms: int
    executed_at: datetime


class TraceFactResponse(BaseModel):
    id: str
    atom_id: str
    kind: str
    metric: str
    value: Any
    unit: str | None
    period: str | None
    dimensions: list[list[str]]
    lineage: dict[str, Any]
    created_at: datetime


class RunTraceResponse(BaseModel):
    run: RunResponse
    events: list[RunEventResponse]
    artifacts: list[TraceArtifactResponse]
    evidence: list[TraceEvidenceResponse]
    facts: list[TraceFactResponse]
    gaps: list[dict[str, Any]]
    children: list[RunChildSummary] = Field(default_factory=list)


def _run_response(run: RunRecord) -> RunResponse:
    return RunResponse(
        id=run.id,
        owner_user_id=run.owner_user_id,
        session_id=run.session_id,
        question=run.question,
        status=run.status,
        mode=run.mode,
        parent_run_id=run.parent_run_id,
        insight_meta=dict(run.insight_meta or {}),
        next_event_cursor=run.next_event_cursor,
        version=run.version,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _child_summary(run: RunRecord) -> RunChildSummary:
    return RunChildSummary(
        id=run.id,
        question=run.question,
        status=run.status,
        mode=run.mode,
        insight_meta=dict(run.insight_meta or {}),
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _event_response(event: RunEvent, *, redact: bool = False) -> RunEventResponse:
    payload = _redact(event.payload) if redact else event.payload
    return RunEventResponse(
        run_id=event.run_id,
        cursor=event.cursor,
        type=event.event_type,
        payload=payload if isinstance(payload, dict) else event.payload,
        created_at=event.created_at,
    )


@router.post("", response_model=RunCreateResponse, status_code=status.HTTP_201_CREATED)
def create_run(
    body: RunCreateRequest,
    response: Response,
    principal: CurrentPrincipal,
    service: RunServiceDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RunCreateResponse:
    result = service.create_run(
        principal=principal,
        question=body.question,
        session_id=body.session_id,
        idempotency_key=idempotency_key,
    )
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return RunCreateResponse(run=_run_response(result.run), created=result.created)


@router.get("", response_model=list[RunResponse])
def list_runs(
    principal: CurrentPrincipal,
    service: RunServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RunResponse]:
    return [
        _run_response(run)
        for run in service.list_runs(principal=principal, limit=limit, offset=offset)
    ]


@router.post("/{run_id}/cancel", response_model=RunResponse)
def cancel_run(
    run_id: str,
    principal: CurrentPrincipal,
    service: RunServiceDep,
) -> RunResponse:
    """Owner/admin stop: flips the run to cancelled so workers can exit."""

    return _run_response(service.cancel_run(principal=principal, run_id=run_id))


@router.get("/{run_id}", response_model=RunResponse)
def get_run(run_id: str, principal: CurrentPrincipal, service: RunServiceDep) -> RunResponse:
    return _run_response(service.get_run(principal=principal, run_id=run_id))


@router.get("/{run_id}/children", response_model=list[RunChildSummary])
def list_run_children(
    run_id: str, principal: CurrentPrincipal, service: RunServiceDep
) -> list[RunChildSummary]:
    return [
        _child_summary(child)
        for child in service.list_child_runs(principal=principal, parent_run_id=run_id)
    ]


@router.get("/{run_id}/events", response_model=RunEventPageResponse)
def list_run_events(
    run_id: str,
    principal: CurrentPrincipal,
    service: RunServiceDep,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> RunEventPageResponse:
    page = service.list_events(principal=principal, run_id=run_id, after=after, limit=limit)
    return RunEventPageResponse(
        items=[_event_response(event) for event in page.items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get("/{run_id}/trace", response_model=RunTraceResponse)
def get_run_trace(
    run_id: str,
    principal: CurrentPrincipal,
    service: RunServiceDep,
    database: DbSession,
) -> RunTraceResponse:
    """Return an owner-scoped audit trace without credentials or result rows."""

    run = service.get_run(principal=principal, run_id=run_id)
    event_page = service.list_events(
        principal=principal,
        run_id=run_id,
        after=0,
        limit=1000,
    )
    artifacts = SqlAlchemyArtifactRepository(database).list_for_run(run_id)
    evidence = SqlAlchemyEvidenceRepository(database).for_run(run_id)
    bundle = SqlAlchemyFactRepository(database).for_run(run_id)
    events = [_event_response(event, redact=True) for event in event_page.items]
    gaps = [
        _redact(gap)
        for event in event_page.items
        if event.event_type == "answer.completed"
        for gap in event.payload.get("gaps", [])
        if isinstance(gap, dict)
    ]
    fact_items = [
        TraceFactResponse(
            id=fact.id,
            atom_id=fact.atom_id,
            kind="raw",
            metric=fact.metric,
            value=_json_value(fact.value),
            unit=fact.unit,
            period=fact.period,
            dimensions=[list(value) for value in fact.dimensions],
            lineage={
                "evidence_id": fact.evidence_id,
                "execution_id": fact.execution_id,
                "approved_sql_id": fact.approved_sql_id,
                "data_source_revision_id": fact.data_source_revision_id,
                "semantic_scope_roles": sorted({key for key, _ in fact.semantic_scope}),
            },
            created_at=fact.created_at,
        )
        for fact in bundle.raw
    ]
    fact_items.extend(
        TraceFactResponse(
            id=fact.id,
            atom_id=fact.atom_id,
            kind="derived",
            metric=fact.metric,
            value=_json_value(fact.value),
            unit=fact.unit,
            period=fact.period,
            dimensions=[list(value) for value in fact.dimensions],
            lineage={
                "input_fact_ids": list(fact.input_fact_ids),
                "calc_plan_id": fact.calc_plan_id,
                "calc_version": fact.calc_version,
                "semantic_scope_roles": sorted({key for key, _ in fact.semantic_scope}),
            },
            created_at=fact.created_at,
        )
        for fact in bundle.derived
    )
    children = [
        _child_summary(child)
        for child in service.list_child_runs(principal=principal, parent_run_id=run_id)
    ]
    return RunTraceResponse(
        run=_run_response(run),
        events=events,
        artifacts=[
            TraceArtifactResponse(
                id=str(item["id"]),
                kind=str(item["kind"]),
                atom_id=str(item["atom_id"]) if item["atom_id"] else None,
                revision=int(item["revision"]),
                payload=_redact(item["payload"]),
                created_at=parse_iso_datetime(str(item["created_at"])),
            )
            for item in artifacts
        ],
        evidence=[
            TraceEvidenceResponse(
                id=item.id,
                atom_id=item.atom_id,
                execution_id=item.execution_id,
                approved_sql_id=item.approved_sql_id,
                sql_fingerprint=item.sql_fingerprint,
                data_source_revision_id=item.data_source_revision_id,
                state=item.state.value,
                columns=[asdict(column) for column in item.columns],
                row_count=item.row_count,
                truncated=item.truncated,
                result_hash=item.result_hash,
                duration_ms=item.duration_ms,
                executed_at=item.executed_at,
            )
            for item in evidence
        ],
        facts=fact_items,
        gaps=gaps,
        children=children,
    )


@router.get("/{run_id}/report")
def get_run_report(
    run_id: str, principal: CurrentPrincipal, service: RunServiceDep, database: DbSession,
) -> dict[str, Any]:
    service.get_run(principal=principal, run_id=run_id)
    payload = SqlAlchemyArtifactRepository(database).latest(run_id=run_id, kind="bi_report")
    if payload is None:
        raise NotFound("report not found")
    return payload


@router.get("/{run_id}/exports/{export_id}")
def download_run_export(
    run_id: str,
    export_id: str,
    principal: CurrentPrincipal,
    service: RunServiceDep,
    database: DbSession,
) -> Response:
    """Owner-scoped download of a full query-result workbook."""

    service.get_run(principal=principal, run_id=run_id)
    artifact = SqlAlchemyArtifactRepository(database).get(export_id)
    payload = artifact.get("payload") if artifact else None
    if (
        artifact is None
        or artifact.get("run_id") != run_id
        or artifact.get("kind") != "xlsx_export"
        or not isinstance(payload, dict)
    ):
        raise NotFound("export not found")
    columns = payload.get("columns")
    rows = payload.get("rows")
    if not isinstance(columns, list) or not columns or not isinstance(rows, list):
        raise NotFound("export not found")
    filename = str(payload.get("filename") or "查询结果.xlsx").strip() or "查询结果.xlsx"
    if not filename.lower().endswith(".xlsx"):
        filename = f"{filename}.xlsx"
    try:
        content = dump_result_xlsx(
            title=str(payload.get("title") or ""),
            summary=str(payload.get("summary") or ""),
            columns=[str(column) for column in columns],
            rows=rows,
        )
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="query-result.xlsx"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
        status_code=status.HTTP_200_OK,
    )


@router.get("/{run_id}/stream")
def stream_run_events(
    run_id: str,
    request: Request,
    principal: CurrentPrincipal,
    service: RunServiceDep,
    after: Annotated[int, Query(ge=0)] = 0,
    follow: bool = True,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    service.get_run(principal=principal, run_id=run_id)
    cursor = after
    if last_event_id is not None:
        try:
            header_cursor = int(last_event_id)
        except ValueError as exc:
            raise ValidationFailed("Last-Event-ID must be a non-negative integer") from exc
        if header_cursor < 0:
            raise ValidationFailed("Last-Event-ID must be a non-negative integer")
        cursor = max(cursor, header_cursor)

    settings = request.app.state.settings
    iterator = stream_events(
        session_factory=request.app.state.session_factory,
        run_id=run_id,
        after=cursor,
        follow=follow,
        poll_seconds=settings.sse_poll_seconds,
        heartbeat_seconds=settings.sse_heartbeat_seconds,
    )
    return StreamingResponse(
        iterator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "authorization",
    "api_key",
    "scope_fingerprint",
    "allowed_organizations",
    "allowed_regions",
)
_SENSITIVE_SQL_KEYS = frozenset({"sql", "original_sql", "normalized_sql"})


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if str(key).casefold() in _SENSITIVE_SQL_KEYS
                or any(part in str(key).casefold() for part in _SENSITIVE_KEY_PARTS)
                else _redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return _json_value(value)


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value
