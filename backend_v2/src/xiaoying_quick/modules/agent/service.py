"""Use cases for agent enablement and tool assignment."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from xiaoying_quick.shared.errors import NotFound, ValidationFailed

from .catalog import AGENT_BY_ID, AGENT_SPECS, TOOL_NAMES, AgentSpec
from .ports import AgentConfigRepository
from .profiles import AgentConfigRecord


@dataclass(frozen=True)
class AgentProfile:
    spec: AgentSpec
    config: AgentConfigRecord

    @property
    def id(self) -> str:
        return self.spec.id

    def to_public_record(self) -> dict[str, object]:
        return {
            "id": self.spec.id,
            "name": self.spec.name,
            "code": self.spec.id,
            "kind": self.spec.kind,
            "required": self.spec.required,
            "enabled": self.config.enabled if not self.spec.required else True,
            "blurb": self.spec.blurb,
            "tool_name": self.spec.tool_name,
            "tool_label": self.spec.tool_label,
            "toolNames": list(self.config.tool_names),
            "agentNames": list(self.config.agent_names),
            "systemPrompt": self.spec.system_prompt,
            "extras": dict(self.config.extras or {}),
            "updated_at": self.config.updated_at.isoformat(),
        }


class AgentConfigService:
    def __init__(self, repository: AgentConfigRepository) -> None:
        self._repository = repository

    def list_profiles(self) -> tuple[AgentProfile, ...]:
        self.ensure_seeded()
        by_id = {row.id: row for row in self._repository.list_all()}
        profiles = []
        for spec in AGENT_SPECS:
            config = by_id.get(spec.id)
            if config is None:
                continue
            profiles.append(AgentProfile(spec=spec, config=config))
        return tuple(profiles)

    def get_profile(self, agent_id: str) -> AgentProfile:
        spec = AGENT_BY_ID.get(agent_id)
        if spec is None:
            raise NotFound("agent not found")
        self.ensure_seeded()
        config = self._repository.get(agent_id)
        if config is None:
            raise NotFound("agent not found")
        return AgentProfile(spec=spec, config=config)

    def update(
        self,
        agent_id: str,
        *,
        enabled: bool | None = None,
        tool_names: tuple[str, ...] | None = None,
        agent_names: tuple[str, ...] | None = None,
        extras: dict | None = None,
    ) -> AgentProfile:
        profile = self.get_profile(agent_id)
        next_enabled = profile.config.enabled if enabled is None else bool(enabled)
        if profile.spec.required:
            next_enabled = True
        next_tools = profile.config.tool_names if tool_names is None else _clean_tools(tool_names)
        next_agents = (
            profile.config.agent_names
            if agent_names is None
            else _clean_agents(agent_names, owner_id=agent_id)
        )
        if extras is None:
            next_extras = profile.config.extras
        else:
            next_extras = _clean_extras(extras)
            if (profile.config.extras or {}).get("report_tool_seeded"):
                next_extras["report_tool_seeded"] = True
            if (profile.config.extras or {}).get("local_tools_seeded"):
                next_extras["local_tools_seeded"] = True
        saved = self._repository.save(
            replace(
                profile.config,
                enabled=next_enabled,
                tool_names=next_tools,
                agent_names=next_agents,
                extras=next_extras,
            )
        )
        return AgentProfile(spec=profile.spec, config=saved)

    def set_enabled(self, agent_id: str, enabled: bool) -> AgentProfile:
        return self.update(agent_id, enabled=enabled)

    def ensure_seeded(self) -> None:
        existing = {row.id: row for row in self._repository.list_all()}
        now = datetime.now(timezone.utc)
        for spec in AGENT_SPECS:
            if spec.id in existing:
                continue
            self._repository.add(
                AgentConfigRecord(
                    id=spec.id,
                    enabled=spec.enabled_by_default,
                    tool_names=spec.default_tool_names,
                    agent_names=spec.default_agent_names,
                    created_at=now,
                    updated_at=now,
                )
            )
        self._ensure_local_tools()
        main = self._repository.get("main")
        if main is not None and not (main.extras or {}).get("report_tool_seeded"):
            tools = tuple(dict.fromkeys((*main.tool_names, "render_report")))
            extras = {**(main.extras or {}), "report_tool_seeded": True}
            self._repository.save(replace(main, tool_names=tools, extras=extras))

    def _ensure_local_tools(self) -> None:
        extra_tools = {
            "lab_sql": ("inspect_schema", "generate_sql", "validate_sql"),
            "bailian": ("inspect_schema", "field_recall", "value_recall"),
        }
        for row in self._repository.list_all():
            added = extra_tools.get(row.id)
            if not added:
                continue
            extras = dict(row.extras or {})
            if extras.get("local_tools_seeded"):
                continue
            merged = list(row.tool_names)
            for name in added:
                if name in TOOL_NAMES and name not in merged:
                    merged.append(name)
            extras["local_tools_seeded"] = True
            self._repository.save(replace(row, tool_names=tuple(merged), extras=extras))


def _clean_tools(names: tuple[str, ...]) -> tuple[str, ...]:
    seen: list[str] = []
    unknown: list[str] = []
    for name in names:
        item = str(name or "").strip()
        if not item:
            continue
        if item not in TOOL_NAMES:
            unknown.append(item)
            continue
        if item not in seen:
            seen.append(item)
    if unknown:
        raise ValidationFailed(f"unknown tools: {', '.join(unknown)}")
    return tuple(seen)


def _clean_extras(extras: dict) -> dict:
    recall = extras.get("recall") if isinstance(extras, dict) else None
    cleaned: dict = {}
    if extras.get("local_tools_seeded"):
        cleaned["local_tools_seeded"] = True
    if isinstance(recall, dict):
        try:
            max_values = int(recall.get("max_values") or 24)
        except (TypeError, ValueError):
            max_values = 24
        cleaned["recall"] = {
            "probe_values": bool(recall.get("probe_values", True)),
            "max_values": max(1, min(max_values, 100)),
        }
    return cleaned


def _clean_agents(names: tuple[str, ...], *, owner_id: str) -> tuple[str, ...]:
    seen: list[str] = []
    unknown: list[str] = []
    for name in names:
        item = str(name or "").strip()
        if not item or item == owner_id:
            continue
        spec = AGENT_BY_ID.get(item)
        if spec is None or spec.kind != "sub":
            unknown.append(item)
            continue
        if item not in seen:
            seen.append(item)
    if unknown:
        raise ValidationFailed(f"unknown sub-agents: {', '.join(unknown)}")
    return tuple(seen)
