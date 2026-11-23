"""Resolve downloadable documents from owned answers or authorized board snapshots."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from markdown_it import MarkdownIt
from sqlalchemy import select

from xiaoying_quick.application.answer_tables import answer_tables
from xiaoying_quick.application.charts.table_data import chart_table_data
from xiaoying_quick.application.workspace_assets import report_widget, resolve_asset, scoped_report
from xiaoying_quick.infrastructure.persistence.models.artifacts import RunArtifactModel
from xiaoying_quick.infrastructure.persistence.models.chat import ChatMessageModel
from xiaoying_quick.infrastructure.persistence.models.runs import RunEventModel
from xiaoying_quick.shared.errors import Conflict, NotFound, ValidationFailed

VISUAL_TABLE_ROWS = 100


def _chart_section(snapshot: dict, title: str, key: str, view: dict | None = None) -> dict:
    view = view or {}
    charts = snapshot.get("charts", [])
    selected_type = view.get("chart_type") or snapshot.get("default_type")
    chart = next((item for item in charts if item["type"] == selected_type), None)
    if chart is None:
        if selected_type:
            raise ValidationFailed("当前图表样式已变化，请刷新后重试")
        chart = next(iter(charts), None)
    if chart is None:
        raise ValidationFailed("没有可导出的图表")
    return {
        "id": key,
        "kind": "analysis",
        "title": title,
        "scope": snapshot.get("scope", ""),
        "kpis": snapshot.get("kpis", []),
        "chart": deepcopy(chart["option"]),
        "show_values": bool(view.get("show_values")),
        "data": chart_table_data(snapshot, chart),
        "details": snapshot.get("details"),
    }


def _report_sections(report: dict, key: str) -> list[dict]:
    sections = []
    _, kpis, _ = report_widget(report, "kpis")
    metrics = deepcopy(kpis["metrics"])
    for metric in metrics:
        if metric.get("unit") == "%" and metric.get("value") is not None:
            metric["value"] /= 100
    sections.append(
        {
            "id": f"{key}-kpis",
            "kind": "kpi",
            "title": report["title"],
            "scope": report.get("subtitle", ""),
            "kpis": metrics,
        }
    )
    findings = [
        " ".join(str(item.get(field) or "") for field in ("title", "body")).strip()
        for item in report.get("findings", [])
    ]
    if findings:
        sections.append(
            {
                "id": f"{key}-findings",
                "kind": "text",
                "title": "分析发现",
                "paragraphs": findings,
            }
        )
    for name in ("trend", "contribution"):
        _, snapshot, title = report_widget(report, name)
        sections.append(_chart_section(snapshot, title, f"{key}-{name}"))
    columns = report["columns"]
    sections.append(
        {
            "id": f"{key}-details",
            "kind": "table",
            "title": f"{report['title']} · 明细",
            "data": {
                "columns": [column.get("label") or column["key"] for column in columns],
                "rows": [[row.get(column["key"]) for column in columns] for row in report["rows"]],
                "row_count": len(report["rows"]),
            },
        }
    )
    return sections


def _asset_sections(asset: dict, key: str, view: dict | None = None) -> list[dict]:
    kind, snapshot = asset["kind"], asset["snapshot"]
    if kind == "report":
        state = (view or {}).get("report_state") or {}
        report = scoped_report(snapshot, state) if state else snapshot
        return _report_sections(report, key)
    if kind in {"analysis", "chart"}:
        if (view or {}).get("table_only"):
            section = _chart_section(snapshot, asset["title"], key, view)
            data = section["data"]
            if view.get("table_view") == "details":
                data = section.get("details")
                if not data:
                    raise NotFound("此图表没有已保存的查询明细")
            return [
                {
                    "id": key,
                    "kind": "table",
                    "title": asset["title"],
                    "scope": snapshot.get("scope", ""),
                    "data": data,
                }
            ]
        return [_chart_section(snapshot, asset["title"], key, view)]
    if kind == "table":
        return [
            {
                "id": key,
                "kind": "table",
                "title": asset["title"],
                "scope": snapshot.get("scope", ""),
                "data": snapshot["data"],
            }
        ]
    metrics = deepcopy(snapshot.get("metrics", []))
    for metric in metrics:
        if metric.get("unit") == "%" and metric.get("value") is not None:
            metric["value"] /= 100
    return [{"id": key, "kind": "kpi", "title": asset["title"], "kpis": metrics}]


def _prose(markdown: str) -> list[str]:
    paragraphs = []
    in_table = False
    for token in MarkdownIt().enable("table").parse(markdown):
        if token.type == "table_open":
            in_table = True
        elif token.type == "table_close":
            in_table = False
        elif token.type == "inline" and not in_table:
            text = "".join(
                child.content
                if child.type in {"text", "code_inline"}
                else "\n"
                if child.type in {"softbreak", "hardbreak"}
                else ""
                for child in token.children or []
            ).strip()
            if text:
                paragraphs.append(text)
    return paragraphs


def _query_reference(database, run_id: str, cursor: int, bundle: dict) -> str | None:
    if bundle.get("query_ref"):
        return str(bundle["query_ref"])
    # Earlier chart events predate query_ref. Recover their own present_chart call.
    event = database.scalar(
        select(RunEventModel)
        .where(
            RunEventModel.run_id == run_id,
            RunEventModel.cursor < cursor,
            RunEventModel.event_type == "tool.call",
            RunEventModel.payload["name"].as_string() == "present_chart",
        )
        .order_by(RunEventModel.cursor.desc())
        .limit(1)
    )
    return (event.payload.get("arguments") or {}).get("query_ref") if event else None


def query_data(database, run_id: str, reference: str | None) -> dict | None:
    artifact = database.get(RunArtifactModel, reference) if reference else None
    if not artifact or artifact.run_id != run_id or artifact.kind != "tool_result":
        return None
    body = artifact.payload
    data = body.get("payload", {})
    if body.get("name") != "query_db" or not body.get("ok") or not data.get("columns"):
        return None
    if data.get("sql_review", {}).get("ok") is False:
        return None
    return {
        "columns": data["columns"],
        "rows": data.get("rows", []),
        "row_count": len(data.get("rows", [])),
        "query_truncated": bool(data.get("truncated")),
    }


def resolve_document(
    source: dict, *, principal, database, runs, bot_store, workspace, view: dict | None = None
) -> dict:
    if source["kind"] == "board":
        board = workspace.get(source["board_id"], principal.user_id)
        if board["version"] != source["version"]:
            raise Conflict("看板内容已变化，请刷新后重新导出")
        items = board["items"]
        if source.get("item_id"):
            items = [item for item in items if item["id"] == source["item_id"]]
            if not items:
                raise NotFound("此看板内容已移除，请刷新后重试")
        sections = []
        for item in items:
            item_view = {**source.get("views", {}).get(item["id"], {})}
            if source.get("item_id"):
                item_view.update(view or {})
            sections.extend(_asset_sections(item, item["id"], item_view))
        title = items[0]["title"] if source.get("item_id") else board["name"]
        document = {"title": title, "subtitle": board["description"], "sections": sections}
    elif source["kind"] == "answer":
        run = runs.get_run(principal=principal, run_id=source["run_id"])
        if run.owner_user_id != principal.user_id:
            raise NotFound("只能导出自己的问答")
        bot_store.require(str((run.insight_meta or {}).get("chatbot_id") or "ddi"), principal)
        answer = database.scalar(
            select(ChatMessageModel.content)
            .where(
                ChatMessageModel.run_id == run.id,
                ChatMessageModel.role == "assistant",
            )
            .order_by(ChatMessageModel.created_at.desc())
            .limit(1)
        )
        if answer is None:
            raise ValidationFailed("回答尚未保存，请在分析完成后导出")
        sections = [
            {
                "id": "answer-text",
                "kind": "text",
                "title": "分析结论",
                "paragraphs": _prose(answer),
            }
        ]
        for index, table in enumerate(answer_tables(answer)):
            sections.append(
                {
                    "id": f"answer-table-{index}",
                    "kind": "table",
                    "title": table["title"],
                    "data": table["data"],
                }
            )
        report = database.scalar(
            select(RunArtifactModel)
            .where(
                RunArtifactModel.run_id == run.id,
                RunArtifactModel.kind == "bi_report",
            )
            .order_by(RunArtifactModel.created_at.desc(), RunArtifactModel.revision.desc())
            .limit(1)
        )
        if report:
            sections.extend(
                _report_sections(
                    scoped_report(
                        report.payload,
                        source.get("report_state") or {},
                    ),
                    "answer-report",
                )
            )
        else:
            events = database.scalars(
                select(RunEventModel)
                .where(
                    RunEventModel.run_id == run.id,
                    RunEventModel.event_type == "chart.ready",
                )
                .order_by(RunEventModel.cursor)
            ).all()
            rich = [event for event in events if event.payload.get("version") == 2]
            for event in rich or events[-1:]:
                key = str(event.cursor)
                bundle = event.payload
                section = _chart_section(
                    bundle,
                    bundle.get("title") or "分析图表",
                    f"chart-{key}",
                    source.get("views", {}).get(key),
                )
                section["query_data"] = query_data(
                    database,
                    run.id,
                    _query_reference(database, run.id, event.cursor, bundle),
                )
                sections.append(section)
        exported_tables = database.scalars(
            select(RunArtifactModel)
            .where(
                RunArtifactModel.run_id == run.id,
                RunArtifactModel.kind == "xlsx_export",
            )
            .order_by(RunArtifactModel.created_at)
        ).all()
        for index, artifact in enumerate(exported_tables):
            payload = artifact.payload
            data = {
                "columns": payload.get("columns", []),
                "rows": payload.get("rows", []),
                "query_truncated": bool(payload.get("truncated")),
            }
            if data["columns"]:
                sections.append(
                    {
                        "id": f"exported-table-{index}",
                        "kind": "table",
                        "title": payload.get("title") or "已查询明细",
                        "data": data,
                    }
                )
        document = {"title": run.question[:100], "subtitle": "问数分析", "sections": sections}
    else:
        asset = resolve_asset(
            source,
            principal=principal,
            database=database,
            runs=runs,
            bot_store=bot_store,
        )
        sections = _asset_sections(asset, "selection", view)
        if source["kind"] in {"answer_chart", "answer_analysis", "chart_table"}:
            cursor = asset["source"]["chart_cursor"]
            event = database.get(RunEventModel, (source["run_id"], cursor))
            reference = _query_reference(database, source["run_id"], cursor, event.payload)
            sections[0]["query_data"] = query_data(database, source["run_id"], reference)
        document = {"title": asset["title"], "subtitle": "已确认的分析范围", "sections": sections}
    document["sections"] = [
        section
        for section in document["sections"]
        if (
            section.get("chart")
            or section.get("paragraphs")
            or section.get("kpis")
            or section.get("data", {}).get("columns")
        )
    ]
    if not document["sections"]:
        raise ValidationFailed("当前没有可导出的内容，请先添加分析或图表")
    return document


def document_key(document: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def prepare_document(document: dict) -> dict:
    return {
        "title": document["title"],
        "document_key": document_key(document),
        "charts": [
            {
                "id": section["id"],
                "option": section["chart"],
                "show_values": section.get("show_values", False),
            }
            for section in document["sections"]
            if section.get("chart")
        ],
        "visual_table_rows": VISUAL_TABLE_ROWS,
    }
