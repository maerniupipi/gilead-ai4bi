"""SQLAlchemy repository for agent enablement and tool assignment."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from xiaoying_quick.modules.agent.ports import AgentConfigRepository
from xiaoying_quick.modules.agent.profiles import AgentConfigRecord

from ..models.agent_configs import AgentConfigModel


class SqlAlchemyAgentConfigRepository(AgentConfigRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, agent_id: str) -> AgentConfigRecord | None:
        model = self._session.get(AgentConfigModel, agent_id)
        return _to_record(model) if model is not None else None

    def list_all(self) -> tuple[AgentConfigRecord, ...]:
        rows = self._session.scalars(select(AgentConfigModel)).all()
        return tuple(_to_record(row) for row in rows)

    def add(self, record: AgentConfigRecord) -> AgentConfigRecord:
        model = _to_model(record)
        self._session.add(model)
        self._session.flush()
        return _to_record(model)

    def save(self, record: AgentConfigRecord) -> AgentConfigRecord:
        model = self._session.get(AgentConfigModel, record.id)
        if model is None:
            raise LookupError(f"agent config {record.id} disappeared")
        model.enabled = record.enabled
        model.tool_names = list(record.tool_names)
        model.agent_names = list(record.agent_names)
        model.extras = dict(record.extras or {})
        self._session.flush()
        return _to_record(model)


def _to_model(record: AgentConfigRecord) -> AgentConfigModel:
    return AgentConfigModel(
        id=record.id,
        enabled=record.enabled,
        tool_names=list(record.tool_names),
        agent_names=list(record.agent_names),
        extras=dict(record.extras or {}),
    )


def _to_record(model: AgentConfigModel) -> AgentConfigRecord:
    tools = model.tool_names if isinstance(model.tool_names, list) else []
    agents = model.agent_names if isinstance(model.agent_names, list) else []
    extras = model.extras if isinstance(model.extras, dict) else {}
    return AgentConfigRecord(
        id=model.id,
        enabled=bool(model.enabled),
        tool_names=tuple(str(item) for item in tools),
        agent_names=tuple(str(item) for item in agents),
        created_at=model.created_at,
        updated_at=model.updated_at,
        extras=dict(extras),
    )
