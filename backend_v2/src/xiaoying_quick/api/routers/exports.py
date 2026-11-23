"""Authenticated file downloads for answers, chart selections and shared boards."""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from pydantic import Field, model_validator

from xiaoying_quick.api.dependencies import CurrentPrincipal, DbSession, RunServiceDep
from xiaoying_quick.api.routers.chatbots import get_chatbot_store
from xiaoying_quick.api.routers.workspace import PinSource, Store, Strict
from xiaoying_quick.application.document_exports import (
    document_key,
    prepare_document,
    resolve_document,
)
from xiaoying_quick.infrastructure.document_export import write_document
from xiaoying_quick.shared.errors import Conflict

router = APIRouter(prefix="/api/v2/exports", tags=["exports"])


class ExportView(Strict):
    chart_type: str | None = Field(default=None, max_length=32)
    show_values: bool = False
    table_only: bool = False
    table_view: Literal["chart", "details"] = "chart"
    report_state: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_report_state(self):
        if self.report_state:
            # Reuse the report's existing state validation and field allowlist.
            source = PinSource(
                kind="report",
                run_id="validation",
                report_id="validation",
                report_revision=1,
                state=self.report_state,
            )
            self.report_state = source.state
        return self


class AnswerSource(Strict):
    kind: Literal["answer"]
    run_id: str = Field(min_length=1, max_length=64)
    report_state: dict[str, Any] = Field(default_factory=dict)
    views: dict[str, ExportView] = Field(default_factory=dict, max_length=40)

    @model_validator(mode="after")
    def validate_report_state(self):
        self.report_state = ExportView(report_state=self.report_state).report_state
        return self


class BoardSource(Strict):
    kind: Literal["board"]
    board_id: str = Field(min_length=1, max_length=64)
    item_id: str | None = Field(default=None, max_length=64)
    version: int = Field(ge=1)
    views: dict[str, ExportView] = Field(default_factory=dict, max_length=40)


class ExportRequest(Strict):
    source: Annotated[PinSource | AnswerSource | BoardSource, Field(discriminator="kind")]
    view: ExportView = Field(default_factory=ExportView)


class ExportDownload(ExportRequest):
    format: Literal["pptx", "xlsx", "pdf"]
    document_key: str = Field(min_length=64, max_length=64)
    images: dict[str, str] = Field(default_factory=dict, max_length=40)

    @model_validator(mode="after")
    def image_budget(self):
        if len(json.dumps(self.images)) > 28_000_000:
            raise ValueError("图表图片过多，请选择单项导出")
        return self


def _document(body, principal, database, runs, workspace, request):
    return resolve_document(
        body.source.model_dump(),
        principal=principal,
        database=database,
        runs=runs,
        bot_store=get_chatbot_store(request),
        workspace=workspace,
        view=body.view.model_dump(exclude_unset=True),
    )


@router.post("/prepare")
def prepare_export(
    body: ExportRequest,
    principal: CurrentPrincipal,
    database: DbSession,
    runs: RunServiceDep,
    workspace: Store,
    request: Request,
    response: Response,
) -> dict:
    response.headers["Cache-Control"] = "private, no-store"
    return prepare_document(_document(body, principal, database, runs, workspace, request))


@router.post("/download")
def download_export(
    body: ExportDownload,
    principal: CurrentPrincipal,
    database: DbSession,
    runs: RunServiceDep,
    workspace: Store,
    request: Request,
) -> Response:
    document = _document(body, principal, database, runs, workspace, request)
    if document_key(document) != body.document_key:
        raise Conflict("分析内容已变化，请重新导出")
    payload = write_document(document, body.format, body.images)
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', " ", document["title"]).strip()[:100] or "问数分析"
    title = title.encode("utf-8")[:180].decode("utf-8", errors="ignore").rstrip()
    filename = f"{title}.{body.format}"
    media = {
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pdf": "application/pdf",
    }
    return Response(
        payload,
        media_type=media[body.format],
        headers={
            "Content-Disposition": (
                f"attachment; filename=analysis.{body.format}; filename*=UTF-8''{quote(filename)}"
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
