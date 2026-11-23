"""Optional per-run tool/step budgets for the agent loop.

Both chat modes use the same unlimited loop. This optional value object is
retained for callers that explicitly need execution caps.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_KNOWLEDGE = frozenset(
    {
        "knowledge_search",
        "knowledge_read",
        "bailian_recall",
        "field_recall",
        "value_recall",
    }
)
_LAB = frozenset({"ask_lab", "generate_sql", "agent_lab_sql"})
_LEDGER = frozenset({"update_ledger"})
_QUERY = frozenset({"query_db"})


@dataclass(frozen=True)
class AgentLoopBudget:
    """Hard caps. ``None`` fields mean unlimited for that dimension."""

    max_steps: int | None = None
    max_update_ledger: int | None = None
    max_knowledge: int | None = None
    max_lab: int | None = None
    max_query_db: int | None = None
    repeat_block_at: int | None = None
    skip_suggest: bool = False
    skip_sql_review: bool = False
    system_addon: str = ""

    def deny(self, name: str, counts: Mapping[str, int]) -> str | None:
        """Return a refusal message if this tool call should not run."""

        tool = str(name or "").strip()
        if tool in _LEDGER and self.max_update_ledger is not None:
            used = int(counts.get("update_ledger", 0))
            if used >= self.max_update_ledger:
                return (
                    f"工具调用台账已写满 {self.max_update_ledger} 次，禁止再 update_ledger。"
                    "请基于已有口径直接 ask_lab/query_db 或给出结论。"
                )
        if tool in _KNOWLEDGE and self.max_knowledge is not None:
            used = int(counts.get("knowledge", 0))
            if used >= self.max_knowledge:
                return (
                    f"工具调用知识检索已达 {self.max_knowledge} 次上限。"
                    "不要再搜文档；请直接取数或结束作答。"
                )
        if tool in _LAB and self.max_lab is not None:
            used = int(counts.get("lab", 0))
            if used >= self.max_lab:
                return (
                    f"工具调用实验室调用已达 {self.max_lab} 次上限。"
                    "请用已有 SQL/结果作答，或改参数极少次 query_db；禁止继续连环生成 SQL。"
                )
        if tool in _QUERY and self.max_query_db is not None:
            used = int(counts.get("query_db", 0))
            if used >= self.max_query_db:
                return (
                    f"工具调用 query_db 已达 {self.max_query_db} 次上限。"
                    "请基于已确立事实直接给出简短结论，禁止再查。"
                )
        return None

    def record(self, name: str, counts: dict[str, int]) -> None:
        tool = str(name or "").strip()
        if tool in _LEDGER:
            counts["update_ledger"] = int(counts.get("update_ledger", 0)) + 1
        elif tool in _KNOWLEDGE:
            counts["knowledge"] = int(counts.get("knowledge", 0)) + 1
        elif tool in _LAB:
            counts["lab"] = int(counts.get("lab", 0)) + 1
        elif tool in _QUERY:
            counts["query_db"] = int(counts.get("query_db", 0)) + 1


__all__ = ["AgentLoopBudget"]
