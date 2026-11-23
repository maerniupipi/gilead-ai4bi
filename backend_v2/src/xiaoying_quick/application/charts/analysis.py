"""Compose KPI cards, chart alternatives and data from trusted query snapshots."""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot.errors import ParseError

from xiaoying_quick.application.charts.analysis_metrics import (
    aggregate_grid,
    build_kpis,
    data_payload,
    detail_rows,
    dimension_for,
    metric_records,
    metric_value,
    metrics_for,
    numeric_columns,
)
from xiaoying_quick.application.charts.analysis_options import build_views
from xiaoying_quick.shared.errors import ValidationFailed


def _align_summary_columns(table: dict, summary: dict) -> dict:
    if not table.get("sql") or not summary.get("sql"):
        return summary
    try:
        primary = sqlglot.parse_one(table["sql"], read="sqlite")
        totals = sqlglot.parse_one(summary["sql"], read="sqlite")
    except ParseError:
        return summary
    expressions = {}
    for projection in totals.selects:
        expression = projection.unalias().sql(dialect="sqlite", normalize=True, comments=False)
        expressions.setdefault(expression, []).append(projection.alias_or_name)
    candidates = {}
    for projection in primary.selects:
        name = projection.alias_or_name
        if name not in table["columns"] or name in summary["columns"]:
            continue
        expression = projection.unalias().sql(dialect="sqlite", normalize=True, comments=False)
        matches = [
            column
            for column in expressions.get(expression, [])
            if column in summary["columns"] and column not in table["columns"]
        ]
        if len(matches) == 1:
            candidates.setdefault(matches[0], []).append(name)
    aliases = {column: names[0] for column, names in candidates.items() if len(names) == 1}
    return {**summary, "columns": [aliases.get(column, column) for column in summary["columns"]]}


def build_analysis_bundle(
    table: dict[str, Any],
    *,
    question: str = "",
    title: str = "医药经营分析",
    dimension: str | None = None,
    metrics: list[dict] | None = None,
    summary: dict | None = None,
    default_type: str = "combo",
    scope: str = "",
) -> dict:
    if not table.get("columns") or not table.get("rows"):
        raise ValidationFailed("请先查询包含维度与业务指标的数据")
    if summary and (len(summary.get("rows", [])) != 1 or summary.get("truncated")):
        raise ValidationFailed("顶部汇总必须来自一行完整的总体查询结果")
    if summary:
        summary = _align_summary_columns(table, summary)
    selected = metrics_for(table, metrics)
    dimension = dimension_for(table, dimension, question)
    grid, warnings = aggregate_grid(table, dimension, selected)
    if not grid:
        raise ValidationFailed("当前结果没有可展示的分组数据")
    if table.get("truncated"):
        warnings.append("查询结果已截断，图表仅代表已返回数据，不能视为完整总体。")
    if len(grid) > 120:
        warnings.append("图形最多展示前120个分组，数据表可核验更多结果。")
    plot_metrics = [metric for metric in selected if metric.chart != "kpi"]
    plot_grid = [
        [row[0], *(row[selected.index(metric) + 1] for metric in plot_metrics)] for row in grid
    ]
    kpis = build_kpis(table, dimension, selected, summary)
    if summary and not table.get("truncated"):
        check_rows = detail_rows(table, dimension)
        for metric, kpi in zip(selected, kpis):
            expected = metric_value(metric, check_rows, table["columns"])
            if (
                expected is not None
                and kpi["value"] is not None
                and metric.column in summary["columns"]
            ):
                tolerance = 0.0001 if metric.unit == "%" else 0.01
                if abs(expected - kpi["value"]) > max(tolerance, abs(expected) * 0.00001):
                    raise ValidationFailed("顶部汇总与图表数据不一致，请统一期间、范围和去重口径")
    chart_table = {**table, "rows": detail_rows(table, dimension)}
    charts = build_views(chart_table, dimension, plot_grid, plot_metrics, title[:120])
    if not charts:
        raise ValidationFailed("当前结果不适合图表，请补充可比维度")
    types = {chart["type"] for chart in charts}
    return {
        "version": 2,
        "title": title[:120],
        "scope": scope[:240],
        "default_type": default_type if default_type in types else charts[0]["type"],
        "charts": charts,
        "kpis": kpis,
        "data": data_payload(
            [dimension, *(metric.column for metric in selected)],
            grid,
            selected,
            truncated=table.get("truncated"),
        ),
        "details": data_payload(
            table["columns"], table["rows"], selected, truncated=table.get("truncated"), raw=True
        ),
        "metrics": metric_records(selected),
        "warnings": warnings,
    }


def automatic_analysis(tables: list[dict], question: str) -> dict | None:
    candidates = [table for table in tables if table.get("rows") and table.get("columns")]
    if not candidates:
        return None

    def score(table):
        numeric = numeric_columns(table["columns"], table["rows"])
        matches = sum(
            any(term in column for column in numeric)
            for term in ("金额", "数量", "达成", "目标", "同比", "环比")
            if term in question
        )
        return matches, min(len(numeric), 8), min(len(table["rows"]), 120)

    primary = max(candidates, key=score)
    try:
        return build_analysis_bundle(primary, question=question)
    except ValidationFailed:
        return None
