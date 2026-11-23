"""Open registry of agent tools.

Adding a capability is registering a ``ToolSpec``; the loop itself never
changes. Execution is uniform and failure-proof: whatever an executor raises
becomes a failed observation for the model instead of killing the run.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence

from .contracts import AgentToolContext, ToolCallResult, ToolSpec

_LOGGER = logging.getLogger(__name__)

#: Tool output handed back into the model's context is capped so one chatty
#: tool cannot crowd out the rest of the conversation.
MAX_TOOL_OUTPUT_CHARS = 8_000


class ToolRegistry:
    def __init__(self, specs: Sequence[ToolSpec]) -> None:
        by_name: dict[str, ToolSpec] = {}
        for spec in specs:
            if spec.name in by_name:
                raise ValueError(f"duplicate tool name: {spec.name}")
            by_name[spec.name] = spec
        self._specs = by_name

    def names(self) -> tuple[str, ...]:
        return tuple(self._specs)

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def schemas(self) -> tuple[Mapping[str, object], ...]:
        return tuple(spec.openai_schema() for spec in self._specs.values())

    async def execute(
        self,
        *,
        name: str,
        context: AgentToolContext,
        arguments: Mapping[str, object],
    ) -> ToolCallResult:
        spec = self._specs.get(name)
        if spec is None:
            return ToolCallResult(
                ok=False,
                output=f"工具 `{name}` 不存在。可用工具：{', '.join(self._specs)}。",
            )
        try:
            result = await spec.executor(context, arguments)
        except Exception as exc:  # noqa: BLE001 — a tool failure is an observation.
            _LOGGER.warning("agent tool failed", extra={"tool": name, "error": str(exc)})
            return ToolCallResult(
                ok=False,
                output=f"工具 `{name}` 执行失败：{_bounded(str(exc))}",
                payload={"error": type(exc).__name__},
            )
        output = _bounded(result.output)
        return ToolCallResult(
            ok=result.ok,
            output=output,
            payload=result.payload,
            suspended=result.suspended,
        )

    @staticmethod
    def parse_arguments(raw: str) -> Mapping[str, object]:
        """The model serializes call arguments as JSON text."""

        try:
            parsed = json.loads(raw or "{}")
        except (json.JSONDecodeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}


def _bounded(text: str) -> str:
    if len(text) <= MAX_TOOL_OUTPUT_CHARS:
        return text
    return text[:MAX_TOOL_OUTPUT_CHARS] + f"\n…[已截断，共 {len(text)} 字符]"
