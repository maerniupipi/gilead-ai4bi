"""Event vocabulary of the agent loop.

Every one of these is appended to the run's event stream, which is the single
source of truth: the conversation view, the track timeline, and the message
history replayed into the model are all projections of the same append-only
log. Deltas ride the live stream too so the UI can render thinking as it
happens; the full text of each step is always recoverable from
``assistant.message``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from xiaoying_quick.shared.compat import StrEnum


class AgentEventType(StrEnum):
    TURN_START = "agent.turn_start"
    TURN_END = "agent.turn_end"
    STEP_START = "agent.step_start"
    STEP_END = "agent.step_end"
    THINK_DELTA = "agent.think.delta"
    CONTENT_DELTA = "agent.content.delta"
    ASSISTANT_MESSAGE = "assistant.message"
    CONTEXT_UPDATED = "context.updated"
    CONTEXT_COMPACTED = "context.compacted"
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    ASK_USER_OPENED = "ask_user.opened"
    ASK_USER_ANSWERED = "ask_user.answered"
    MEMORY_AUTO_SAVED = "memory.auto_saved"
    LEDGER_UPDATED = "agent.ledger.updated"
    AGENT_DONE = "agent.done"
    AGENT_FAILED = "agent.failed"
    CHART_READY = "chart.ready"
    SUGGEST_READY = "suggest.ready"


_REQUIRED: dict[str, tuple[str, ...]] = {
    AgentEventType.STEP_START.value: ("step",),
    AgentEventType.STEP_END.value: ("step",),
    AgentEventType.THINK_DELTA.value: ("text",),
    AgentEventType.CONTENT_DELTA.value: ("text",),
    AgentEventType.ASSISTANT_MESSAGE.value: ("step",),
    AgentEventType.CONTEXT_UPDATED.value: ("step", "used_tokens", "limit", "threshold_tokens"),
    AgentEventType.CONTEXT_COMPACTED.value: ("step", "used_tokens", "before_tokens", "limit", "threshold_tokens"),
    AgentEventType.TOOL_CALL.value: ("call_id", "name", "arguments"),
    AgentEventType.TOOL_RESULT.value: ("call_id", "name", "ok"),
    AgentEventType.ASK_USER_OPENED.value: ("groups",),
    AgentEventType.AGENT_DONE.value: ("answer",),
    AgentEventType.AGENT_FAILED.value: ("code",),
    AgentEventType.CHART_READY.value: ("default_type", "charts"),
    AgentEventType.SUGGEST_READY.value: ("questions",),
}


def validate_agent_event(event_type: str, payload: Mapping[str, Any]) -> None:
    try:
        kind = AgentEventType(event_type)
    except ValueError as exc:
        raise ValueError(f"unknown agent event type: {event_type}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("event payload must be a mapping")
    for key in _REQUIRED.get(kind.value, ()):
        if key not in payload:
            raise ValueError(f"{kind.value} requires {key}")
    if kind is AgentEventType.ASK_USER_OPENED:
        _validate_ask_groups(payload.get("groups"))
    if kind is AgentEventType.CHART_READY:
        _validate_chart_ready(payload)
    if kind is AgentEventType.SUGGEST_READY:
        _validate_suggest_ready(payload)


def _validate_suggest_ready(payload: Mapping[str, Any]) -> None:
    questions = payload.get("questions")
    if not isinstance(questions, (list, tuple)) or len(questions) != 3:
        raise ValueError("suggest.ready requires exactly 3 questions")
    for item in questions:
        if not isinstance(item, Mapping):
            raise ValueError("each suggest.ready entry must be a mapping")
        if not str(item.get("text") or "").strip():
            raise ValueError("each suggest.ready entry requires text")


def _validate_chart_ready(payload: Mapping[str, Any]) -> None:
    charts = payload.get("charts")
    valid_count = 1 <= len(charts) <= 14 if isinstance(charts, (list, tuple)) else False
    if not valid_count or (payload.get("version") != 2 and len(charts) != 3):
        raise ValueError("chart.ready requires 3 charts, or 1 to 14 views for an analysis card")
    for item in charts:
        if not isinstance(item, Mapping):
            raise ValueError("each chart.ready entry must be a mapping")
        if not str(item.get("type") or "").strip():
            raise ValueError("each chart.ready entry requires type")
        if not isinstance(item.get("option"), Mapping):
            raise ValueError("each chart.ready entry requires option")


def _validate_ask_groups(groups: object) -> None:
    if not isinstance(groups, (list, tuple)) or not groups:
        raise ValueError("ask_user.opened requires a non-empty groups list")
    for group in groups:
        if not isinstance(group, Mapping):
            raise ValueError("each ask_user group must be a mapping")
        if not str(group.get("question") or "").strip():
            raise ValueError("each ask_user group requires a question")
        options = group.get("options")
        if not isinstance(options, (list, tuple)) or not options:
            raise ValueError("each ask_user group needs options")
