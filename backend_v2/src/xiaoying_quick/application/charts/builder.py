"""Build compact ECharts options from a judged chart spec + analysis table.

Visual language: 清新浅色 — unified primary, soft gradients, airy layout.
No default rainbow palette, no 3D, no heavy borders/shadows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from xiaoying_quick.application.charts.judge import CHART_TYPES

_CHART_LABELS: dict[str, str] = {
    "bar": "柱状图",
    "line": "折线图",
    "pie": "饼图",
    "progress": "进度图",
    "heatmap": "热力图",
    "scatter": "散点图",
    "area": "面积图",
    "radar": "雷达图",
    "funnel": "漏斗图",
    "stacked_bar": "堆叠柱状图",
}

# Colorblind-friendly: blue–teal primary + amber accent + muted slate secondaries.
# Avoid red/green-only contrasts and ECharts default rainbow.
_PRIMARY = "#C5203F"
_PRIMARY_DEEP = "#881222"
_ACCENT = "#3FB9C2"
_MUTED = ("#94A3B8", "#CBD5E1", "#64748B", "#A8B3C2", "#7C8A9A", "#B6C0CC")
_PALETTE = (
    _PRIMARY,
    _ACCENT,
    "#128A89",
    "#77A5B3",
    "#64748B",
    "#94A3B8",
    "#0F766E",
    "#D97706",
)
_FONT = "Avenir Next, 'Helvetica Neue', -apple-system, 'Segoe UI', 'PingFang SC', 'Noto Sans SC', sans-serif"
_MAX_CHART_ROWS = 60

_AXIS_LABEL = {
    "color": "#94A3B8",
    "fontSize": 11,
    "fontFamily": _FONT,
}
_AXIS_LINE = {"show": False}
_AXIS_TICK = {"show": False}
_SPLIT_LINE = {
    "show": True,
    "lineStyle": {"color": "rgba(148, 163, 184, 0.22)", "width": 1, "type": "dashed"},
}

# Light tooltip (清新浅色) — rounded, airy padding, no dark glass.
_TOOLTIP_BASE = {
    "backgroundColor": "rgba(255, 255, 255, 0.96)",
    "borderColor": "rgba(148, 163, 184, 0.28)",
    "borderWidth": 1,
    "padding": [12, 16],
    "textStyle": {"color": "#334155", "fontSize": 12, "fontFamily": _FONT},
    "extraCssText": (
        "border-radius:12px;box-shadow:0 8px 24px rgba(15,23,42,.08);"
        "backdrop-filter:blur(6px);"
    ),
}
_TOOLTIP_AXIS = {
    **_TOOLTIP_BASE,
    "trigger": "axis",
    "axisPointer": {
        "type": "shadow",
        "shadowStyle": {"color": "rgba(14, 165, 233, 0.06)"},
    },
}
_TOOLTIP_ITEM = {**_TOOLTIP_BASE, "trigger": "item"}

_SOFT_SHADOW = {
    "shadowBlur": 8,
    "shadowColor": "rgba(14, 165, 233, 0.16)",
    "shadowOffsetY": 3,
}

_LEGEND = {
    "orient": "horizontal",
    "bottom": 0,
    "left": "center",
    "icon": "circle",
    "itemWidth": 8,
    "itemHeight": 8,
    "itemGap": 14,
    "type": "scroll",
    "textStyle": {"color": "#64748B", "fontSize": 11, "fontFamily": _FONT},
    "pageIconColor": _PRIMARY,
    "pageTextStyle": {"color": "#94A3B8"},
}


def build_chart_payload(
    *,
    judged: Mapping[str, Any],
    table: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return chart.ready payload or None to skip silently."""

    if not judged.get("suitable"):
        return None
    charts_spec = judged.get("charts")
    if not isinstance(charts_spec, list) or len(charts_spec) != 3:
        return None
    columns = [str(column) for column in (table.get("columns") or [])]
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    if not columns or not rows:
        return None
    clipped = [list(row) if isinstance(row, (list, tuple)) else [row] for row in rows[:_MAX_CHART_ROWS]]
    built: list[dict[str, Any]] = []
    for spec in charts_spec:
        if not isinstance(spec, Mapping):
            return None
        chart_type = str(spec.get("type") or "")
        if chart_type not in CHART_TYPES:
            return None
        mapping = spec.get("mapping") if isinstance(spec.get("mapping"), Mapping) else {}
        option = _build_option(
            chart_type=chart_type,
            title=str(spec.get("title") or "")[:120],
            mapping=mapping,
            columns=columns,
            rows=clipped,
        )
        if option is None:
            return None
        built.append(
            {
                "type": chart_type,
                "label": _CHART_LABELS.get(chart_type, chart_type),
                "option": option,
            }
        )
    if len(built) != 3:
        return None
    return {
        "default_type": built[0]["type"],
        "charts": built,
    }


def _col_index(columns: Sequence[str], name: str) -> int | None:
    needle = str(name or "").strip()
    if not needle:
        return None
    for index, column in enumerate(columns):
        if column == needle:
            return index
    lowered = needle.casefold()
    for index, column in enumerate(columns):
        if column.casefold() == lowered:
            return index
    return None


def _resolve_xy(
    columns: Sequence[str],
    mapping: Mapping[str, Any],
) -> tuple[int, int] | None:
    x_idx = _col_index(columns, str(mapping.get("x") or ""))
    y_idx = _col_index(columns, str(mapping.get("y") or ""))
    if x_idx is None or y_idx is None:
        if len(columns) >= 2:
            return 0, 1
        return None
    return x_idx, y_idx


def _as_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _categories_and_values(
    rows: Sequence[Sequence[Any]],
    x_idx: int,
    y_idx: int,
) -> tuple[list[str], list[float]]:
    categories: list[str] = []
    values: list[float] = []
    for row in rows:
        if max(x_idx, y_idx) >= len(row):
            continue
        number = _as_number(row[y_idx])
        if number is None:
            continue
        categories.append(str(row[x_idx]))
        values.append(number)
    return categories, values


def _fade(hex_color: str, alpha: float) -> str:
    text = hex_color.lstrip("#")
    if len(text) != 6:
        return hex_color
    red = int(text[0:2], 16)
    green = int(text[2:4], 16)
    blue = int(text[4:6], 16)
    return f"rgba({red}, {green}, {blue}, {alpha:.2f})"


def _linear_gradient(top: str, bottom: str | None = None) -> dict[str, Any]:
    return {
        "type": "linear",
        "x": 0,
        "y": 0,
        "x2": 0,
        "y2": 1,
        "colorStops": [
            {"offset": 0, "color": top},
            {"offset": 1, "color": bottom or _fade(top, 0.55)},
        ],
    }


def _area_fill(color: str) -> dict[str, Any]:
    return {
        "color": {
            "type": "linear",
            "x": 0,
            "y": 0,
            "x2": 0,
            "y2": 1,
            "colorStops": [
                {"offset": 0, "color": _fade(color, 0.28)},
                {"offset": 1, "color": _fade(color, 0.02)},
            ],
        }
    }


def _series_color(index: int, *, highlight: bool = False) -> str:
    if highlight or index == 0:
        return _PRIMARY if index == 0 else _ACCENT if index == 1 else _PALETTE[index % len(_PALETTE)]
    if index < 2:
        return _PALETTE[index]
    return _MUTED[(index - 2) % len(_MUTED)]


def _category_axis(categories: Sequence[str], *, rotate: bool | None = None) -> dict[str, Any]:
    should_rotate = len(categories) > 6 if rotate is None else rotate
    return {
        "type": "category",
        "data": list(categories),
        "axisLabel": {
            **_AXIS_LABEL,
            "interval": 0,
            "rotate": 28 if should_rotate else 0,
            "hideOverlap": True,
        },
        "axisLine": _AXIS_LINE,
        "axisTick": _AXIS_TICK,
    }


def _value_axis() -> dict[str, Any]:
    return {
        "type": "value",
        "axisLabel": dict(_AXIS_LABEL),
        "axisLine": _AXIS_LINE,
        "axisTick": _AXIS_TICK,
        "splitLine": dict(_SPLIT_LINE),
        "splitNumber": 4,
    }


def _base_option(*, chart_type: str, title: str) -> dict[str, Any]:
    return {
        "color": list(_PALETTE),
        "textStyle": {"fontFamily": _FONT, "color": "#475569"},
        "animation": True,
        "animationDuration": 720,
        "animationEasing": "cubicOut",
        "animationDurationUpdate": 360,
        "animationEasingUpdate": "cubicInOut",
        "title": {
            "text": title or _CHART_LABELS.get(chart_type, ""),
            "left": "left",
            "top": 4,
            "padding": [4, 0, 0, 4],
            "textStyle": {
                "fontSize": 15,
                "fontWeight": 600,
                "color": "#0F172A",
                "fontFamily": _FONT,
            },
        },
        "tooltip": dict(_TOOLTIP_ITEM),
        # Airy grid — more whitespace around the plot.
        "grid": {"left": 28, "right": 20, "top": 56, "bottom": 28, "containLabel": True},
    }


def _build_option(
    *,
    chart_type: str,
    title: str,
    mapping: Mapping[str, Any],
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> dict[str, Any] | None:
    xy = _resolve_xy(columns, mapping)
    if xy is None:
        return None
    x_idx, y_idx = xy
    categories, values = _categories_and_values(rows, x_idx, y_idx)
    if not categories:
        return None
    base = _base_option(chart_type=chart_type, title=title)
    builders = {
        "bar": _option_bar,
        "line": _option_line,
        "pie": _option_pie,
        "progress": _option_progress,
        "heatmap": _option_heatmap,
        "scatter": _option_scatter,
        "area": _option_area,
        "radar": _option_radar,
        "funnel": _option_funnel,
        "stacked_bar": _option_stacked_bar,
    }
    builder = builders.get(chart_type)
    if builder is None:
        return None
    return builder(base, categories, values, columns=columns, rows=rows, mapping=mapping, x_idx=x_idx, y_idx=y_idx)


def _option_bar(base, categories, values, **_kwargs):
    option = dict(base)
    option["tooltip"] = {
        **_TOOLTIP_AXIS,
        "valueFormatter": None,
    }
    option["xAxis"] = _category_axis(categories)
    option["yAxis"] = _value_axis()
    # Highlight max bar; mute the rest for focus hierarchy.
    peak = max(values) if values else None
    data = []
    for value in values:
        item: dict[str, Any] = {"value": value}
        if peak is not None and value == peak:
            item["itemStyle"] = {
                "borderRadius": [8, 8, 2, 2],
                "color": _linear_gradient(_PRIMARY, _PRIMARY_DEEP),
                **_SOFT_SHADOW,
            }
        else:
            item["itemStyle"] = {
                "borderRadius": [8, 8, 2, 2],
                "color": _linear_gradient("#7DD3FC", "#128A89"),
                "opacity": 0.78,
            }
        data.append(item)
    option["series"] = [
        {
            "type": "bar",
            "data": data,
            "barMaxWidth": 36,
            "barCategoryGap": "48%",
            "animationDuration": 650,
            "animationEasing": "cubicOut",
            "emphasis": {
                "focus": "self",
                "itemStyle": {**_SOFT_SHADOW, "opacity": 1},
            },
            "blur": {"itemStyle": {"opacity": 0.25}},
            "label": {
                "show": len(values) <= 10,
                "position": "top",
                "color": "#64748B",
                "fontSize": 10,
                "fontFamily": _FONT,
            },
        }
    ]
    return option


def _option_line(base, categories, values, **_kwargs):
    option = dict(base)
    option["tooltip"] = {
        **_TOOLTIP_AXIS,
        "axisPointer": {
            "type": "line",
            "lineStyle": {"color": _fade(_PRIMARY, 0.35), "width": 1, "type": "dashed"},
        },
    }
    option["xAxis"] = {
        **_category_axis(categories, rotate=len(categories) > 8),
        "boundaryGap": False,
    }
    option["yAxis"] = _value_axis()
    # Longer duration + per-point delay (applied in frontend) = left-to-right draw.
    point_ms = max(60, min(120, 1400 // max(len(values), 1)))
    option["series"] = [
        {
            "type": "line",
            "data": values,
            "smooth": True,
            "symbol": "circle",
            "symbolSize": 6,
            "showSymbol": True,
            "lineStyle": {"width": 2.5, "color": _PRIMARY},
            "itemStyle": {
                "color": _PRIMARY,
                "borderColor": "#fff",
                "borderWidth": 2,
                **_SOFT_SHADOW,
            },
            "emphasis": {"focus": "series", "scale": 1.15},
            "blur": {"lineStyle": {"opacity": 0.2}, "itemStyle": {"opacity": 0.2}},
            "areaStyle": _area_fill(_PRIMARY),
            "animationDuration": max(900, point_ms * len(values)),
            "animationEasing": "linear",
            # Hint for frontend polish (ms between points).
            "_stagger_ms": point_ms,
        }
    ]
    return option


def _option_area(base, categories, values, **_kwargs):
    option = _option_line(base, categories, values)
    series = option["series"][0]
    series["areaStyle"] = {
        "color": {
            "type": "linear",
            "x": 0,
            "y": 0,
            "x2": 0,
            "y2": 1,
            "colorStops": [
                {"offset": 0, "color": _fade(_PRIMARY, 0.36)},
                {"offset": 1, "color": _fade(_PRIMARY, 0.02)},
            ],
        }
    }
    return option


def _option_pie(base, categories, values, **_kwargs):
    option = dict(base)
    option.pop("grid", None)
    option["tooltip"] = {
        **_TOOLTIP_ITEM,
        "formatter": "{b}<br/><b>{c}</b>（{d}%）",
    }
    # Always show legend so slices stay identifiable without hover.
    option["legend"] = {
        **_LEGEND,
        "data": list(categories),
        "type": "scroll",
        "orient": "horizontal",
        "bottom": 4,
        "left": "center",
        "width": "92%",
    }
    slices = [
        {
            "name": name,
            "value": value,
            "itemStyle": {
                "color": _MUTED[0],
                "borderColor": "#fff",
                "borderWidth": 2,
                "borderRadius": 6,
            },
        }
        for name, value in zip(categories, values, strict=False)
    ]
    # Largest = primary, 2nd = amber accent, rest = muted slate (no rainbow).
    ordered = sorted(range(len(values)), key=lambda i: values[i], reverse=True)
    if ordered:
        slices[ordered[0]]["itemStyle"]["color"] = _PRIMARY
    if len(ordered) > 1:
        slices[ordered[1]]["itemStyle"]["color"] = _ACCENT
    for rank, idx in enumerate(ordered[2:]):
        slices[idx]["itemStyle"]["color"] = _MUTED[rank % len(_MUTED)]

    crowded = len(categories) > 8
    option["series"] = [
        {
            "type": "pie",
            "radius": ["38%", "58%"] if crowded else ["42%", "64%"],
            "center": ["50%", "44%"],
            "data": slices,
            # Always label slices — name + percent; overlap hidden by layout.
            "label": {
                "show": True,
                "formatter": "{b}\n{d}%",
                "color": "#475569",
                "fontSize": 10 if crowded else 11,
                "fontFamily": _FONT,
                "lineHeight": 14,
                "overflow": "truncate",
            },
            "labelLine": {
                "show": True,
                "length": 12 if crowded else 14,
                "length2": 8,
                "smooth": True,
                "lineStyle": {"color": "#CBD5E1", "width": 1},
            },
            "labelLayout": {"hideOverlap": True},
            "emphasis": {
                "scale": True,
                "scaleSize": 6,
                "focus": "self",
                "itemStyle": {**_SOFT_SHADOW},
                "label": {"show": True, "fontWeight": 600, "color": "#0F172A", "fontSize": 12},
            },
            "blur": {"itemStyle": {"opacity": 0.3}, "label": {"opacity": 0.35}},
            "animationType": "expansion",
            "animationEasing": "cubicOut",
            "animationDuration": 900,
        }
    ]
    return option


def _option_progress(base, categories, values, **_kwargs):
    total = sum(values) or 1.0
    top = max(values) if values else 0.0
    ratio = max(0.0, min(100.0, (top / total) * 100.0))
    option = dict(base)
    option.pop("grid", None)
    label = categories[values.index(top)] if values else ""
    option["title"]["subtext"] = f"{label}  {ratio:.1f}%"
    option["title"]["subtextStyle"] = {
        "color": "#94A3B8",
        "fontSize": 12,
        "fontFamily": _FONT,
        "padding": [8, 0, 0, 0],
    }
    option["series"] = [
        {
            "type": "gauge",
            "min": 0,
            "max": 100,
            "startAngle": 210,
            "endAngle": -30,
            "radius": "76%",
            "center": ["50%", "58%"],
            "progress": {
                "show": True,
                "width": 14,
                "roundCap": True,
                "itemStyle": {"color": _PRIMARY},
            },
            "axisLine": {
                "roundCap": True,
                "lineStyle": {"width": 14, "color": [[1, "rgba(148, 163, 184, 0.16)"]]},
            },
            "axisTick": {"show": False},
            "splitLine": {"show": False},
            "axisLabel": {"show": False},
            "pointer": {"show": False},
            "anchor": {"show": False},
            "detail": {
                "valueAnimation": True,
                "formatter": "{value}%",
                "color": "#0F172A",
                "fontSize": 28,
                "fontWeight": 600,
                "fontFamily": _FONT,
                "offsetCenter": [0, "16%"],
            },
            "title": {
                "offsetCenter": [0, "40%"],
                "color": "#94A3B8",
                "fontSize": 12,
                "fontFamily": _FONT,
            },
            "data": [{"value": round(ratio, 1), "name": label[:20]}],
        }
    ]
    return option


def _option_scatter(base, categories, values, **_kwargs):
    option = dict(base)
    option["tooltip"] = dict(_TOOLTIP_ITEM)
    option["xAxis"] = {
        "type": "value",
        "name": "序号",
        "nameTextStyle": dict(_AXIS_LABEL),
        "axisLabel": dict(_AXIS_LABEL),
        "axisLine": _AXIS_LINE,
        "axisTick": _AXIS_TICK,
        "splitLine": dict(_SPLIT_LINE),
    }
    option["yAxis"] = _value_axis()
    option["series"] = [
        {
            "type": "scatter",
            "symbolSize": 12,
            "itemStyle": {
                "color": _fade(_PRIMARY, 0.82),
                "borderColor": "#fff",
                "borderWidth": 2,
                **_SOFT_SHADOW,
            },
            "emphasis": {"focus": "series", "scale": 1.2},
            "blur": {"itemStyle": {"opacity": 0.25}},
            "data": [[index + 1, value] for index, value in enumerate(values)],
        }
    ]
    return option


def _option_heatmap(base, categories, values, **_kwargs):
    option = dict(base)
    x_labels = categories
    y_labels = ["值"]
    data = [[index, 0, value] for index, value in enumerate(values)]
    option["tooltip"] = {**_TOOLTIP_ITEM, "position": "top"}
    option["grid"] = {"left": 28, "right": 20, "top": 56, "bottom": 64, "containLabel": True}
    option["xAxis"] = {
        "type": "category",
        "data": x_labels,
        "splitArea": {
            "show": True,
            "areaStyle": {"color": ["rgba(248,250,252,.95)", "rgba(241,245,249,.9)"]},
        },
        "axisLabel": dict(_AXIS_LABEL),
        "axisLine": _AXIS_LINE,
        "axisTick": _AXIS_TICK,
    }
    option["yAxis"] = {
        "type": "category",
        "data": y_labels,
        "splitArea": {"show": True},
        "axisLabel": dict(_AXIS_LABEL),
        "axisLine": _AXIS_LINE,
        "axisTick": _AXIS_TICK,
    }
    # Sequential blue scale — colorblind-safer than green→red.
    option["visualMap"] = {
        "min": min(values) if values else 0,
        "max": max(values) if values else 1,
        "calculable": True,
        "orient": "horizontal",
        "left": "center",
        "bottom": 8,
        "inRange": {"color": ["#F0F9FF", "#7DD3FC", "#0EA5E9", "#0369A1"]},
        "textStyle": {"color": "#94A3B8", "fontSize": 11, "fontFamily": _FONT},
    }
    option["series"] = [
        {
            "type": "heatmap",
            "data": data,
            "label": {"show": False},
            "itemStyle": {"borderColor": "#fff", "borderWidth": 2, "borderRadius": 4},
            "emphasis": {"itemStyle": {**_SOFT_SHADOW}},
        }
    ]
    return option


def _option_radar(base, categories, values, **_kwargs):
    peak = max(values) if values else 1.0
    indicators = [{"name": name[:16], "max": peak * 1.2 or 1} for name in categories[:12]]
    option = dict(base)
    option.pop("grid", None)
    option["radar"] = {
        "indicator": indicators,
        "radius": "60%",
        "axisName": {"color": "#94A3B8", "fontSize": 11, "fontFamily": _FONT},
        "splitArea": {
            "areaStyle": {
                "color": [
                    "rgba(14, 165, 233, 0.03)",
                    "rgba(14, 165, 233, 0.06)",
                    "rgba(14, 165, 233, 0.03)",
                    "rgba(14, 165, 233, 0.07)",
                ]
            }
        },
        "axisLine": {"lineStyle": {"color": "rgba(148, 163, 184, 0.28)"}},
        "splitLine": {"lineStyle": {"color": "rgba(148, 163, 184, 0.22)", "type": "dashed"}},
    }
    option["series"] = [
        {
            "type": "radar",
            "symbol": "circle",
            "symbolSize": 5,
            "lineStyle": {"width": 2, "color": _PRIMARY},
            "itemStyle": {"color": _PRIMARY, **_SOFT_SHADOW},
            "areaStyle": {"color": _fade(_PRIMARY, 0.18)},
            "emphasis": {"focus": "series"},
            "data": [{"value": values[: len(indicators)], "name": "系列"}],
        }
    ]
    return option


def _option_funnel(base, categories, values, **_kwargs):
    option = dict(base)
    option.pop("grid", None)
    paired = sorted(zip(categories, values, strict=False), key=lambda item: item[1], reverse=True)
    option["tooltip"] = dict(_TOOLTIP_ITEM)
    data = []
    for index, (name, value) in enumerate(paired):
        color = _PRIMARY if index == 0 else _ACCENT if index == 1 else _MUTED[(index - 2) % len(_MUTED)]
        data.append(
            {
                "name": name,
                "value": value,
                "itemStyle": {
                    "color": color,
                    "borderColor": "#fff",
                    "borderWidth": 2,
                    "borderRadius": 6,
                },
            }
        )
    option["series"] = [
        {
            "type": "funnel",
            "left": "14%",
            "width": "72%",
            "minSize": "14%",
            "gap": 6,
            "label": {
                "formatter": "{b}",
                "color": "#64748B",
                "fontSize": 12,
                "fontFamily": _FONT,
            },
            "emphasis": {
                "focus": "self",
                "label": {"fontWeight": 600, "color": "#0F172A"},
            },
            "blur": {"itemStyle": {"opacity": 0.3}},
            "data": data,
        }
    ]
    return option


def _option_stacked_bar(
    base,
    categories,
    values,
    *,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    mapping: Mapping[str, Any],
    x_idx: int,
    y_idx: int,
):
    series_idx = _col_index(columns, str(mapping.get("series") or ""))
    if series_idx is None:
        return _option_bar(base, categories, values)
    cats: list[str] = []
    series_names: list[str] = []
    matrix: dict[str, dict[str, float]] = {}
    for row in rows:
        if max(x_idx, y_idx, series_idx) >= len(row):
            continue
        number = _as_number(row[y_idx])
        if number is None:
            continue
        cat = str(row[x_idx])
        series = str(row[series_idx])
        if cat not in matrix:
            matrix[cat] = {}
            cats.append(cat)
        if series not in series_names:
            series_names.append(series)
        matrix[cat][series] = matrix[cat].get(series, 0.0) + number
    if not cats or not series_names:
        return _option_bar(base, categories, values)
    option = dict(base)
    option["tooltip"] = dict(_TOOLTIP_AXIS)
    limited = series_names[:6]
    option["legend"] = {**_LEGEND, "data": limited}
    option["grid"] = {"left": 28, "right": 20, "top": 56, "bottom": 44, "containLabel": True}
    option["xAxis"] = _category_axis(cats)
    option["yAxis"] = _value_axis()
    option["series"] = [
        {
            "name": name,
            "type": "bar",
            "stack": "total",
            "barMaxWidth": 36,
            "emphasis": {"focus": "series"},
            "blur": {"itemStyle": {"opacity": 0.2}},
            "itemStyle": {
                "borderRadius": (
                    [8, 8, 0, 0] if index == len(limited) - 1 else [0, 0, 0, 0]
                ),
                "color": (
                    _linear_gradient(_PRIMARY, _PRIMARY_DEEP)
                    if index == 0
                    else _series_color(index)
                ),
            },
            "data": [matrix[cat].get(name, 0.0) for cat in cats],
        }
        for index, name in enumerate(limited)
    ]
    return option
