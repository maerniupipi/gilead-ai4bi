"""Assemble features.loop_prompt_1..5 for a lab call."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

LOOP_PROMPT_KEYS = tuple(f"loop_prompt_{index}" for index in range(1, 6))
_SLOT_LIMIT = 4000


def _clip(text: str) -> str:
    clean = text.strip()
    return clean[:_SLOT_LIMIT] if len(clean) > _SLOT_LIMIT else clean


def _norm_term(text: str) -> str:
    """Normalize a term for matching: width-fold, casefold, drop spaces."""

    return unicodedata.normalize("NFKC", str(text)).casefold().replace(" ", "")


def _term_in_query(alias: str, query: str) -> bool:
    """Whether a term appears in the query as a whole unit.

    Latin/digit terms must hit a word boundary — otherwise a bare ``H`` or
    ``M`` in the alias table matches every question that mentions H2 or YM.
    """

    norm_alias = _norm_term(alias)
    if not norm_alias:
        return False
    norm_query = _norm_term(query)
    if norm_alias.isascii():
        pattern = re.escape(norm_alias)
        if norm_alias.isalnum():
            pattern = rf"(?<![a-z0-9]){pattern}(?![a-z0-9])"
        return re.search(pattern, norm_query) is not None
    return norm_alias in norm_query


def format_upstream_context(hop: Mapping[str, Any]) -> str:
    """Render one verified query_db hop for loop_prompt_5 (SQL-stage only).

    Prefer keeping the executed SQL; drop result rows first when over the
    slot limit so the lab can wrap the previous statement as a subquery.
    """

    sql = str(hop.get("sql") or "").strip()
    question = str(hop.get("question") or "").strip()
    columns = [str(column).strip() for column in (hop.get("columns") or []) if str(column).strip()]
    raw_rows = hop.get("rows")
    rows: list[Any] = raw_rows if isinstance(raw_rows, list) else []
    row_count = hop.get("row_count")
    total = int(row_count) if isinstance(row_count, int) else len(rows)

    def render(include_rows: Sequence[Any]) -> str:
        lines = ["【上游已核验，必须作为本问的过滤集合】"]
        if question:
            lines.append(f"上游问题：{question[:300]}")
        if sql:
            lines.append("上游SQL：")
            lines.append(sql[:2_000])
        if columns:
            lines.append("列：" + "、".join(columns[:24]))
        lines.append(f"行数：{total}")
        if include_rows:
            lines.append("结果行（完整键值，勿只取前几行）：")
            for row in include_rows:
                cells = row if isinstance(row, (list, tuple)) else [row]
                lines.append("- " + " | ".join(_upstream_cell(cell) for cell in cells[:12]))
        else:
            lines.append("结果行过长已省略；请直接 IN (上游SQL) 包裹，不要改上游筛选口径。")
        lines.append("用法：优先写成 WHERE 键列 IN (上游SQL)；不要只取前几行；不要改上游筛选口径。")
        return "\n".join(lines)

    visible = list(rows[:80])
    text = render(visible)
    while visible and len(text) > _SLOT_LIMIT:
        visible = visible[: max(0, len(visible) // 2)]
        text = render(visible)
    if len(text) > _SLOT_LIMIT:
        text = render(())
    return _clip(text)


def _upstream_cell(cell: Any) -> str:
    if cell is None:
        return "NULL"
    text = str(cell).strip()
    return text if len(text) <= 80 else text[:77] + "..."


def pack_loop_prompts(
    *,
    query: str,
    glossary: Mapping[str, str] | None = None,
    bindings: Mapping[str, str] | None = None,
    confirmed: Mapping[str, str] | None = None,
    time_anchor: str = "",
    kpi_formulas: str = "",
    unconfirmed_preferences: Sequence[str] = (),
    upstream_context: str = "",
) -> dict[str, str]:
    """Fill the five loop_prompt slots.

    Slot layout (v2): 1=glossary, 2=confirmed scopes, 3=time anchor,
    4=KPI formulas, 5=upstream verified SQL/keys when the model asked to
    attach the previous hop (otherwise empty).
    Unconfirmed preferences never enter any slot.
    """

    forbidden = {item.strip() for item in unconfirmed_preferences if item and item.strip()}
    glossary_lines: list[str] = []
    for key, value in (glossary or {}).items():
        if _term_in_query(key, query) and key not in forbidden:
            glossary_lines.append(f"{key}: {value}")
    if not glossary_lines and glossary:
        # No alias hit: hand the lab the whole glossary instead of nothing —
        # a missing definition steers SQL generation worse than extra lines.
        glossary_lines = [
            f"{key}: {value}" for key, value in glossary.items() if key not in forbidden and value
        ]
    bind_lines = [f"{key}={value}" for key, value in (bindings or {}).items() if value]
    confirm_lines = [
        f"{key}={value}"
        for key, value in (confirmed or {}).items()
        if value and value not in forbidden
    ]
    slot2 = "\n".join((*bind_lines, *confirm_lines))
    return {
        "loop_prompt_1": _clip("\n".join(glossary_lines)),
        "loop_prompt_2": _clip(slot2),
        "loop_prompt_3": _clip(time_anchor),
        "loop_prompt_4": _clip(kpi_formulas),
        "loop_prompt_5": _clip(upstream_context),
    }


def pack_from_documents(
    *,
    knowledge_root: Path,
    lab_id: str,
    query: str,
    bindings: Mapping[str, str] | None = None,
    confirmed: Mapping[str, str] | None = None,
    time_anchor: str = "",
    unconfirmed_preferences: Sequence[str] = (),
    upstream_context: str = "",
) -> dict[str, str]:
    """Load glossary and formulas from published markdown."""

    business = _read_named(knowledge_root, "业务知识.md")
    lab_md = _read_lab_markdown(knowledge_root, lab_id)
    glossary = {
        **_glossary_from_markdown(business, query),
        **_glossary_from_markdown(lab_md, query),
    }
    if not glossary:
        # No alias hit in the query: give the pack the whole glossary so the
        # slot-2 fallback can ship it to the lab instead of an empty slot.
        glossary = {**_glossary_all(business), **_glossary_all(lab_md)}
    formulas = "\n".join(
        item
        for item in (_kpi_from_markdown(business, query), _kpi_from_markdown(lab_md, query))
        if item
    )
    return pack_loop_prompts(
        query=query,
        glossary=glossary,
        bindings=bindings,
        confirmed=confirmed,
        time_anchor=time_anchor,
        kpi_formulas=formulas,
        unconfirmed_preferences=unconfirmed_preferences,
        upstream_context=upstream_context,
    )


def _read_named(root: Path, name: str) -> str:
    if not root.exists():
        return ""
    for path in sorted(root.rglob(name)):
        return path.read_text(encoding="utf-8")
    return ""


def _read_lab_markdown(root: Path, lab_id: str) -> str:
    if not lab_id or not root.exists():
        return ""
    marker = f"lab_id: `{lab_id}`"
    for path in sorted(root.rglob("labs/*.md")):
        text = path.read_text(encoding="utf-8")
        if path.stem == lab_id or marker in text:
            return text
    return ""


def _tables_in_sections(markdown: str, hints: tuple[str, ...]) -> list[list[list[str]]]:
    """Tables of the sections whose title matches a hint (all when no title)."""

    sections = _markdown_sections(markdown)
    if not any(title for title, _ in sections):
        return [_table_rows(markdown)]
    return [_table_rows(body) for title, body in sections if any(hint in title for hint in hints)]


def _glossary_from_markdown(markdown: str, query: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for rows in _tables_in_sections(markdown, ("术语", "词表", "别名", "产品")):
        for cells in rows:
            if len(cells) < 2:
                continue
            if cells[0].isdigit() and len(cells) >= 3:
                canonical, alias_blob = cells[1], "、".join(cells[2:])
            else:
                canonical, alias_blob = cells[0], "、".join(cells[1:])
            aliases = _split_aliases(alias_blob)
            # The canonical cell itself may bundle variants ("耐信 / 耐针（针剂）");
            # each variant must be matchable on its own.
            parts = _split_aliases(canonical)
            for alias in (*parts, *aliases):
                # One-character terms (H/M/年…) are unit codes, not products.
                if not alias or len(alias.strip()) < 2:
                    continue
                if _term_in_query(alias, query):
                    if alias != canonical and alias not in parts:
                        found[alias] = canonical
                    else:
                        found[alias] = aliases[0] if aliases else alias
    return found


def _glossary_all(markdown: str) -> dict[str, str]:
    """Every glossary row, unfiltered — the zero-hit fallback payload."""

    found: dict[str, str] = {}
    for rows in _tables_in_sections(markdown, ("术语", "词表", "别名", "产品")):
        for cells in rows:
            if len(cells) < 2:
                continue
            if cells[0].isdigit() and len(cells) >= 3:
                canonical, alias_blob = cells[1], "、".join(cells[2:])
            else:
                canonical, alias_blob = cells[0], "、".join(cells[1:])
            aliases = _split_aliases(alias_blob)
            if canonical and canonical not in found:
                found[canonical] = "、".join(aliases) if aliases else canonical
    return found


def _kpi_token_hit(token: str, query: str) -> bool:
    """Exact term hit, or a 3-char CJK window of the label inside the query.

    The window catches phrasing drift: the table says 「销售指标达成率」
    while the user asks about 「金额达成率」— both share 「达成率」.
    """

    if _term_in_query(token, query):
        return True
    norm = _norm_term(token)
    norm_query = _norm_term(query)
    if norm.isascii() or len(norm) < 4:
        return False
    return any(norm[index : index + 3] in norm_query for index in range(len(norm) - 2))


def _kpi_from_markdown(markdown: str, query: str) -> str:
    lines: list[str] = []
    for rows in _tables_in_sections(markdown, ("KPI", "指标", "公式")):
        for cells in rows:
            if len(cells) < 3:
                continue
            if cells[0].isdigit() and len(cells) >= 4:
                name, label, formula = cells[1], cells[2], cells[-1]
            else:
                name, label, formula = cells[0], cells[1], cells[-1]
            tokens = (name, label, *_split_aliases(label), *_split_aliases(name))
            if any(token and _kpi_token_hit(token, query) for token in tokens):
                lines.append(f"{name}：{formula}")
    return "\n".join(dict.fromkeys(lines))


def _table_rows(markdown: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells or set("".join(cells)) <= {"-", ":"}:
            continue
        if cells[0] in {"文档", "KPI", "#", "lab_id", "维度", "槽位"}:
            continue
        rows.append(cells)
    return rows


def _markdown_sections(markdown: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    title = ""
    buf: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if title or buf:
                sections.append((title, "\n".join(buf).strip()))
            title = line[3:].strip()
            buf = []
        else:
            buf.append(line)
    if title or buf:
        sections.append((title, "\n".join(buf).strip()))
    return sections


def _split_aliases(text: str) -> tuple[str, ...]:
    parts: list[str] = []
    current = []
    for char in text.replace("/", "、").replace("，", "、"):
        if char in {"、", ",", ";", "；"}:
            token = "".join(current).strip()
            if token:
                parts.append(token)
            current = []
        else:
            current.append(char)
    token = "".join(current).strip()
    if token:
        parts.append(token)
    return tuple(parts)
