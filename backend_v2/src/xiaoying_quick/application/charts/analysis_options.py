"""ECharts views over one consistent, verified analysis grid."""

from __future__ import annotations

import re
from collections import defaultdict

from xiaoying_quick.application.charts.analysis_metrics import Metric, data_payload, metric_value
from xiaoying_quick.application.charts.builder import (
    _LEGEND,
    _base_option,
    _category_axis,
    _value_axis,
)

MAX_CATEGORIES = 120


def _option(title: str) -> dict:
    option = _base_option(chart_type="bar", title=title)
    option["tooltip"].update(trigger="axis", renderMode="richText", confine=True)
    option["grid"].update(top=95, bottom=55)
    option["legend"] = {**_LEGEND, "top": 38, "bottom": None, "width": "94%"}
    return option


def _plot_value(value, metric: Metric):
    return None if value is None else round(value * (100 if metric.unit == "%" else 1), 6)


def cartesian(title: str, grid: list[list], metrics: list[Metric], mode: str) -> dict:
    rows = grid[:MAX_CATEGORIES]
    option = _option(title)
    units = list(dict.fromkeys(metric.unit for metric in metrics))
    axes = []
    for index, unit in enumerate(units):
        axis = _value_axis()
        axis.update(
            name=unit or "数值",
            position="left" if index == 0 else "right",
            offset=max(0, index - 1) * 65,
        )
        if unit == "%":
            axis["axisLabel"]["formatter"] = "{value}%"
        if index:
            axis["splitLine"] = {"show": False}
        axes.append(axis)
    option["yAxis"] = axes
    option["xAxis"] = _category_axis([row[0] for row in rows])
    option["grid"]["right"] = 30 if len(axes) == 1 else 85 if len(axes) == 2 else 145
    series = []
    for index, metric in enumerate(metrics):
        kind = metric.chart if mode == "combo" else "line" if mode in {"line", "area"} else "bar"
        item = {
            "name": metric.column,
            "type": kind,
            "yAxisIndex": units.index(metric.unit),
            "data": [_plot_value(row[index + 1], metric) for row in rows],
            "barMaxWidth": 30,
            "smooth": False,
            "connectNulls": False,
            "symbolSize": 6,
            "emphasis": {"focus": "series"},
            "label": {"show": False, "formatter": "{c}%" if metric.unit == "%" else "{c}"},
        }
        if mode == "area":
            item["areaStyle"] = {"opacity": 0.12}
        if metric.unit == "%" and "达成" in metric.column:
            item["markLine"] = {
                "silent": True,
                "symbol": "none",
                "data": [{"yAxis": 100}],
                "label": {"formatter": "目标 100%"},
                "lineStyle": {"type": "dashed", "color": "#a7a9b3"},
            }
        series.append(item)
    option["series"] = series
    if len(rows) > 12:
        option["grid"]["bottom"] = 85
        option["dataZoom"] = [
            {"type": "inside", "xAxisIndex": 0},
            {
                "type": "slider",
                "height": 18,
                "bottom": 15,
                "start": 0,
                "end": min(100, 24 / len(rows) * 100),
            },
        ]
    return option


def _single_metric(grid: list[list], metrics: list[Metric]) -> tuple[Metric, list[list]] | None:
    for index, metric in enumerate(metrics):
        if metric.aggregate == "sum" and metric.unit != "%":
            return metric, [[row[0], row[index + 1]] for row in grid if row[index + 1] is not None]
    return None


def _distribution(title: str, rows: list[list], donut: bool) -> dict:
    option = _option(title)
    option.pop("grid", None)
    option["tooltip"]["trigger"] = "item"
    option["legend"] = {**_LEGEND, "bottom": 0, "width": "94%"}
    option["series"] = [
        {
            "type": "pie",
            "radius": ["42%", "65%"] if donut else "62%",
            "center": ["50%", "47%"],
            "avoidLabelOverlap": True,
            "label": {"show": True, "formatter": "{b}\n{d}%"},
            "labelLayout": {"hideOverlap": True},
            "data": [{"name": name, "value": value} for name, value in rows],
        }
    ]
    return option


def _breakdown(table: dict, dimension: str, metrics: list[Metric]) -> str | None:
    excluded = {metric.column for metric in metrics} | {dimension}
    for name in table["columns"]:
        if name in excluded or not re.search(
            r"城市|区域|大区|渠道|产品|药品名称|治疗领域|终端类型|品牌", name
        ):
            continue
        return name
    return None


def breakdown_views(table: dict, dimension: str, metric: Metric) -> list[dict]:
    secondary = _breakdown(table, dimension, [metric])
    if not secondary or dimension not in table["columns"]:
        return []
    columns = table["columns"]
    xi, yi = columns.index(dimension), columns.index(secondary)
    groups = defaultdict(list)
    for row in table["rows"]:
        groups[(str(row[xi]), str(row[yi]))].append(row)
    categories = sorted({pair[0] for pair in groups})[:MAX_CATEGORIES]
    names = sorted({pair[1] for pair in groups})
    points = [(x, y, metric_value(metric, rows, columns)) for (x, y), rows in groups.items()]
    if not names or len(names) > 30:
        return []
    heatmap = _option(f"{dimension}与{secondary} · {metric.column}")
    heatmap.pop("legend", None)
    heatmap["tooltip"]["trigger"] = "item"
    heatmap["grid"].update(top=65, bottom=90)
    heatmap["xAxis"] = _category_axis(categories)
    heatmap["yAxis"] = _category_axis(names)
    values = [value for _, _, value in points if value is not None]
    heatmap["visualMap"] = {
        "min": min(values, default=0),
        "max": max(values, default=1),
        "calculable": True,
        "orient": "horizontal",
        "bottom": 10,
        "left": "center",
        "inRange": {"color": ["#f7eff2", "#c5203f", "#79182d"]},
    }
    heatmap["series"] = [
        {
            "name": metric.column,
            "type": "heatmap",
            "data": [
                [categories.index(x), names.index(y), value]
                for x, y, value in points
                if x in categories and value is not None
            ],
        }
    ]
    source = data_payload(
        [dimension, secondary, metric.column], [[x, y, value] for x, y, value in points], [metric]
    )
    result = [{"type": "heatmap", "label": "热力图", "option": heatmap, "data": source}]
    if (
        metric.aggregate != "sum"
        or len(names) > 12
        or any(value is None or value < 0 for value in values)
    ):
        return result
    for kind, label in (("stacked_bar", "堆叠柱图"), ("stacked_area", "堆叠面积")):
        option = _option(f"{metric.column} · {secondary}构成")
        option["xAxis"] = _category_axis(categories)
        option["yAxis"] = {**_value_axis(), "name": metric.unit or "数值"}
        option["series"] = []
        for name in names:
            by_category = {x: value for x, y, value in points if y == name}
            series = {
                "name": name,
                "type": "bar" if kind == "stacked_bar" else "line",
                "stack": "composition",
                "data": [by_category.get(x, 0) for x in categories],
                "emphasis": {"focus": "series"},
                "barMaxWidth": 40,
            }
            if kind == "stacked_area":
                series["areaStyle"] = {"opacity": 0.7}
            option["series"].append(series)
        result.append({"type": kind, "label": label, "option": option, "data": source})
    return result


def build_views(
    table: dict, dimension: str, grid: list[list], metrics: list[Metric], title: str
) -> list[dict]:
    result = []

    def add(kind: str, label: str, option: dict, **extra) -> None:
        result.append({"type": kind, "label": label, "option": option, **extra})

    add("combo", "柱线复合", cartesian(title, grid, metrics, "combo"))
    bar_metrics = [metric for metric in metrics if metric.unit != "%"]
    if bar_metrics:
        bar_grid = [
            [row[0], *(row[metrics.index(metric) + 1] for metric in bar_metrics)] for row in grid
        ]
        add("grouped_bar", "多指标柱图", cartesian(title, bar_grid, bar_metrics, "bar"))
    add("line", "多指标折线", cartesian(title, grid, metrics, "line"))
    selection = _single_metric(grid, metrics)
    if selection:
        primary, values = selection
        ranked = sorted(values, key=lambda row: -(row[1] or 0))
        option = _option(f"{primary.column} · 排名")
        option.pop("legend", None)
        option["xAxis"] = {**_value_axis(), "name": primary.unit or "数值"}
        option["yAxis"] = {**_category_axis([row[0] for row in ranked[:30]]), "inverse": True}
        option["series"] = [
            {
                "name": primary.column,
                "type": "bar",
                "barMaxWidth": 24,
                "data": [row[1] for row in ranked[:30]],
                "label": {"show": False},
            }
        ]
        add(
            "horizontal_bar",
            "排名条形",
            option,
            data=data_payload([dimension, primary.column], ranked, [primary]),
            note="图形展示前30个分组，表格保留完整排名预览。" if len(ranked) > 30 else "",
        )
        same_unit = [
            metric
            for metric in metrics
            if metric.unit == primary.unit and metric.aggregate == "sum"
        ]
        area_grid = [
            [row[0], *(row[metrics.index(metric) + 1] for metric in same_unit)] for row in grid
        ]
        add("area", "面积趋势", cartesian(title, area_grid, same_unit, "area"))
        if (
            values
            and all(value >= 0 for _, value in values)
            and sum(value for _, value in values) > 0
        ):
            if len(values) <= 30:
                add("pie", "饼图", _distribution(f"{primary.column}构成", values, False))
                add("donut", "环形图", _distribution(f"{primary.column}构成", values, True))
            total, cumulative = sum(value for _, value in ranked), 0
            pareto_rows = []
            for name, value in ranked:
                cumulative += value
                pareto_rows.append([name, value, cumulative / total])
            share = Metric("累计贡献率", "%", "line", "ratio")
            add(
                "pareto",
                "帕累托",
                cartesian(f"{primary.column}与累计贡献", pareto_rows, [primary, share], "combo"),
                data=data_payload(
                    [dimension, primary.column, "累计贡献率"], pareto_rows, [primary, share]
                ),
            )
        result.extend(breakdown_views(table, dimension, primary))
    if len(metrics) >= 2:
        x = next((metric for metric in metrics if metric.unit != "%"), metrics[0])
        y = next(
            (metric for metric in metrics if metric.unit == "%" and metric != x),
            next(metric for metric in metrics if metric != x),
        )
        xi, yi = metrics.index(x) + 1, metrics.index(y) + 1
        for bubble in (False, True):
            size_metric = next(
                (metric for metric in metrics if metric not in (x, y) and metric.unit == "盒"),
                next((metric for metric in metrics if metric not in (x, y)), None),
            )
            if bubble and size_metric is None:
                continue
            option = _option(f"{x.column}与{y.column}")
            option.pop("legend", None)
            option["tooltip"]["trigger"] = "item"
            axes = []
            for metric in (x, y):
                axis = _value_axis()
                axis.update(name=metric.column, nameLocation="middle", nameGap=35, scale=True)
                if metric.unit == "%":
                    axis["axisLabel"]["formatter"] = "{value}%"
                axes.append(axis)
            option["xAxis"], option["yAxis"] = axes
            option["grid"].update(top=65, bottom=75, left=70, right=45)
            points = []
            for row in grid[:MAX_CATEGORIES]:
                if row[xi] is None or row[yi] is None:
                    continue
                point = [_plot_value(row[xi], x), _plot_value(row[yi], y)]
                if bubble:
                    point.append(max(0, row[metrics.index(size_metric) + 1] or 0))
                points.append({"name": row[0], "value": point})
            option["series"] = [
                {
                    "type": "scatter",
                    "name": dimension,
                    "data": points,
                    "symbolSize": 12,
                    "itemStyle": {"opacity": 0.78},
                }
            ]
            if bubble:
                sizes = [point["value"][2] for point in points]
                option["visualMap"] = {
                    "show": False,
                    "dimension": 2,
                    "min": min(sizes, default=0),
                    "max": max(sizes, default=1),
                    "inRange": {"symbolSize": [12, 46]},
                }
            add("bubble" if bubble else "scatter", "气泡图" if bubble else "散点图", option)
    money = [metric for metric in metrics if metric.unit == "元" and metric.aggregate == "sum"]
    if (
        len(money) >= 3
        and grid
        and all(
            row[metrics.index(metric) + 1] is not None and row[metrics.index(metric) + 1] >= 0
            for row in grid
            for metric in money
        )
    ):
        radar = _option("多指标组合结构")
        radar.pop("grid", None)
        radar["tooltip"]["trigger"] = "item"
        radar["legend"].update(top=None, bottom=0)
        radar["radar"] = {
            "center": ["50%", "52%"],
            "radius": "58%",
            "indicator": [
                {
                    "name": metric.column,
                    "max": max(1, max(row[metrics.index(metric) + 1] or 0 for row in grid) * 1.1),
                }
                for metric in money[:6]
            ],
        }
        radar["series"] = [
            {
                "type": "radar",
                "data": [
                    {
                        "name": row[0],
                        "value": [row[metrics.index(metric) + 1] for metric in money[:6]],
                    }
                    for row in grid[:6]
                ],
            }
        ]
        add("radar", "雷达图", radar, note="各指标使用独立刻度，仅比较结构。图形展示前6个分组。")
    return result
