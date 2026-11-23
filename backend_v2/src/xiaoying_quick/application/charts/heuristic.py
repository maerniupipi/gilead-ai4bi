"""Deterministic chartability checks and default 3-chart specs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


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


def infer_xy_columns(table: Mapping[str, Any]) -> tuple[str, str] | None:
    columns = [str(column) for column in (table.get("columns") or [])]
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    if len(columns) < 2 or len(rows) < 3:
        return None
    best_y: tuple[int, int] | None = None  # (numeric_count, index)
    for index, _name in enumerate(columns):
        numeric = 0
        for row in rows[:40]:
            if isinstance(row, (list, tuple)) and index < len(row) and _as_number(row[index]) is not None:
                numeric += 1
        if best_y is None or numeric > best_y[0]:
            best_y = (numeric, index)
    if best_y is None or best_y[0] < max(3, len(rows[:40]) // 2):
        return None
    y_idx = best_y[1]
    x_idx = 0 if y_idx != 0 else 1
    return columns[x_idx], columns[y_idx]


def is_chartable_table(table: Mapping[str, Any] | None) -> bool:
    if not isinstance(table, Mapping):
        return False
    return infer_xy_columns(table) is not None


def default_chart_specs(table: Mapping[str, Any]) -> dict[str, Any] | None:
    """bar / line / pie with inferred x/y — used when the judge is unavailable."""

    pair = infer_xy_columns(table)
    if pair is None:
        return None
    x_name, y_name = pair
    mapping = {"x": x_name, "y": y_name, "z": None, "series": None}
    return {
        "suitable": True,
        "reason": "heuristic: categorical + numeric grid",
        "charts": [
            {"type": "bar", "title": f"{y_name} 对比", "mapping": mapping, "style": {}},
            {"type": "line", "title": f"{y_name} 趋势", "mapping": mapping, "style": {}},
            {"type": "pie", "title": f"{y_name} 占比", "mapping": mapping, "style": {}},
        ],
    }


def looks_like_metadata_question(question: str, answer: str) -> bool:
    text = f"{question}\n{answer}".casefold()
    needles = (
        "最新时间",
        "最新日期",
        "有哪些字段",
        "字段有哪些",
        "表结构",
        "什么表",
        "哪些表",
        "数据字典",
        "schema",
        "column",
    )
    return any(item in text for item in needles)
