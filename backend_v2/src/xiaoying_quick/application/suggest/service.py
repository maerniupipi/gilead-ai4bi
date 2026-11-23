"""Generate three follow-up questions after the main answer is ready.

Runs outside the Agent tool loop: callers invoke this only at the end of a
normal turn or insight synthesis, never in parallel with the main loop.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from xiaoying_quick.application.suggest.prompts import (
    CATEGORIES,
    CLASSIFY_SYSTEM,
    classify_user_prompt,
    generate_system_for,
    generate_user_prompt,
)
from xiaoying_quick.infrastructure.llm.client import ChatCompletionClient

_LOGGER = logging.getLogger(__name__)

CancelledCheck = Callable[[], bool]
_MAX_TABLE_ROWS = 8
_MAX_FACT_LINES = 12


async def build_suggestions(
    *,
    client: ChatCompletionClient | None,
    question: str,
    answer: str = "",
    answer_data: str = "",
    facts: Sequence[str] | None = None,
    query_tables: Sequence[Mapping[str, Any]] | None = None,
    is_cancelled: CancelledCheck | None = None,
) -> dict[str, Any] | None:
    """Return suggest.ready payload or None (silent).

    ``answer`` / ``answer_data`` (or facts+tables) must reflect the finished
    turn so recommendations dig into causes behind the result, not lookalikes
    of the original question.
    """

    def cancelled() -> bool:
        return bool(is_cancelled and is_cancelled())

    clean_q = str(question or "").strip()
    clean_a = str(answer or "").strip()
    if cancelled() or not clean_q or client is None:
        return None
    reviewer = getattr(client, "complete_json", None)
    if not callable(reviewer):
        return None

    data_text = str(answer_data or "").strip() or format_answer_data(
        facts=facts, query_tables=query_tables
    )

    if cancelled():
        return None
    try:
        classified = await reviewer(
            purpose="suggest.classify",
            system_prompt=CLASSIFY_SYSTEM,
            user_prompt=classify_user_prompt(question=clean_q, answer=clean_a),
            max_tokens=200,
        )
        category = _parse_category(getattr(classified, "payload", None))
    except Exception:  # noqa: BLE001 — suggest never fails the main run
        _LOGGER.warning("suggest classify raised", exc_info=True)
        return None
    if cancelled() or category is None:
        return None

    if cancelled():
        return None
    try:
        generated = await reviewer(
            purpose="suggest.generate",
            system_prompt=generate_system_for(category),
            user_prompt=generate_user_prompt(
                question=clean_q,
                answer=clean_a,
                answer_data=data_text,
                category=category,
            ),
            max_tokens=700,
        )
        questions = _parse_questions(getattr(generated, "payload", None))
    except Exception:  # noqa: BLE001
        _LOGGER.warning("suggest generate raised", exc_info=True)
        return None
    if cancelled() or not questions:
        return None
    return {"category": category, "questions": questions}


def format_answer_data(
    *,
    facts: Sequence[str] | None = None,
    query_tables: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """Compact text context for the suggest generator (not shown to end users)."""

    lines: list[str] = []
    clean_facts = [str(item).strip() for item in (facts or ()) if str(item).strip()]
    if clean_facts:
        lines.append("【事实摘要】")
        for item in clean_facts[-_MAX_FACT_LINES:]:
            lines.append(f"- {item[:300]}")
    for index, table in enumerate(query_tables or ()):
        if not isinstance(table, Mapping):
            continue
        columns = [str(col) for col in (table.get("columns") or [])]
        rows = table.get("rows") if isinstance(table.get("rows"), list) else []
        if not columns or not rows:
            continue
        lines.append(f"【取数表{index + 1}】列：{' | '.join(columns[:12])}")
        for row in rows[:_MAX_TABLE_ROWS]:
            if isinstance(row, (list, tuple)):
                cells = [str(cell) for cell in row[:12]]
            else:
                cells = [str(row)]
            lines.append("  " + " | ".join(cells))
        if len(rows) > _MAX_TABLE_ROWS:
            lines.append(f"  …共 {len(rows)} 行")
    return "\n".join(lines).strip()


def _parse_category(payload: Mapping[str, Any] | None) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    category = str(payload.get("category") or "").strip()
    return category if category in CATEGORIES else None


def _parse_questions(payload: Mapping[str, Any] | None) -> list[dict[str, str]] | None:
    if not isinstance(payload, Mapping):
        return None
    raw = payload.get("questions")
    if not isinstance(raw, list):
        return None
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in raw:
        text = ""
        if isinstance(entry, Mapping):
            text = str(entry.get("text") or "").strip()
        elif isinstance(entry, str):
            text = entry.strip()
        text = " ".join(text.split())
        if not text or text in seen:
            continue
        seen.add(text)
        items.append({"text": text[:200]})
        if len(items) == 3:
            break
    return items if len(items) == 3 else None
