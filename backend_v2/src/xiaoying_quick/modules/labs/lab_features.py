"""Assemble the full ``features`` payload shipped with every lab call.

The lab platform templates reference ``features.*`` placeholders and every
value is ours to provide: time anchors (the labs cannot guess "YTD" without
knowing the latest data month), ambiguity knowledge, KPI whitelists and
calculation logic, plus the identity slots that await a user-profile source.

Static blocks are extracted from the lab knowledge documents at call time;
they are small markdown sections, so re-reading them is cheap and keeps the
docs as the single source of truth.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from xiaoying_quick.modules.labs.knowledge_pack import (
    _markdown_sections,
    _read_lab_markdown,
    _table_rows,
)

_VALUE_LIMIT = 4_000
#: Lab rewrite templates use this as 「我」→ filter, and ``startswith('rsd')``
#: for 「下属」grouping. Stays until a user-profile source maps the caller.
DEFAULT_TRTY_CODE = "rsd_trty_code = RD_R40016"


def sales_anchor(max_sales_month: str | None, *, today: date | None = None) -> tuple[int, int]:
    """(year, month) of the latest data month; defaults to the previous month."""

    if max_sales_month and "-" in max_sales_month:
        year_text, month_text = max_sales_month.split("-", 1)
        if year_text.isdigit() and month_text.isdigit():
            return int(year_text), int(month_text)
    current = today or date.today()
    if current.month == 1:
        return current.year - 1, 12
    return current.year, current.month - 1


def time_anchor_text(year: int, month: int) -> str:
    """The loop_prompt slot-3 anchor: every time convention in one place."""

    prev_month = 12 if month == 1 else month - 1
    return (
        f"【时间基准】当前日历时间今天所在月份的数据通常尚未出齐，"
        f"数据最新月默认为 {year} 年 {month} 月（系统估算值，"
        f"若上游已确认实际数据最新月，以确认值为准）。\n"
        f"YTD=当年1月至数据最新月份（{year} 年 YTD 即 1 月到 {month} 月）；"
        f"H1=1月到6月；H2=7月到12月；\n"
        f"「今年」指 {year} 年，「去年」指 {year - 1} 年，「前年」指 {year - 2} 年；"
        f"「上个月」指 {prev_month} 月。"
    )


def _section(doc: str, *hints: str) -> str:
    for title, body in _markdown_sections(doc):
        if any(hint in title for hint in hints):
            return body.strip()
    return ""


def _clip(text: str) -> str:
    clean = text.strip()
    return clean[:_VALUE_LIMIT] if len(clean) > _VALUE_LIMIT else clean


def _kpi_names(section_body: str) -> list[str]:
    names: list[str] = []
    for cells in _table_rows(section_body):
        if not cells:
            continue
        if cells[0].isdigit() and len(cells) >= 2:
            name = cells[1]
        elif cells[0] in {"KPI", "#", "指标"} or set("".join(cells)) <= {"-", ":"}:
            continue
        else:
            name = cells[0]
        if name.strip():
            names.append(name.strip())
    return names


def ambiguity_knowledge(knowledge_root: Path, lab_id: str) -> str:
    """The lab's §6 ambiguity knowledge → features.columns_value_knowledge."""

    doc = _read_lab_markdown(knowledge_root, lab_id)
    if not doc:
        return ""
    return _clip(_section(doc, "歧义", "澄清"))


def build_static_features(knowledge_root: Path, lab_id: str) -> dict[str, str]:
    """Per-lab feature values extracted from the knowledge documents."""

    features: dict[str, str] = {}
    doc = _read_lab_markdown(knowledge_root, lab_id)
    if not doc:
        return features

    ambiguity = _clip(_section(doc, "歧义", "澄清"))
    if ambiguity:
        features["columns_value_knowledge"] = ambiguity

    if lab_id == "actual":
        kpi_section = _section(doc, "支持的 KPI", "KPI")
        names = _kpi_names(kpi_section)
        if names:
            features["kpis"] = _clip("、".join(names))
        if kpi_section:
            features["Actual_Prompt"] = _clip(kpi_section)
    elif lab_id == "ext_simple":
        kpi_section = _section(doc, "指标与口径")
        if kpi_section:
            features["kpi_prompt"] = _clip(kpi_section)
    elif lab_id == "ext_complex":
        kpi_section = _section(doc, "指标与口径")
        if kpi_section:
            features["kpi_prompt"] = _clip(kpi_section)
        market_section = _section(doc, "数据范围与维度")
        if market_section:
            features["market_danwei"] = _clip(market_section)
    return features


def build_call_features(
    *,
    lab_id: str,
    knowledge_root: Path,
    max_sales_month: str | None = None,
    remark: str = "",
    trty_code: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Every features key a lab template may reference, filled or explicitly blank."""

    year, month = sales_anchor(max_sales_month, today=today)
    identity = DEFAULT_TRTY_CODE if trty_code is None else str(trty_code).strip()
    features: dict[str, Any] = {
        "cur_sales_year": str(year),
        "cur_sales_month": str(month),
        "max_sales_year": str(year),
        "max_sales_month": str(month),
        "trty_code": identity,
        "kcode": "",
        # The long/short-word shielding expects JSON; "None" takes the
        # template's else branch until the knowledge docs are JSON-ified.
        "long_short_words": "None",
    }
    clean_remark = " ".join(str(remark or "").split()).strip()
    if clean_remark:
        features["remark"] = clean_remark[:2_000]
    features.update(build_static_features(knowledge_root, lab_id))
    return features


__all__ = [
    "DEFAULT_TRTY_CODE",
    "ambiguity_knowledge",
    "build_call_features",
    "build_static_features",
    "sales_anchor",
    "time_anchor_text",
]
