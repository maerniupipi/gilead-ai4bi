"""Metric semantics and aggregation for verified Excel analysis results."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from typing import Any

from xiaoying_quick.shared.errors import ValidationFailed

MAX_DATA_ROWS = 1000
MAX_METRICS = 8
_TOTAL = re.compile(r"^(?:全国|总体|所有|全部)?(?:合计|总计|汇总)$")


def number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        text = str(value).strip().replace(",", "")
        result = float(text.removesuffix("%"))
        if text.endswith("%"):
            result /= 100
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def metric_unit(column: str) -> str:
    if re.search(r"率|同比|环比|占比|比例|%|percent|rate|margin", column, re.I):
        return "%"
    if re.search(
        r"金额|销售额|收入|成本|毛利|费用|单价|元|amount|revenue|cost|price", column, re.I
    ):
        return "元"
    if re.search(r"终端(?:数|数量)|机构(?:数|数量)|客户(?:数|数量)", column):
        return "家"
    if "记录数" in column:
        return "条"
    if re.search(r"数量|销量|盒|qty|volume|quantity", column, re.I):
        return "盒"
    if re.search(r"数|count", column, re.I):
        return "个"
    return ""


def numeric_columns(columns: list[str], rows: list[list]) -> list[str]:
    result = []
    for index, column in enumerate(columns):
        if re.search(r"编码|代码|年份|月份|序号|(?:^|_)id$|code|year|month", column, re.I):
            continue
        values = [row[index] for row in rows[:80] if index < len(row) and row[index] is not None]
        if (values and all(number(value) is not None for value in values)) or (
            not values and metric_unit(column) in {"%", "元", "盒", "家", "条"}
        ):
            result.append(column)
    return result


@dataclass(frozen=True)
class Metric:
    column: str
    unit: str
    chart: str
    aggregate: str
    numerator: str | None = None
    denominator: str | None = None
    scale: str = "fraction"


def _find(columns: list[str], pattern: str, exclude: str = "a^") -> str | None:
    return next(
        (
            name
            for name in columns
            if re.search(pattern, name, re.I) and not re.search(exclude, name, re.I)
        ),
        None,
    )


def infer_metric(column: str, columns: list[str], config: dict | None = None) -> Metric:
    config = config or {}
    unit = str(config.get("unit") or metric_unit(column))[:12]
    numerator, denominator = config.get("numerator"), config.get("denominator")
    aggregate = str(config.get("aggregate") or "sum")
    if unit == "%":
        aggregate = str(config.get("aggregate") or "ratio")
        if aggregate == "sum":
            raise ValidationFailed("比率不能直接相加，请提供同范围分子和分母")
        actual = _find(
            columns,
            r"销售金额|销售额|实际金额|amount|revenue",
            r"目标|同期|去年|上年|上期|上月|prior|previous|target",
        )
        if "达成" in column:
            if re.search(r"数量|销量", column):
                numerator = numerator or _find(columns, r"销售数量|销量|实际数量", r"目标")
                denominator = denominator or _find(columns, r"目标数量|数量目标|目标销量")
            else:
                numerator = numerator or actual
                denominator = denominator or _find(columns, r"目标金额|目标额|金额目标|target")
        elif "毛利率" in column:
            numerator = numerator or _find(columns, r"毛利", r"率")
            denominator = denominator or actual
        elif "费用率" in column:
            numerator = numerator or _find(columns, r"费用", r"率")
            denominator = denominator or actual
        elif re.search(r"同比|环比|yoy|mom", column, re.I):
            quantity = bool(re.search(r"数量|销量|盒|qty|volume|quantity", column, re.I))
            numerator = numerator or (
                _find(
                    columns,
                    r"销售数量|销量|实际数量|qty|quantity",
                    r"目标|同期|上期|去年|上年|上月|prior|previous",
                )
                if quantity
                else actual
            )
            pattern = (
                r"同期|去年|上年|prior"
                if re.search(r"同比|yoy", column, re.I)
                else r"上期|上月|previous"
            )
            denominator = denominator or _find(
                columns,
                pattern,
                r"率|增量|变化|差额|金额|销售额" if quantity else r"率|增量|变化|差额|数量|销量",
            )
            if not config.get("aggregate"):
                aggregate = "growth"
    elif re.search(r"终端数|机构数|客户数|患者数|产品数|城市数|去重|distinct", column, re.I):
        aggregate = str(config.get("aggregate") or "distinct")
    elif re.search(r"单价|均价|price", column, re.I):
        aggregate = str(config.get("aggregate") or "ratio")
        numerator = numerator or _find(
            columns, r"销售金额|销售额|amount|revenue", r"目标|同期|上期"
        )
        denominator = denominator or _find(
            columns, r"销售数量|销量|qty|quantity", r"目标|同期|上期"
        )
    for dependency in (numerator, denominator):
        if dependency and dependency not in columns:
            raise ValidationFailed(f"指标「{column}」引用了不存在的字段「{dependency}」")
    if aggregate not in {"sum", "ratio", "growth", "distinct"}:
        raise ValidationFailed("指标汇总方式必须是 sum、ratio、growth 或 distinct")
    default_chart = (
        "line"
        if unit == "%"
        else "kpi"
        if re.search(r"记录数|终端数|机构数|客户数|去重", column)
        else "bar"
    )
    chart = str(config.get("chart") or default_chart)
    if chart not in {"bar", "line", "kpi"}:
        raise ValidationFailed("指标类型必须是 bar、line 或 kpi")
    scale = str(config.get("scale") or "fraction")
    if scale not in {"fraction", "percent"}:
        raise ValidationFailed("比率数据格式必须是 fraction 或 percent")
    return Metric(column, unit, chart, aggregate, numerator, denominator, scale)


def metrics_for(table: dict, requested: list[dict] | None = None) -> list[Metric]:
    columns, rows = table["columns"], table["rows"]
    numeric = numeric_columns(columns, rows)
    configs = requested or [{"column": name} for name in numeric[:MAX_METRICS]]
    if len(configs) > MAX_METRICS:
        raise ValidationFailed("一张复合图最多展示8个指标，请聚焦主要指标")
    metrics = []
    seen = set()
    for config in configs:
        column = str(config.get("column") or "")
        if column not in numeric:
            raise ValidationFailed(f"「{column}」不是本次查询的有效数值字段")
        if column in seen:
            raise ValidationFailed("复合图指标不能重复")
        metrics.append(infer_metric(column, columns, config))
        seen.add(column)
    if not metrics:
        raise ValidationFailed("查询中没有可展示的数值指标")
    if not any(metric.chart != "kpi" for metric in metrics):
        metrics = [replace(metric, chart="bar") for metric in metrics]
    if len({metric.unit for metric in metrics if metric.chart != "kpi"}) > 3:
        raise ValidationFailed("图表最多支持三类单位，请减少指标或统一口径")
    return metrics


def metric_value(metric: Metric, rows: list[list], columns: list[str]) -> float | None:
    if not rows:
        return None
    if metric.numerator and metric.denominator:
        if metric.numerator not in columns or metric.denominator not in columns:
            return None
        parts = []
        for name in (metric.numerator, metric.denominator):
            index = columns.index(name)
            values = [number(row[index]) for row in rows]
            if any(value is None for value in values):
                return None
            parts.append(sum(values))
        return None if not parts[1] else parts[0] / parts[1] - (metric.aggregate == "growth")
    if metric.column not in columns:
        return None
    index = columns.index(metric.column)
    values = [number(row[index]) for row in rows]
    if any(value is None for value in values):
        return None
    if metric.aggregate == "sum":
        return sum(values)
    if len(values) == 1:
        explicit_percent = str(rows[0][index]).strip().endswith("%")
        return values[0] / (
            100 if metric.unit == "%" and metric.scale == "percent" and not explicit_percent else 1
        )
    return None


def dimension_for(table: dict, requested: str | None, question: str) -> str:
    columns, rows = table["columns"], table["rows"]
    if requested:
        if requested not in columns:
            raise ValidationFailed("图表分组字段不在本次查询结果中")
        return requested
    if re.search(r"趋势|月度|月份|同比|环比|季度|时间", question):
        found = _find(columns, r"月份|日期|年月|month|date|period")
        if found:
            return found
    categorical = [name for name in columns if name not in numeric_columns(columns, rows)]
    return next(
        (name for name in categorical if name in question),
        categorical[0] if categorical else "统计范围",
    )


def detail_rows(table: dict, dimension: str) -> list[list]:
    rows = table["rows"]
    if dimension not in table["columns"] or len(rows) <= 1:
        return rows
    index = table["columns"].index(dimension)
    return [row for row in rows if not _TOTAL.fullmatch(str(row[index]))]


def aggregate_grid(
    table: dict, dimension: str, metrics: list[Metric]
) -> tuple[list[list], list[str]]:
    columns, rows = table["columns"], table["rows"]
    index = columns.index(dimension) if dimension in columns else None
    groups: dict[str, list] = defaultdict(list)
    warnings = []
    cleaned = detail_rows(table, dimension)
    if len(cleaned) < len(rows):
        warnings.append("已排除明细中的合计行，避免重复汇总")
    for row in cleaned:
        label = str(row[index] if index is not None else "当前范围")
        groups[label].append(row)
    grid = [
        [label, *(metric_value(metric, values, columns) for metric in metrics)]
        for label, values in groups.items()
    ]
    if re.search(r"月|日|年|month|date|period", dimension, re.I):
        grid.sort(key=lambda row: row[0])
    return grid, list(dict.fromkeys(warnings))


def data_payload(
    columns: list[str], rows: list[list], metrics: list[Metric], *, truncated=False, raw=False
) -> dict:
    preview = []
    byte_count = 0
    for row in rows[:MAX_DATA_ROWS]:
        byte_count += len(json.dumps(row, ensure_ascii=False, default=str).encode())
        if byte_count > 300_000:
            break
        preview.append(row)
    return {
        "columns": columns,
        "rows": preview,
        "row_count": len(rows),
        "preview_truncated": len(rows) > len(preview),
        "query_truncated": bool(truncated),
        "formats": {
            metric.column: {
                "unit": metric.unit,
                "percent": metric.unit == "%",
                "scale": metric.scale if raw else "fraction",
            }
            for metric in metrics
        },
    }


def build_kpis(
    table: dict, dimension: str, metrics: list[Metric], summary: dict | None
) -> list[dict]:
    source = summary or table
    rows = source["rows"]
    columns = source["columns"]
    rows = detail_rows(source, dimension)
    kpis = []
    for metric in metrics:
        if summary and metric.column in columns:
            value = number(rows[0][columns.index(metric.column)])
            if (
                metric.unit == "%"
                and metric.scale == "percent"
                and value is not None
                and not str(rows[0][columns.index(metric.column)]).strip().endswith("%")
            ):
                value /= 100
        else:
            value = metric_value(metric, rows, columns)
        if source.get("truncated"):
            value = None
        kpis.append(
            {
                "label": metric.column,
                "value": value,
                "unit": metric.unit,
                "note": "查询结果已截断，需补充总体汇总"
                if source.get("truncated")
                else "需同范围分子分母或总体去重汇总"
                if value is None
                else "当前查询范围",
            }
        )
    if summary:
        for column in numeric_columns(columns, rows):
            if len(kpis) >= MAX_METRICS:
                break
            if column in {metric.column for metric in metrics} or not re.search(
                r"记录数|终端数|机构数|产品数|城市数|客户数", column
            ):
                continue
            kpis.append(
                {
                    "label": column,
                    "value": number(rows[0][columns.index(column)]),
                    "unit": metric_unit(column),
                    "note": "当前查询范围",
                }
            )
    return kpis


def metric_records(metrics: list[Metric]) -> list[dict]:
    return [asdict(metric) for metric in metrics]
