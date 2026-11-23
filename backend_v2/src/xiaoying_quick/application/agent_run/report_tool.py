"""Render a report design against verified query data, without model-copied rows."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from xiaoying_quick.modules.agent import AgentToolContext, ToolCallResult, ToolSpec
from xiaoying_quick.shared.ids import new_id

_DESIGN_KEYS = frozenset(
    {
        "title",
        "subtitle",
        "kind",
        "columns",
        "visible_columns",
        "filter_fields",
        "dimension",
        "date_field",
        "metrics",
        "period",
        "current_period",
        "window",
        "metric",
        "chart_type",
        "filters",
        "findings",
        "accent",
    }
)
_METRIC_KEYS = frozenset(
    {
        "qty",
        "amount",
        "amount_usd",
        "target",
        "target_usd",
        "qty_target",
        "prior",
        "prior_usd",
        "qty_prior",
        "previous",
        "previous_usd",
        "qty_previous",
    }
)


def _cell(value: Any) -> Any:
    if isinstance(value, Mapping) and "__decimal__" in value:
        value = Decimal(str(value["__decimal__"]))
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def make_report(
    *,
    table: Mapping[str, Any] | None,
    previous: Mapping[str, Any] | None,
    design: Mapping[str, Any],
    report_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a design; the data always comes from a query or saved report."""
    if "rows" in design or set(design) - _DESIGN_KEYS:
        raise ValueError("design只能包含报告设计字段，不能传入rows或未知配置。")
    base = dict(previous or {})
    if table is not None:
        keys = [str(key) for key in table.get("columns", [])]
        rows = [
            {key: _cell(value) for key, value in zip(keys, row)} for row in table.get("rows", [])
        ]
        source = {
            "label": "已核验查询结果",
            "sql": str(table.get("sql") or ""),
            "truncated": bool(table.get("truncated")),
            "demo": bool(table.get("mock_enabled")),
            "row_count": len(rows),
            **({"domain": "workbook"} if table.get("lab_provider") == "xlsx" else {}),
        }
        # A refreshed query may have a different schema: validate every retained field below.
        base.update(rows=rows, source=source)
    elif previous:
        keys = [str(column["key"]) for column in previous.get("columns", [])]
    else:
        raise ValueError("请先query_db取得数据，再生成报告。")
    available = set(keys)
    derived = {"_achievement", "_yoy", "_qoq", "_share"}
    if not keys:
        raise ValueError("查询未返回列，无法建立报告。")
    settings = dict(base)
    context = dict(report_context or {})
    if previous and context.get("report_id") == previous.get("id"):
        for key in (
            "filters",
            "period",
            "current_period",
            "window",
            "metric",
            "dimension",
            "visible_columns",
            "chart_type",
        ):
            if key in context:
                settings[key] = (
                    {**(settings.get("filters") or {}), **(context[key] or {})}
                    if key == "filters"
                    else context[key]
                )
    settings.update(design)
    raw_columns = settings.get("columns") or [{"key": key, "label": key} for key in keys]
    if not isinstance(raw_columns, list) or not 1 <= len(raw_columns) <= 64:
        raise ValueError("columns必须包含1至64个字段。")
    columns = []
    for column in raw_columns:
        if not isinstance(column, Mapping) or str(column.get("key")) not in available | derived:
            missing = str(column.get("key")) if isinstance(column, Mapping) else str(column)
            raise ValueError(
                f"显示字段 {missing} 不在原数据中，请先补查后再新增字段。"
                f"可用字段：{', '.join(keys)}"
            )
        columns.append(
            {
                "key": str(column["key"]),
                "label": str(column.get("label") or column["key"])[:100],
                "format": str(column.get("format") or "text"),
            }
        )
    # Keep the full field inventory, even when callers only rename a subset of columns.
    known = {column["key"] for column in columns}
    columns.extend({"key": key, "label": key, "format": "text"} for key in keys if key not in known)
    metrics = settings.get("metrics") or {}
    if not isinstance(metrics, Mapping) or set(metrics) - _METRIC_KEYS:
        raise ValueError("metrics包含不支持的指标角色。")
    if any(value not in available for value in metrics.values()):
        raise ValueError("指标字段缺失，请query_db补查目标、同期或上期数据。")
    if not metrics:
        for role, key in (
            ("amount", "sales_amt"),
            ("qty", "sales_qty"),
            ("target", "target_amt"),
            ("prior", "prior_amt"),
            ("previous", "previous_amt"),
        ):
            if key in available:
                metrics[role] = key
    dimension = settings.get("dimension") or next(
        (key for key in keys if key not in metrics.values()), keys[0]
    )
    date_field = settings.get("date_field") or ""
    filters = settings.get("filters") or {}
    filter_fields = settings.get("filter_fields") or []
    visible = settings.get("visible_columns") or keys
    refs = [dimension, *filter_fields, *visible, *filters.keys()]
    if date_field:
        refs.append(date_field)
    if any(key not in available | derived for key in refs):
        missing = sorted(set(refs) - available - derived)
        raise ValueError(
            f"维度/筛选/显示字段 {missing} 不在查询结果中，请先补查。可用字段：{', '.join(keys)}"
        )
    for key, allowed in (
        ("period", {"day", "month", "quarter", "year"}),
        ("window", {"period", "mtd", "qtd", "ytd"}),
        ("metric", {"amount", "qty", "amount_usd"}),
        ("chart_type", {"line", "bar"}),
        ("kind", {"ddi", "insight"}),
    ):
        if key in settings and settings[key] not in allowed:
            raise ValueError(f"{key}取值不支持。")
    findings = settings.get("findings") or []
    if not isinstance(findings, list) or len(findings) > 6:
        raise ValueError("findings最多6项。")
    report = {
        "id": base.get("id") or new_id("report"),
        "revision": int(base.get("revision") or 0) + 1,
        "title": str(settings.get("title") or "商业表现分析")[:160],
        "subtitle": str(settings.get("subtitle") or "")[:1000],
        "kind": settings.get("kind", "insight"),
        "columns": columns,
        "rows": base.get("rows", []),
        "source": base.get("source", {}),
        "metrics": dict(metrics),
        "dimension": dimension,
        "date_field": date_field,
        "filter_fields": list(filter_fields),
        "visible_columns": list(visible),
        "filters": {str(key): str(value) for key, value in filters.items()},
        "period": settings.get("period", "month"),
        "current_period": str(settings.get("current_period") or ""),
        "window": settings.get("window", "period"),
        "metric": settings.get("metric", "amount"),
        "chart_type": settings.get("chart_type", "line"),
        "findings": findings,
        "accent": str(settings.get("accent") or "navy"),
    }
    # Full month × region × brand × channel grids commonly exceed 220 KB.
    # The event only carries an ID; bounded report data is fetched separately.
    if len(json.dumps(report, ensure_ascii=False, default=str).encode()) > 1_500_000:
        raise ValueError("报告结果过大，请按日期/维度聚合后重新查询，或导出xlsx。")
    return report


def report_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return a small verified total so the model need not infer from preview rows."""

    def as_date(value: Any) -> date | None:
        raw = str(value or "")
        if len(raw) == 6 and raw.isdigit():
            raw = raw[:4] + "-" + raw[4:] + "-01"
        if len(raw) == 7:
            raw += "-01"
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None

    rows = list(report.get("rows") or [])
    field = str(report.get("date_field") or "")
    dates = [value for row in rows if (value := as_date(row.get(field))) is not None]
    anchor = as_date(report.get("current_period")) or (max(dates) if dates else None)
    selected = []
    for row in rows:
        if any(
            value and str(row.get(key) or "") != str(value)
            for key, value in (report.get("filters") or {}).items()
        ):
            continue
        if field and anchor:
            value = as_date(row.get(field))
            if value is None or value.year != anchor.year or value.month > anchor.month:
                continue
            window = report.get("window", "period")
            if window == "qtd" and (value.month - 1) // 3 != (anchor.month - 1) // 3:
                continue
            if window not in {"qtd", "ytd"} and value.month != anchor.month:
                continue
        selected.append(row)

    metrics = report.get("metrics") or {}
    role = str(report.get("metric") or "amount")
    if role not in metrics:
        role = next((key for key in ("amount", "qty", "amount_usd") if key in metrics), role)

    def total(key: str | None, scoped=None) -> float | None:
        scoped = selected if scoped is None else scoped
        if not key or not scoped or any(row.get(key) is None for row in scoped):
            return None
        try:
            return round(sum(float(row[key]) for row in scoped), 6)
        except (TypeError, ValueError):
            return None

    actual = total(metrics.get(role))
    target_role = {"amount": "target", "qty": "qty_target", "amount_usd": "target_usd"}
    target_key = metrics.get(target_role.get(role, "target"))
    target = total(target_key)
    dimension_summaries = {}
    fields = list(dict.fromkeys([report.get("dimension"), *(report.get("filter_fields") or [])]))
    for field in fields[:5]:
        if not field or field == report.get("date_field"):
            continue
        groups = {}
        for row in selected:
            groups.setdefault(str(row.get(field) or "未分类"), []).append(row)
        values = []
        for name, scoped in groups.items():
            value = total(metrics.get(role), scoped)
            goal = total(target_key, scoped)
            values.append(
                {
                    "分组": name,
                    "实际": value,
                    "目标": goal,
                    "达成率%": value / goal * 100 if value is not None and goal else None,
                    "目标差额": round(value - goal, 6)
                    if value is not None and goal is not None
                    else None,
                    "缺口金额": round(goal - value, 6)
                    if value is not None and goal is not None
                    else None,
                    "销售占比%": value / actual * 100 if value is not None and actual else None,
                }
            )
        # Include the largest deficits as well as the largest sales groups.
        deficits = sorted(values, key=lambda v: v["目标差额"] or 0)[:4]
        largest = sorted(values, key=lambda v: v["实际"] or 0, reverse=True)[:8]
        dimension_summaries[field] = list({v["分组"]: v for v in [*deficits, *largest]}.values())
    return {
        "记录数": len(selected),
        "实际": actual,
        "目标": target,
        "达成率%": actual / target * 100 if actual is not None and target else None,
        "销售数量": total(metrics.get("qty")),
        "口径": role,
        "差额定义": "目标差额=实际减目标（负数为缺口）；缺口金额=目标减实际（正数为缺口）。",
        "净缺口": round(target - actual, 6) if actual is not None and target is not None else None,
        "分组核验": dimension_summaries,
    }


def build_render_report_tool() -> ToolSpec:
    async def execute(context: AgentToolContext, arguments: Mapping[str, Any]) -> ToolCallResult:
        try:
            artifacts = context.dependency("artifacts")
            tables = list(context.dependency("query_tables") or [])
            previous = artifacts.latest(run_id=context.run_id, kind="bi_report")
            report_context = context.dependency("report_context") or {}
            if previous is None and not arguments.get("new_report", False):
                saved = context.dependency("previous_report")
                if arguments.get("reuse_previous", True) or (
                    saved and report_context.get("report_id") == saved.get("id")
                ):
                    # Refreshing query data does not create a new report identity.
                    previous = saved
            design = arguments.get("design") or {}
            if not isinstance(design, Mapping):
                raise ValueError("design必须为对象。")
            table = None
            if tables:
                index = arguments.get("query_index")
                # Select only a verified grid that contains all requested source fields.
                # A model may miscount query_index after metadata probes; never merge
                # unrelated aggregates or invent columns to make that index work.
                required = set(design.get("metrics", {}).values())
                required.update(
                    c.get("key") for c in design.get("columns", []) if isinstance(c, Mapping)
                )
                required.update(design.get("filter_fields", []))
                required.update(design.get("visible_columns", []))
                required.update(k for k in (design.get("dimension"), design.get("date_field")) if k)
                if previous:
                    # Adding a field must not discard existing filter dimensions or
                    # comparable measures when the model refreshes the source grid.
                    remapped = {
                        old["key"]: new["key"]
                        for old in previous.get("columns", [])
                        for new in design.get("columns", [])
                        if old.get("label") and old.get("label") == new.get("label")
                    }
                    required.update(
                        remapped.get(key, key) for key in previous.get("filter_fields", [])
                    )
                    for role, key in (previous.get("metrics") or {}).items():
                        required.add(design.get("metrics", {}).get(role, key))
                required.difference_update({"_achievement", "_yoy", "_qoq", "_share"})
                matches = [
                    (i, t) for i, t in enumerate(tables) if required.issubset(t.get("columns", []))
                ]
                if (
                    index is not None
                    and 0 <= int(index) < len(tables)
                    and required.issubset(tables[int(index)].get("columns", []))
                ):
                    table = tables[int(index)]
                elif matches:
                    table = max(matches, key=lambda pair: (len(pair[1].get("rows", [])), pair[0]))[
                        1
                    ]
                else:
                    inventory = [
                        {
                            "query_index": i,
                            "columns": t.get("columns", []),
                            "missing_fields": sorted(required - set(t.get("columns", []))),
                        }
                        for i, t in enumerate(tables)
                    ]
                    raise ValueError(
                        "没有一份已核验结果同时包含所需字段。新增字段时也须保留原筛选维度与指标。"
                        "请ask_lab补查单份完整结果，"
                        "趋势报告须保留月份及筛选维度，禁止拼接不同粒度汇总。可用查询："
                        + json.dumps(inventory, ensure_ascii=False)
                    )
            report = make_report(
                table=table,
                previous=previous,
                design=design,
                report_context=report_context,
            )
            provenance = context.dependency("report_data_provenance")
            if table is not None and isinstance(provenance, Mapping):
                report["source"].update(provenance)
            artifacts.append(run_id=context.run_id, kind="bi_report", payload=report)
            context.emit(
                "report.ready",
                {
                    "report_id": report["id"],
                    "revision": report["revision"],
                    "run_id": context.run_id,
                },
            )
            return ToolCallResult(
                ok=True,
                output=f"已生成交互HTML报告《{report['title']}》v{report['revision']}。"
                "用户可直接筛选、编辑字段并下载HTML。"
                "当前视图核验汇总："
                + json.dumps(report_summary(report), ensure_ascii=False)
                + "。请简述结论与修改，无需再输出表格。",
                payload={"report_id": report["id"], "revision": report["revision"]},
            )
        except (ValueError, TypeError, IndexError, LookupError) as exc:
            return ToolCallResult(ok=False, output=str(exc))

    return ToolSpec(
        name="render_report",
        description="用已核验query_db结果生成/修订交互HTML报告，支持图表、筛选、字段编辑。"
        "design只包含展示配置，禁止传rows。修改已有报告时reuse_previous=true；"
        "新增数据里不存在的字段须先补查。query_index为本轮查询结果的0起始序号。"
        "追问即使重新取数也保持原报告身份。只有用户明确另建独立报告才new_report=true。",
        parameters={
            "type": "object",
            "properties": {
                "new_report": {
                    "type": "boolean",
                    "description": "仅用户明确另建独立报告时为true，追问修改为false。",
                },
                "design": {
                    "type": "object",
                    "description": (
                        "支持title,subtitle,kind(ddi/insight),columns([{key,label,format}]),"
                        "metrics({amount,qty,target,prior,previous,...:查询列名}),date_field,"
                        "dimension,filter_fields,visible_columns,filters,period(day/month/quarter/year),"
                        "current_period(YYYY-MM),window(period/mtd/qtd/ytd),metric(amount/qty/amount_usd),"
                        "chart_type(line/bar),findings([{title,body,type}]),accent(navy/teal/red)。"
                        "metrics历史字段必须是预先对齐到每行同一粒度的可加总量。"
                    ),
                },
                "reuse_previous": {"type": "boolean", "default": True},
                "query_index": {"type": "integer", "minimum": 0},
            },
            "required": ["design"],
        },
        executor=execute,
    )
