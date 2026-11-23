"""Eval workbook parse/export and per-item result persistence."""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, File, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ...api.dependencies import CurrentPrincipal, DbSession
from ...infrastructure.eval_xlsx import (
    MAX_WORKBOOK_BYTES,
    RESULT_HEADERS,
    dump_xlsx,
    parse_xlsx,
    workbook_from_payload,
    workbook_to_queue_payload,
)
from ...infrastructure.persistence.repositories.eval_results import (
    SqlAlchemyEvalResultRepository,
)
from ...shared.errors import NotFound, ValidationFailed

router = APIRouter(prefix="/api/v2/eval", tags=["eval"])


class EvalExportRequest(BaseModel):
    filename: str = Field(default="评测结果.xlsx", max_length=200)
    sheets: list[dict[str, Any]] = Field(min_length=1, max_length=16)


class EvalBatchCreateRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=200)


class EvalResultWriteRequest(BaseModel):
    sheet: str = Field(min_length=1, max_length=128)
    row: int = Field(ge=1, le=50_000)
    question: str = Field(default="", max_length=10_000)
    category: str = Field(default="", max_length=200)
    status: str = Field(min_length=1, max_length=24)
    clarify: str = Field(default="", max_length=200_000)
    sql: str = Field(default="", max_length=1_000_000)
    labs: str = Field(default="", max_length=200_000)
    answer: str = Field(default="", max_length=200_000)
    duration: str = Field(default="", max_length=64)
    run_id: str = Field(default="", max_length=64)
    error: str = Field(default="", max_length=2_000)
    headers: list[str] = Field(default_factory=list, max_length=40)
    values: dict[str, str] = Field(default_factory=dict)


@router.post("/workbooks/parse")
async def parse_eval_workbook(
    principal: CurrentPrincipal,
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    del principal
    filename = (file.filename or "workbook.xlsx").strip() or "workbook.xlsx"
    if not filename.lower().endswith(".xlsx"):
        raise ValidationFailed("请上传 .xlsx 工作簿")
    data = await file.read(MAX_WORKBOOK_BYTES + 1)
    if len(data) > MAX_WORKBOOK_BYTES:
        raise ValidationFailed("工作簿超过 12MB 上限")
    if not data:
        raise ValidationFailed("上传文件为空")
    try:
        workbook = parse_xlsx(data, filename=filename)
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    return workbook_to_queue_payload(workbook)


@router.post("/workbooks/export")
def export_eval_workbook(
    principal: CurrentPrincipal,
    body: EvalExportRequest,
) -> Response:
    del principal
    try:
        workbook = workbook_from_payload(body.model_dump())
        payload = dump_xlsx(workbook)
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    filename = (
        workbook.filename if workbook.filename.endswith(".xlsx") else f"{workbook.filename}.xlsx"
    )
    ascii_name = "eval-result.xlsx"
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_name}"; '
                f"filename*=UTF-8''{_encode_filename(filename)}"
            )
        },
        status_code=status.HTTP_200_OK,
    )


@router.post("/batches", status_code=status.HTTP_201_CREATED)
def create_eval_batch(
    principal: CurrentPrincipal,
    database: DbSession,
    body: EvalBatchCreateRequest,
) -> dict[str, str]:
    filename = body.filename.strip() or "评测.xlsx"
    if not filename.lower().endswith(".xlsx"):
        filename = f"{filename}.xlsx"
    batch = SqlAlchemyEvalResultRepository(database).create_batch(
        owner_user_id=principal.user_id,
        filename=filename[:200],
    )
    return {"id": batch.id, "filename": batch.filename}


@router.put("/batches/{batch_id}/items")
def upsert_eval_result(
    batch_id: str,
    principal: CurrentPrincipal,
    database: DbSession,
    body: EvalResultWriteRequest,
) -> dict[str, Any]:
    repo = SqlAlchemyEvalResultRepository(database)
    batch = repo.get_batch(batch_id, owner_user_id=principal.user_id)
    if batch is None:
        raise NotFound("评测批次不存在")
    status_value = body.status.strip() or "done"
    if status_value not in {"queued", "running", "clarify", "done", "failed", "paused"}:
        raise ValidationFailed("评测结果状态无效")
    headers = [str(item)[:80] for item in body.headers[:40] if str(item).strip()]
    extra = {str(key)[:80]: str(value)[:20_000] for key, value in list(body.values.items())[:40]}
    row = repo.upsert_result(
        batch_id=batch.id,
        sheet=body.sheet.strip()[:128],
        row_number=body.row,
        question=body.question.strip()[:10_000],
        category=body.category.strip()[:200],
        status=status_value,
        clarify=body.clarify[:200_000],
        sql_text=body.sql[:1_000_000],
        labs=body.labs[:200_000],
        answer=body.answer[:200_000],
        duration=body.duration.strip()[:64],
        run_id=body.run_id.strip()[:64],
        error=body.error.strip()[:2_000],
        headers=headers,
        extra_values=extra,
    )
    return _summary(row)


@router.get("/batches/{batch_id}/items")
def list_eval_results(
    batch_id: str,
    principal: CurrentPrincipal,
    database: DbSession,
) -> dict[str, Any]:
    repo = SqlAlchemyEvalResultRepository(database)
    batch = repo.get_batch(batch_id, owner_user_id=principal.user_id)
    if batch is None:
        raise NotFound("评测批次不存在")
    return {
        "id": batch.id,
        "filename": batch.filename,
        "items": [_summary(row) for row in repo.list_summaries(batch.id)],
    }


@router.get("/batches/{batch_id}/items/one")
def get_eval_result(
    batch_id: str,
    principal: CurrentPrincipal,
    database: DbSession,
    sheet: Annotated[str, Query(min_length=1, max_length=128)],
    row: Annotated[int, Query(ge=1, le=50_000)],
) -> dict[str, Any]:
    repo = SqlAlchemyEvalResultRepository(database)
    batch = repo.get_batch(batch_id, owner_user_id=principal.user_id)
    if batch is None:
        raise NotFound("评测批次不存在")
    record = repo.get_result(batch.id, sheet=sheet.strip(), row_number=row)
    if record is None:
        raise NotFound("评测结果不存在")
    return _detail(record)


@router.get("/batches/{batch_id}/export")
def export_eval_batch(
    batch_id: str,
    principal: CurrentPrincipal,
    database: DbSession,
) -> Response:
    repo = SqlAlchemyEvalResultRepository(database)
    batch = repo.get_batch(batch_id, owner_user_id=principal.user_id)
    if batch is None:
        raise NotFound("评测批次不存在")
    rows = repo.list_summaries(batch.id)
    if not rows:
        raise ValidationFailed("这个批次还没有可导出的结果")
    payload = dump_xlsx(workbook_from_payload(_export_payload(batch.filename, rows)))
    filename = batch.filename if batch.filename.endswith(".xlsx") else f"{batch.filename}.xlsx"
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="eval-result.xlsx"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
        status_code=status.HTTP_200_OK,
    )


def _summary(row: Any) -> dict[str, Any]:
    return {
        "sheet": row.sheet,
        "row": row.row_number,
        "question": row.question,
        "category": row.category,
        "status": row.status,
        "duration": row.duration,
        "run_id": row.run_id,
        "error": row.error,
        "answer_preview": row.answer_preview,
        "headers": list(row.headers or ()),
    }


def _detail(row: Any) -> dict[str, Any]:
    payload = _summary(row)
    payload.update(
        {
            "clarify": row.clarify,
            "sql": row.sql_text,
            "labs": row.labs,
            "answer": row.answer,
            "values": dict(row.extra_values or {}),
        }
    )
    return payload


def _export_payload(filename: str, rows: list[Any]) -> dict[str, Any]:
    extra = [*RESULT_HEADERS, "状态", "运行ID"]
    by_sheet: dict[str, dict[str, Any]] = {}
    for row in rows:
        sheet = by_sheet.setdefault(
            row.sheet,
            {
                "name": row.sheet,
                "headers": _headers_for(row, extra),
                "rows": [],
            },
        )
        values = dict(row.extra_values or {})
        values["问题"] = row.question
        if row.category:
            values["问题分类"] = row.category
        values["澄清选项"] = row.clarify
        values["最终sql"] = row.sql_text
        values["实验室选择"] = row.labs
        values["最终结果"] = row.answer or row.error
        values["持续时间"] = row.duration
        values["状态"] = row.status
        values["运行ID"] = row.run_id
        sheet["rows"].append({"row": row.row_number, "values": values})
    return {"filename": filename, "sheets": list(by_sheet.values())}


def _headers_for(row: Any, extra: list[str]) -> list[str]:
    headers = [str(item) for item in (row.headers or []) if str(item)]
    if "问题" not in headers:
        headers.insert(0, "问题")
    for name in extra:
        if name not in headers:
            headers.append(name)
    return headers


def _encode_filename(name: str) -> str:
    return quote(name)
