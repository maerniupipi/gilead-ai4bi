"""Build the live ToolRegistry from code-registered tools and persisted agent config."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from xiaoying_quick.application.agent_run.local_tools import (
    build_field_recall_tool,
    build_generate_sql_tool,
    build_inspect_schema_tool,
    build_validate_sql_tool,
    build_value_recall_tool,
)
from xiaoying_quick.application.agent_run.nested import NestedAgentRunner
from xiaoying_quick.application.agent_run.report_tool import build_render_report_tool
from xiaoying_quick.application.agent_run.tools import (
    build_ask_lab_tool,
    build_ask_user_tool,
    build_bailian_recall_tool,
    build_export_xlsx_tool,
    build_knowledge_read_tool,
    build_knowledge_search_tool,
    build_memory_save_tool,
    build_query_db_tool,
    build_update_ledger_tool,
)
from xiaoying_quick.modules.agent import (
    TOOL_METAS,
    AgentConfigService,
    AgentProfile,
    AgentSpec,
    AgentToolContext,
    ToolCallResult,
    ToolRegistry,
    ToolSpec,
)

_NESTED_BLOCKED = frozenset({"ask_user"})
_MAX_DELEGATE_DEPTH = 2

_CATALOG_ONLY_DESCRIPTIONS: dict[str, str] = {
    "suggest_questions": (
        "旁路推荐问题：主问答/洞察汇总全部结束后，基于最终回答与取数结果生成三条"
        "「或许你还想问」（追问原因与结构，非相似问）；不进入 Agent 循环，也不与主链路并行。"
    ),
    "generate_charts": (
        "旁路图表生成：主循环结束后根据取数结果判定是否可视化，"
        "适合时推送三种 ECharts 方案供切换；不进入 Agent 循环。"
    ),

}


def build_primitive_tools(
    *,
    lab_ids: Sequence[str],
    knowledge_root: Path,
    max_sales_month: str | None = None,
    lab_provider: str | None = None,
    mock_enabled: bool = False,
) -> dict[str, ToolSpec]:
    labs = tuple(lab_ids)
    primitives = {
        "ask_lab": build_ask_lab_tool(
            labs, knowledge_root=knowledge_root, max_sales_month=max_sales_month
        ),
        "inspect_schema": build_inspect_schema_tool(),
        "generate_sql": build_generate_sql_tool(labs),
        "validate_sql": build_validate_sql_tool(),
        "query_db": build_query_db_tool(),
        "export_xlsx": build_export_xlsx_tool(),
        "render_report": build_render_report_tool(),
        "knowledge_search": build_knowledge_search_tool(),
        "bailian_recall": build_bailian_recall_tool(labs),
        "field_recall": build_field_recall_tool(),
        "value_recall": build_value_recall_tool(),
        "knowledge_read": build_knowledge_read_tool(knowledge_root),
        "memory_save": build_memory_save_tool(),
        "ask_user": build_ask_user_tool(),
        "update_ledger": build_update_ledger_tool(),
    }
    if lab_provider:
        remote = primitives["ask_lab"]

        async def generate(
            context: AgentToolContext, arguments: Mapping[str, Any]
        ) -> ToolCallResult:
            return await remote.executor(
                context,
                {**arguments, "remark": arguments.get("context") or arguments.get("remark", "")},
            )

        primitives["generate_sql"] = replace(
            remote,
            name="generate_sql",
            executor=generate,
            description=f"通过当前配置的 {lab_provider} 实验室生成 SQL。必须指定 lab_id；"
            "返回后将原始候选 SQL 交给主智能体 query_db 获取结果。",
        )
        if lab_provider == "bootcamp" and not mock_enabled:
            for name in (
                "inspect_schema",
                "validate_sql",
                "field_recall",
                "value_recall",
                "bailian_recall",
            ):
                primitives.pop(name, None)
    return primitives


def public_tool_records(primitives: Mapping[str, ToolSpec]) -> list[dict[str, object]]:
    records = []
    for meta in TOOL_METAS:
        spec = primitives.get(meta.name)
        if spec is None and not meta.catalog_only:
            continue
        description = (
            spec.description
            if spec is not None
            else _CATALOG_ONLY_DESCRIPTIONS.get(meta.name, meta.label)
        )
        schema = spec.parameters if spec is not None and isinstance(spec.parameters, Mapping) else {}
        properties = schema.get("properties") if isinstance(schema, Mapping) else {}
        required = set(schema.get("required") or []) if isinstance(schema, Mapping) else set()
        parameters = []
        if isinstance(properties, Mapping):
            for name, schema in properties.items():
                info = schema if isinstance(schema, Mapping) else {}
                parameters.append(
                    {
                        "name": name,
                        "required": name in required,
                        "text": str(info.get("description") or ""),
                    }
                )
        records.append(
            {
                "name": meta.name,
                "label": meta.label,
                "group": meta.group,
                "description": description,
                "parameters": parameters,
                "configurable": meta.configurable,
                "catalog_only": meta.catalog_only,
            }
        )
    return records


def assemble_tool_registry(
    *,
    service: AgentConfigService,
    primitives: Mapping[str, ToolSpec],
    lab_ids: Sequence[str],
    agent_id: str = "main",
    lab_provider: str | None = None,
) -> ToolRegistry:
    profiles = {item.id: item for item in service.list_profiles()}
    if lab_provider and "lab_sql" in profiles:
        profile = profiles["lab_sql"]
        profiles["lab_sql"] = replace(
            profile,
            spec=replace(
                profile.spec,
                tool_description=(
                    f"调用当前选择的 {lab_provider} 实验室取得候选 SQL。返回后必须 query_db。"
                ),
                system_prompt=(
                    f"你是实验室智能体，当前连接为 {lab_provider}。用中文完成任务。"
                    "调用 generate_sql 或 ask_lab 将原子化查数问题发送到所选实验室；"
                    "这两个工具都通过当前平台运行，不自行生成或改写SQL。"
                    "必须根据问题选择lab_id，原样返回候选SQL和简短口径给主智能体query_db。"
                    "不需要先读取本地数据库结构；缺少要素时说明缺什么。"
                    "今天是 {today}。可用实验室：{labs}。"
                ),
            ),
        )
        if lab_provider == "bootcamp":
            for key, profile in list(profiles.items()):
                profiles[key] = replace(
                    profile,
                    config=replace(
                        profile.config,
                        agent_names=tuple(
                            name for name in profile.config.agent_names if name != "bailian"
                        ),
                    ),
                )
    specs = _assemble_agent_tools(
        agent_id,
        profiles=profiles,
        primitives=primitives,
        lab_ids=tuple(lab_ids),
        depth=0,
    )
    return ToolRegistry(specs)


def _assemble_agent_tools(
    agent_id: str,
    *,
    profiles: Mapping[str, AgentProfile],
    primitives: Mapping[str, ToolSpec],
    lab_ids: tuple[str, ...],
    depth: int,
) -> list[ToolSpec]:
    profile = profiles.get(agent_id)
    if profile is None:
        return []
    selected: list[ToolSpec] = []
    blocked = _NESTED_BLOCKED if depth > 0 else frozenset()
    for name in profile.config.tool_names:
        if name in blocked:
            continue
        spec = primitives.get(name)
        if spec is not None:
            selected.append(spec)
    if depth >= _MAX_DELEGATE_DEPTH:
        return selected
    for child_id in profile.config.agent_names:
        child = profiles.get(child_id)
        if child is None or not child.config.enabled or child.spec.kind != "sub":
            continue
        if child_id == agent_id:
            continue
        child_tools = ToolRegistry(
            _assemble_agent_tools(
                child_id,
                profiles=profiles,
                primitives=primitives,
                lab_ids=lab_ids,
                depth=depth + 1,
            )
        )
        selected.append(_build_delegate_tool(child.spec, child_tools, lab_ids))
    return selected


def _build_delegate_tool(
    spec: AgentSpec,
    child_tools: ToolRegistry,
    lab_ids: tuple[str, ...],
) -> ToolSpec:
    runner = NestedAgentRunner(lab_ids=lab_ids)
    parameters = _delegate_parameters(spec)

    async def execute(context: AgentToolContext, arguments: Mapping[str, Any]) -> ToolCallResult:
        return await runner.run(
            context=context,
            spec=spec,
            tools=child_tools,
            arguments=arguments,
        )

    return ToolSpec(
        name=spec.tool_name,
        description=spec.tool_description,
        parameters=parameters,
        executor=execute,
    )


def _delegate_parameters(spec: AgentSpec) -> dict[str, Any]:
    if spec.id == "lab_sql":
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "原子化的查数问题：单一意图，含产品 / 时间 / 口径",
                },
                "lab_id": {
                    "type": "string",
                    "description": "目标实验室，可选",
                },
            },
            "required": ["question"],
        }
    if spec.id == "bailian":
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用户原问题全文，或某个短词",
                },
                "lab_type": {
                    "type": "string",
                    "description": "对应实验室名称，可选",
                },
            },
            "required": ["query"],
        }
    return {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "交给子智能体的问题"},
        },
        "required": ["question"],
    }


def used_by_map(profiles: Sequence[AgentProfile]) -> dict[str, list[dict[str, str]]]:
    used: dict[str, list[dict[str, str]]] = {meta.name: [] for meta in TOOL_METAS}
    for profile in profiles:
        if not profile.config.enabled and not profile.spec.required:
            continue
        owner = {"id": profile.id, "name": profile.spec.name}
        for name in profile.config.tool_names:
            used.setdefault(name, []).append(owner)
    return used
