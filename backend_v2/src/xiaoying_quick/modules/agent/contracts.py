"""Tool contracts for the agent loop.

A tool is a name, a JSON schema the model reasons against, and an executor.
The loop treats every tool identically: emit ``tool.call``, run the executor,
emit ``tool.result``. A failing tool never breaks the loop — the failure text
goes back to the model as an observation and it decides what to do next.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCallResult:
    """What one tool execution leaves behind.

    ``output`` is the bounded text handed back to the model; ``payload`` is the
    structured form kept in the event/artifact trail for the UI to render
    (tables, citations, SQL text, ...).
    """

    ok: bool
    output: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    #: Set by the ask_user tool: suspend the loop and wait for the user.
    suspended: bool = False


class AgentToolContext:
    """Capabilities one tool execution may use.

    The application layer builds a concrete instance per run step; tools stay
    reusable across runs because they only see this surface, never the loop.
    """

    def __init__(
        self,
        *,
        run_id: str,
        session_id: str,
        actor_id: str,
        emit: Callable[[str, dict[str, Any]], None],
        extras: Mapping[str, Any] | None = None,
        active_scopes: tuple[str, ...] = (),
        call_id: str = "",
    ) -> None:
        self.run_id = run_id
        self.session_id = session_id
        self.actor_id = actor_id
        self.call_id = call_id
        self._emit = emit
        self._extras = dict(extras or {})
        #: Confirmed scopes effective for this turn (primed memory plus
        #: answered clarifications); tools forward them to downstream ports.
        self.active_scopes = tuple(active_scopes)

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self._emit(event_type, payload)

    def dependency(self, key: str) -> Any:
        """A wired dependency (lab port, query runner, knowledge recall...)."""

        try:
            return self._extras[key]
        except KeyError:
            raise LookupError(f"agent tool dependency unavailable: {key}") from None


ToolExecutor = Callable[[AgentToolContext, Mapping[str, Any]], Awaitable[ToolCallResult]]


@dataclass(frozen=True)
class ToolSpec:
    """One registered tool, exactly as the model is allowed to see it."""

    name: str
    description: str
    parameters: Mapping[str, Any]
    executor: ToolExecutor

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.parameters),
            },
        }
