"""Resolve pins from server-owned answers and limit shared reports to the saved scope."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from copy import deepcopy
from datetime import date
from typing import Any

from sqlalchemy import select

from xiaoying_quick.application.answer_tables import answer_tables
from xiaoying_quick.application.charts.table_data import chart_table_data
from xiaoying_quick.infrastructure.persistence.models.artifacts import RunArtifactModel
from xiaoying_quick.infrastructure.persistence.models.chat import ChatMessageModel
from xiaoying_quick.infrastructure.persistence.models.runs import RunEventModel
from xiaoying_quick.shared.errors import Forbidden, NotFound, ValidationFailed


def _date(value: Any) -> date | None:
    raw = str(value or "")
    if re.fullmatch(r"\d{6}", raw):
        raw = f"{raw[:4]}-{raw[4:]}-01"
    if re.fullmatch(r"\d{4}-\d{2}", raw):
        raw += "-01"
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def scoped_report(report: dict, state: dict) -> dict:
    result = deepcopy(report)
    allowed = {column["key"] for column in report["columns"]}
    derived = {"_achievement", "_share", "_yoy", "_qoq"}
    enums = {
        "period": {"day", "month", "quarter", "year"},
        "window": {"period", "mtd", "qtd", "ytd"},
        "metric": {"amount", "qty", "amount_usd"},
        "chart_type": {"line", "bar"},
    }
    for key, choices in enums.items():
        if key in state:
            if state[key] not in choices:
                raise ValidationFailed("报告视图配置无效，请刷新后重试")
            result[key] = state[key]
    if state.get("dimension"):
        if state["dimension"] not in allowed:
            raise ValidationFailed("分组字段不在当前报告中")
        result["dimension"] = state["dimension"]
    if "visible_columns" in state:
        visible = state["visible_columns"]
        if not isinstance(visible, list) or not set(visible) <= allowed | derived:
            raise ValidationFailed("显示字段不在当前报告中")
        result["visible_columns"] = visible
    filters = {**report.get("filters", {}), **state.get("filters", {})}
    if not set(filters) <= allowed or any(not isinstance(v, str) for v in filters.values()):
        raise ValidationFailed("筛选字段或筛选值无效")
    field = report.get("date_field")
    dates = [parsed for row in report["rows"] if (parsed := _date(row.get(field)))] if field else []
    period = state.get("current_period") or report.get("current_period")
    anchor = _date(period) if period else max(dates, default=None)
    if period and anchor is None:
        raise ValidationFailed("统计月份格式无效")
    selected = []
    for row in report["rows"]:
        if any(value and str(row.get(key, "")) != value for key, value in filters.items()):
            continue
        if field and anchor:
            current = _date(row.get(field))
            if current is None or current.year != anchor.year or current.month > anchor.month:
                continue
            window = result.get("window", "period")
            if window == "qtd" and (current.month - 1) // 3 != (anchor.month - 1) // 3:
                continue
            if window in ("period", "mtd") and current.month != anchor.month:
                continue
        selected.append({key: value for key, value in row.items() if key in allowed})
    if not selected:
        raise ValidationFailed("当前筛选没有数据，请调整后再加入看板")
    if filters != report.get("filters", {}) or any(
        key in state and state[key] != report.get(key)
        for key in ("window", "current_period", "metric")
    ):
        result["findings"] = []
        result["subtitle"] = "已保存的筛选范围；图表与明细按收藏时的数据呈现。"
    result.update(rows=selected, filters=filters, read_only=True)
    if anchor:
        result["current_period"] = anchor.strftime("%Y-%m")
    result["source"] = {
        key: value
        for key, value in report.get("source", {}).items()
        if key in {"label", "sample", "demo", "truncated", "domain"}
    }
    result["source"].update(row_count=len(selected), note="看板保存时的筛选范围；数据未自动刷新。")
    return result


def _sum(rows: list[dict], key: str | None) -> float | None:
    if not rows or not key or any(row.get(key) in (None, "") for row in rows):
        return None
    try:
        return sum(float(row[key]) for row in rows)
    except (ValueError, TypeError):
        return None


def report_widget(report: dict, section: str) -> tuple[str, dict, str]:
    rows = report["rows"]
    metrics = report.get("metrics", {})
    role = report.get("metric", "amount")
    if role not in metrics:
        role = next((key for key in ("amount", "qty", "amount_usd") if key in metrics), "amount")
    key = metrics.get(role)
    if not key:
        raise ValidationFailed("报告缺少可收藏的主指标，请先配置指标")
    goal = metrics.get({"qty": "qty_target", "amount_usd": "target_usd"}.get(role, "target"))
    prior = metrics.get({"qty": "qty_prior", "amount_usd": "prior_usd"}.get(role, "prior"))
    previous = metrics.get(
        {"qty": "qty_previous", "amount_usd": "previous_usd"}.get(role, "previous")
    )
    labels = {column["key"]: column.get("label") or column["key"] for column in report["columns"]}
    title = labels.get(key, key)
    unit = "数量" if role == "qty" else "USD" if role == "amount_usd" else "CNY"
    if report.get("source", {}).get("domain") == "workbook":
        unit = (
            "CNY"
            if re.search(r"金额|收入|销售额|费用|成本", title)
            else "人"
            if re.search(
                r"人数|用户|活跃|转化|访问",
                title,
            )
            else "数量"
        )
    actual, target, old, last = (_sum(rows, value) for value in (key, goal, prior, previous))
    if section == "kpis":

        def rate(value, base, growth=False):
            return None if value is None or base in (None, 0) else (value / base - growth) * 100

        return (
            "kpi",
            {
                "metrics": [
                    {"label": title, "value": actual, "unit": unit},
                    {"label": "目标达成率", "value": rate(actual, target), "unit": "%"},
                    (
                        {
                            "label": "目标总额" if unit in ("CNY", "USD") else "目标总量",
                            "value": target,
                            "unit": unit,
                        }
                        if target is not None
                        else {"label": "同比增长", "value": rate(actual, old, True), "unit": "%"}
                    ),
                    (
                        {
                            "label": "目标差额",
                            "value": actual - target if actual is not None else None,
                            "unit": unit,
                        }
                        if target is not None
                        else {"label": "环比增长", "value": rate(actual, last, True), "unit": "%"}
                    ),
                ]
            },
            f"{report['title']} · 核心指标",
        )
    dimension = report["dimension"]
    field = report.get("date_field")
    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        if section == "trend" and field:
            parsed = _date(row.get(field))
            if parsed is None:
                continue
            period = report.get("period", "month")
            label = (
                str(parsed.year)
                if period == "year"
                else f"{parsed.year} Q{(parsed.month - 1) // 3 + 1}"
                if period == "quarter"
                else parsed.isoformat()
                if period == "day"
                else parsed.strftime("%Y-%m")
            )
        else:
            label = str(row.get(dimension) or "未分类")
        groups[label].append(row)
    grouped = [
        (name, _sum(values, key), _sum(values, goal), _sum(values, prior))
        for name, values in groups.items()
    ]
    grouped.sort(key=lambda entry: entry[0] if section == "trend" and field else -(entry[1] or 0))
    series = []
    if section == "contribution":
        base_index = 3 if old is not None else 2 if target is not None else None
        values = [
            (
                name,
                value - entry[base_index]
                if base_index is not None and value is not None and entry[base_index] is not None
                else value,
            )
            for entry in grouped
            for name, value in [entry[:2]]
        ]
        values.sort(key=lambda item: -(abs(item[1] or 0)))
        names = [item[0] for item in values[:20]]
        series = [
            {
                "name": "贡献",
                "type": "bar",
                "data": [
                    {
                        "value": value,
                        "itemStyle": {"color": "#c5203f" if (value or 0) < 0 else "#399b9f"},
                    }
                    for _, value in values[:20]
                ],
            }
        ]
        heading = f"{labels.get(dimension, dimension)} · " + (
            "同比增量贡献"
            if old is not None
            else "目标差额贡献"
            if target is not None
            else "指标贡献"
        )
    else:
        names = [entry[0] for entry in grouped]
        chart_type = report.get("chart_type", "line")
        series.append({"name": title, "type": chart_type, "data": [entry[1] for entry in grouped]})
        if target is not None:
            series.append(
                {"name": "目标", "type": chart_type, "data": [entry[2] for entry in grouped]}
            )
        heading = f"{title} · {'趋势' if field else '对比'}"
    option = {
        "color": ["#c5203f", "#9aabbc"],
        "tooltip": {"trigger": "axis", "renderMode": "richText"},
        "legend": {"top": 6},
        "grid": {"left": 30, "right": 24, "bottom": 30, "top": 45, "containLabel": True},
        "xAxis": {"type": "category", "data": names},
        "yAxis": {"type": "value", "name": unit},
        "series": series,
    }
    chart_type = "bar" if section == "contribution" else report.get("chart_type", "line")
    return (
        "chart",
        {
            "charts": [{"type": chart_type, "label": heading, "option": option}],
            "default_type": chart_type,
        },
        heading,
    )


def resolve_asset(source: dict, *, principal, database, runs, bot_store) -> dict:
    run = runs.get_run(principal=principal, run_id=source["run_id"])
    if run.owner_user_id != principal.user_id:
        raise Forbidden("只能收藏自己对话中的图表")
    bot_id = str((run.insight_meta or {}).get("chatbot_id") or "ddi")
    bot = bot_store.require(bot_id, principal)
    state = source.get("state") or {}
    if source["kind"] == "answer_table":
        answer = database.scalar(
            select(ChatMessageModel.content).where(
                ChatMessageModel.run_id == run.id, ChatMessageModel.role == "assistant",
            ).order_by(ChatMessageModel.created_at.desc()).limit(1)
        )
        if answer is None:
            raise NotFound("此回答尚未保存，请在回答完成后加入看板")
        tables = answer_tables(answer)
        index = source.get("table_index")
        if not isinstance(index, int) or not 0 <= index < len(tables):
            raise NotFound("此数据表尚未保存或已不可访问，请刷新原问答")
        table = tables[index]
        kind, snapshot, title = (
            "table", {"data": table["data"], "scope": table["title"]}, table["title"],
        )
    elif source["kind"] in {"answer_analysis", "answer_chart", "chart_table"}:
        statement = select(RunEventModel.cursor).where(
            RunEventModel.run_id == run.id,
            RunEventModel.event_type == "chart.ready",
        )
        if source.get("chart_cursor"):
            statement = statement.where(RunEventModel.cursor == source["chart_cursor"])
        cursor = database.scalar(statement.order_by(RunEventModel.cursor.desc()).limit(1))
        event = database.get(RunEventModel, (run.id, cursor)) if cursor else None
        charts = event.payload.get("charts", []) if event else []
        selected = next(
            (chart for chart in charts if chart.get("type") == source.get("chart_type")), None
        )
        if selected is None:
            raise NotFound("这张图表尚未保存或已不可访问，请刷新原问答")
        whole_analysis = source["kind"] == "answer_analysis"
        saved_charts = deepcopy(charts if whole_analysis else [selected])
        for chart in saved_charts:
            saved_option = chart.setdefault("option", {})
            saved_option.setdefault("tooltip", {}).update(renderMode="richText", confine=True)
            saved_option.pop("toolbox", None)
        option = selected.get("option", {})
        kind, snapshot, title = (
            "analysis" if whole_analysis else "chart",
            {"charts": saved_charts, "default_type": selected["type"]},
            (option.get("title", {}).get("text") or selected.get("label") or "问答图表"),
        )
        if whole_analysis:
            title = event.payload.get("title") or title
        if event.payload.get("version") == 2:
            for key in ("version", "title", "scope", "kpis", "metrics", "warnings", "details"):
                if key in event.payload:
                    snapshot[key] = deepcopy(event.payload[key])
            snapshot["data"] = deepcopy(
                event.payload.get("data", {})
                if whole_analysis else selected.get("data") or event.payload.get("data", {})
            )
        if source["kind"] == "chart_table":
            label = "查询明细" if source.get("table_view") == "details" else "图表数据"
            kind, snapshot, title = (
                "table",
                {
                    "data": chart_table_data(
                        event.payload, selected, source.get("table_view", "chart")
                    ),
                    "scope": event.payload.get("scope", ""),
                },
                f"{title} · {label}"[:120],
            )
    else:
        artifact_id = database.scalar(
            select(RunArtifactModel.id)
            .where(
                RunArtifactModel.run_id == run.id,
                RunArtifactModel.kind == "bi_report",
                RunArtifactModel.payload["id"].as_string() == source.get("report_id"),
                RunArtifactModel.payload["revision"].as_integer() == source.get("report_revision"),
            )
            .limit(1)
        )
        artifact = database.get(RunArtifactModel, artifact_id) if artifact_id else None
        if artifact is None:
            raise NotFound("此报告版本已不可访问，请刷新原问答")
        report = scoped_report(artifact.payload, state)
        if source.get("section", "report") == "report":
            kind, snapshot, title = "report", report, report["title"]
        else:
            kind, snapshot, title = report_widget(report, source["section"])
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                key: value for key, value in source.items()
                if key != "title"
                and (key not in {"chart_cursor", "table_index"} or value is not None)
                and (key != "table_view" or source["kind"] == "chart_table")
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "kind": kind,
        "title": source.get("title") or title,
        "snapshot": snapshot,
        "fingerprint": fingerprint,
        "source": {
            "run_id": run.id,
            "session_id": run.session_id,
            "owner_id": principal.user_id,
            "chatbot_id": bot_id,
            "chatbot_name": bot["name"],
            "kind": source["kind"],
            "chart_cursor": (
                cursor if source["kind"] in {"answer_analysis", "answer_chart", "chart_table"}
                else None
            ),
            "table_index": source.get("table_index"),
            "table_view": source.get("table_view") if source["kind"] == "chart_table" else None,
            "report_id": source.get("report_id"),
            "report_revision": source.get("report_revision"),
            "section": source.get("section"),
            "sample": bot.get("sample", False),
            "scope": {
                **{
                    key: state[key]
                    for key in ("filters", "current_period", "window") if key in state
                },
                **(
                    {"label": snapshot["scope"]}
                    if source["kind"] != "report" and snapshot.get("scope") else {}
                ),
            },
        },
    }
