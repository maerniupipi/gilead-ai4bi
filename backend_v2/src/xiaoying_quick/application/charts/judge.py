"""Judge whether a query result deserves charts and which three types to use."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

CHART_TYPES: tuple[str, ...] = (
    "bar",
    "line",
    "pie",
    "progress",
    "heatmap",
    "scatter",
    "area",
    "radar",
    "funnel",
    "stacked_bar",
)

_COMMON_TYPES = frozenset({"bar", "line", "pie"})
_MAX_SAMPLE_ROWS = 40
_MAX_ANSWER_CHARS = 2_000

JUDGE_SYSTEM_PROMPT = """你是数据分析可视化判定器。根据用户问题、助手最终回答和查询结果表，判断是否值得用图表展示 KPI/对比/趋势类数据。

规则：
1. 适合：各省份/大区销量、时间序列趋势、品类占比、多系列对比等。
2. 不适合（suitable=false）：询问最新时间、字段清单、表结构、单点元数据、空结果、无法形成可比维度等。即使有 query_db 结果也不出图。
3. suitable=true 时必须给出恰好 3 种图表，按推荐优先级排序（第 1 个为默认展示）。
4. 图表 type 只能从以下枚举选择：bar, line, pie, progress, heatmap, scatter, area, radar, funnel, stacked_bar。
5. 数据行数较少时优先 bar / line / pie，不要硬套 heatmap、radar、scatter、funnel 等复杂图；若数据形态确实适合复杂图仍可选用。
6. mapping 用列名标明 x / y（及可选 z、series 分组列）。data 可省略，系统会用原表按 mapping 构图。
7. 只输出一个 JSON 对象，不要 Markdown 代码围栏。

JSON 形状：
{
  "suitable": true|false,
  "reason": "简短理由，仅供日志",
  "charts": [
    {
      "type": "bar",
      "title": "标题",
      "mapping": {"x": "列名", "y": "列名", "z": null, "series": null},
      "style": {}
    }
  ]
}
suitable=false 时 charts 可为 []。
"""


def build_judge_user_prompt(
    *,
    question: str,
    answer: str,
    table: Mapping[str, Any],
) -> str:
    columns = [str(column) for column in (table.get("columns") or [])][:32]
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    sample = rows[:_MAX_SAMPLE_ROWS]
    body = {
        "question": str(question or "")[:1_000],
        "answer": str(answer or "")[:_MAX_ANSWER_CHARS],
        "sql": str(table.get("sql") or "")[:2_000],
        "columns": columns,
        "row_count": int(table.get("row_count") or len(rows)),
        "sample_rows": sample,
    }
    return (
        "请判定是否适合图表，并在适合时给出恰好 3 种推荐图表。\n"
        + json.dumps(body, ensure_ascii=False, default=str)
    )


def parse_judge_payload(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Normalize judge JSON; return None to silently skip charts."""

    if not isinstance(payload, Mapping):
        return None
    suitable = bool(payload.get("suitable"))
    reason = str(payload.get("reason") or "")[:500]
    if not suitable:
        return {"suitable": False, "reason": reason, "charts": []}
    raw_charts = payload.get("charts")
    if not isinstance(raw_charts, list):
        return None
    charts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_charts:
        if not isinstance(item, Mapping):
            continue
        chart_type = str(item.get("type") or "").strip()
        if chart_type not in CHART_TYPES or chart_type in seen:
            continue
        mapping = item.get("mapping") if isinstance(item.get("mapping"), Mapping) else {}
        charts.append(
            {
                "type": chart_type,
                "title": str(item.get("title") or "")[:120],
                "mapping": {
                    "x": str(mapping.get("x") or "").strip(),
                    "y": str(mapping.get("y") or "").strip(),
                    "z": str(mapping.get("z") or "").strip() or None,
                    "series": str(mapping.get("series") or "").strip() or None,
                },
                "style": item.get("style") if isinstance(item.get("style"), Mapping) else {},
            }
        )
        seen.add(chart_type)
        if len(charts) == 3:
            break
    if len(charts) < 3:
        charts = _pad_common_charts(charts, columns_hint=_columns_from_payload(payload))
    if len(charts) != 3:
        return None
    return {"suitable": True, "reason": reason, "charts": charts}


def _columns_from_payload(payload: Mapping[str, Any]) -> Sequence[str]:
    data = payload.get("data")
    if isinstance(data, Mapping) and isinstance(data.get("columns"), list):
        return [str(column) for column in data["columns"]]
    return ()


def _pad_common_charts(
    charts: list[dict[str, Any]],
    *,
    columns_hint: Sequence[str],
) -> list[dict[str, Any]]:
    """Fill to three using common types when the model returned fewer."""

    used = {item["type"] for item in charts}
    x_hint = columns_hint[0] if columns_hint else "x"
    y_hint = columns_hint[1] if len(columns_hint) > 1 else "y"
    for chart_type in ("bar", "line", "pie"):
        if chart_type in used:
            continue
        charts.append(
            {
                "type": chart_type,
                "title": "",
                "mapping": {"x": x_hint, "y": y_hint, "z": None, "series": None},
                "style": {},
            }
        )
        used.add(chart_type)
        if len(charts) == 3:
            break
    return charts[:3]
