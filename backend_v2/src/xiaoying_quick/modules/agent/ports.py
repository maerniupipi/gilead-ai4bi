from __future__ import annotations

from typing import Protocol

from .profiles import AgentConfigRecord


class AgentConfigRepository(Protocol):
    def get(self, agent_id: str) -> AgentConfigRecord | None: ...

    def list_all(self) -> tuple[AgentConfigRecord, ...]: ...

    def add(self, record: AgentConfigRecord) -> AgentConfigRecord: ...

    def save(self, record: AgentConfigRecord) -> AgentConfigRecord: ...
