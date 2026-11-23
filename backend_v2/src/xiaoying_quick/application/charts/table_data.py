"""Resolve displayed data from current and historical chart snapshots."""

from __future__ import annotations

from copy import deepcopy

from xiaoying_quick.application.charts.analysis_metrics import data_payload
from xiaoying_quick.shared.errors import NotFound


def chart_table_data(bundle: dict, chart: dict, view: str = "chart") -> dict:
    if view == "details":
        if not bundle.get("details", {}).get("columns"):
            raise NotFound("此图表没有已保存的查询明细")
        return deepcopy(bundle["details"])
    for data in (chart.get("data"), bundle.get("data")):
        if data and data.get("columns"):
            return deepcopy(data)
    option = chart.get("option", {})
    series = option.get("series", [])
    x = option.get("xAxis", {})
    y = option.get("yAxis", {})
    x = x[0] if isinstance(x, list) and x else x
    y = y[0] if isinstance(y, list) and y else y
    x, y = x or {}, y or {}
    if series and series[0].get("type") == "heatmap":
        rows = [
            [x.get("data", [])[point[0]], y.get("data", [])[point[1]], point[2]]
            for point in series[0].get("data", [])
        ]
        return data_payload([x.get("name") or "横轴", y.get("name") or "纵轴", "数值"], rows, [])
    if series and series[0].get("type") == "radar":
        names = [item.get("name", "") for item in option.get("radar", {}).get("indicator", [])]
        rows = [
            [point.get("name", ""), *point.get("value", [])]
            for item in series
            for point in item.get("data", [])
        ]
        return data_payload(["类别", *names], rows, [])
    category = next((axis for axis in (x, y) if axis.get("data")), None)
    if category and series:
        columns = [
            "类别",
            *(item.get("name") or f"指标{index + 1}" for index, item in enumerate(series)),
        ]
        rows = []
        for index, label in enumerate(category["data"]):
            values = [
                item.get("data", [])[index] if index < len(item.get("data", [])) else None
                for item in series
            ]
            rows.append(
                [
                    label,
                    *(value.get("value") if isinstance(value, dict) else value for value in values),
                ]
            )
        return data_payload(columns, rows, [])
    rows = []
    for item in series:
        for index, point in enumerate(item.get("data", [])):
            value = point.get("value") if isinstance(point, dict) else point
            name = point.get("name", str(index + 1)) if isinstance(point, dict) else str(index + 1)
            values = value if isinstance(value, list) else [value]
            rows.append([name, *values])
    width = max((len(row) - 1 for row in rows), default=1)
    values = (
        ["数值"]
        if width == 1
        else [
            x.get("name") or "X",
            y.get("name") or "Y",
            *[f"数值{i + 1}" for i in range(2, width)],
        ]
    )
    return data_payload(["类别", *values], rows, [])
