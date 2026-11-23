from __future__ import annotations

import pytest

from xiaoying_quick.application.agent_run.loop import AGENT_SYSTEM_PROMPT
from xiaoying_quick.modules.agent.catalog import AGENT_BY_ID, AGENT_SPECS, MAIN_SYSTEM_PROMPT
from xiaoying_quick.modules.agent.profiles import AgentConfigRecord
from xiaoying_quick.modules.agent.service import AgentConfigService
from xiaoying_quick.shared.errors import ValidationFailed


class MemoryRepo:
    def __init__(self) -> None:
        self.rows: dict[str, AgentConfigRecord] = {}

    def get(self, agent_id: str) -> AgentConfigRecord | None:
        return self.rows.get(agent_id)

    def list_all(self) -> tuple[AgentConfigRecord, ...]:
        return tuple(self.rows.values())

    def add(self, record: AgentConfigRecord) -> AgentConfigRecord:
        self.rows[record.id] = record
        return record

    def save(self, record: AgentConfigRecord) -> AgentConfigRecord:
        self.rows[record.id] = record
        return record


def test_seed_creates_catalog_agents() -> None:
    service = AgentConfigService(MemoryRepo())
    profiles = service.list_profiles()
    assert [item.id for item in profiles] == [spec.id for spec in AGENT_SPECS]
    main = next(item for item in profiles if item.id == "main")
    assert main.spec.required
    assert main.config.enabled
    assert "query_db" in main.config.tool_names
    assert "ask_lab" not in main.config.tool_names
    assert main.config.agent_names == ("lab_sql", "bailian")
    lab = next(item for item in profiles if item.id == "lab_sql")
    assert "generate_sql" in lab.config.tool_names
    recall = next(item for item in profiles if item.id == "bailian")
    assert recall.spec.name == "召回智能体"
    assert "field_recall" in recall.config.tool_names


def test_update_rejects_unknown_tools_and_self_delegation() -> None:
    service = AgentConfigService(MemoryRepo())
    with pytest.raises(ValidationFailed, match="unknown tools"):
        service.update("main", tool_names=("not_a_tool",))
    with pytest.raises(ValidationFailed, match="unknown sub-agents"):
        service.update("main", agent_names=("main", "ghost"))
    saved = service.update("main", agent_names=("lab_sql",), tool_names=("query_db", "ask_user"))
    assert saved.config.agent_names == ("lab_sql",)
    assert saved.config.tool_names == ("query_db", "ask_user")


def test_every_agent_has_a_code_owned_system_prompt() -> None:
    for spec in AGENT_SPECS:
        assert spec.system_prompt.strip(), spec.id
    assert AGENT_BY_ID["main"].system_prompt == MAIN_SYSTEM_PROMPT
    assert AGENT_SYSTEM_PROMPT is MAIN_SYSTEM_PROMPT
    assert "你是「Gilead BI」" in AGENT_BY_ID["main"].system_prompt
    assert "generate_sql" in AGENT_BY_ID["lab_sql"].system_prompt
    assert "field_recall" in AGENT_BY_ID["bailian"].system_prompt


def test_local_tools_are_seeded_once() -> None:
    service = AgentConfigService(MemoryRepo())
    lab = service.get_profile("lab_sql")
    assert "generate_sql" in lab.config.tool_names
    trimmed = service.update("lab_sql", tool_names=("update_ledger",))
    assert trimmed.config.tool_names == ("update_ledger",)
    again = service.get_profile("lab_sql")
    assert again.config.tool_names == ("update_ledger",)


def test_recall_extras_are_persisted() -> None:
    service = AgentConfigService(MemoryRepo())
    saved = service.update(
        "bailian",
        extras={"recall": {"probe_values": False, "max_values": 8}},
    )
    assert saved.config.extras["recall"]["probe_values"] is False
    assert saved.config.extras["recall"]["max_values"] == 8


def test_required_agent_cannot_be_disabled() -> None:
    service = AgentConfigService(MemoryRepo())
    main = service.set_enabled("main", False)
    assert main.config.enabled is True
    lab = service.set_enabled("lab_sql", False)
    assert lab.config.enabled is False
