"""Agent domain: the open event protocol and the tool registry."""

from xiaoying_quick.modules.agent.catalog import (
    AGENT_SPECS,
    MAIN_SYSTEM_PROMPT,
    TOOL_METAS,
    AgentSpec,
    ToolMeta,
)
from xiaoying_quick.modules.agent.contracts import (
    AgentToolContext,
    ToolCallResult,
    ToolExecutor,
    ToolSpec,
)
from xiaoying_quick.modules.agent.events import AgentEventType, validate_agent_event
from xiaoying_quick.modules.agent.profiles import AgentConfigRecord
from xiaoying_quick.modules.agent.registry import ToolRegistry
from xiaoying_quick.modules.agent.service import AgentConfigService, AgentProfile

__all__ = [
    "AGENT_SPECS",
    "MAIN_SYSTEM_PROMPT",
    "TOOL_METAS",
    "AgentConfigRecord",
    "AgentConfigService",
    "AgentEventType",
    "AgentProfile",
    "AgentSpec",
    "AgentToolContext",
    "ToolCallResult",
    "ToolExecutor",
    "ToolMeta",
    "ToolRegistry",
    "ToolSpec",
    "validate_agent_event",
]
