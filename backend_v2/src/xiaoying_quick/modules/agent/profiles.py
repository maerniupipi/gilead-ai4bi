"""Persisted enablement and tool selection for a code-registered agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AgentConfigRecord:
    id: str
    enabled: bool
    tool_names: tuple[str, ...]
    agent_names: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    extras: dict[str, Any] = field(default_factory=dict)
