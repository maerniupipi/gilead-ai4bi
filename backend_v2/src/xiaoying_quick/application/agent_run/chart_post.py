"""Post-loop chart stage: judge model then ECharts payload (never an Agent tool)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from xiaoying_quick.application.charts import (
    JUDGE_SYSTEM_PROMPT,
    build_chart_payload,
    build_judge_user_prompt,
    parse_judge_payload,
    select_analysis_table,
)
from xiaoying_quick.application.charts.heuristic import (
    default_chart_specs,
    is_chartable_table,
    looks_like_metadata_question,
)
from xiaoying_quick.infrastructure.llm.client import ChatCompletionClient

_LOGGER = logging.getLogger(__name__)


async def maybe_build_charts(
    *,
    client: ChatCompletionClient | None,
    question: str,
    answer: str,
    query_tables: list[dict[str, Any]],
    is_cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any] | None:
    """Return chart.ready payload, or None to stay silent."""

    def cancelled() -> bool:
        return bool(is_cancelled and is_cancelled())

    if cancelled():
        return None
    table = select_analysis_table(query_tables)
    if table is None:
        _LOGGER.info("chart skip: no analysis table")
        return None
    if looks_like_metadata_question(question, answer):
        _LOGGER.info("chart skip: metadata-style question")
        return None
    if not is_chartable_table(table):
        _LOGGER.info("chart skip: table not chartable")
        return None

    if cancelled():
        return None
    judged = await _judge(client, question=question, answer=answer, table=table)
    if cancelled():
        return None
    if judged is None or not judged.get("suitable"):
        # Judge flaky / veto: still chart clear KPI grids (province sales etc.).
        judged = default_chart_specs(table)
        if judged is None:
            _LOGGER.info("chart skip: judge unsuitable and no heuristic")
            return None
        _LOGGER.info("chart fallback: heuristic bar/line/pie")

    if cancelled():
        return None
    try:
        payload = build_chart_payload(judged=judged, table=table)
    except Exception:  # noqa: BLE001
        _LOGGER.warning("chart builder raised", exc_info=True)
        return None
    if payload is None:
        judged = default_chart_specs(table)
        if judged is None:
            return None
        try:
            payload = build_chart_payload(judged=judged, table=table)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("chart heuristic builder raised", exc_info=True)
            return None
    return None if cancelled() else payload


async def _judge(
    client: ChatCompletionClient | None,
    *,
    question: str,
    answer: str,
    table: dict[str, Any],
) -> dict[str, Any] | None:
    if client is None:
        return None
    reviewer = getattr(client, "complete_json", None)
    if not callable(reviewer):
        return None
    try:
        completion = await reviewer(
            purpose="agent.chart_judge",
            system_prompt=JUDGE_SYSTEM_PROMPT,
            user_prompt=build_judge_user_prompt(
                question=question, answer=answer, table=table
            ),
            max_tokens=1_200,
        )
        payload = getattr(completion, "payload", None)
        return parse_judge_payload(payload if isinstance(payload, dict) else None)
    except Exception:  # noqa: BLE001 — chart stage must never fail the run
        _LOGGER.warning("chart judge raised", exc_info=True)
        return None
