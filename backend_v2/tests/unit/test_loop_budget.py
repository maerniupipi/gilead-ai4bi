"""Optional tool budgets remain independent of chat mode."""

from xiaoying_quick.application.agent_run.loop_budget import (
    AgentLoopBudget,
)


def test_explicit_budget_caps_ledger_knowledge_lab_query() -> None:
    budget = AgentLoopBudget(max_update_ledger=4, max_knowledge=3, max_lab=3, max_query_db=3)
    counts: dict[str, int] = {}
    assert budget.deny("update_ledger", counts) is None
    for _ in range(budget.max_update_ledger or 0):
        budget.record("update_ledger", counts)
    assert "台账" in (budget.deny("update_ledger", counts) or "")

    counts = {}
    for _ in range(budget.max_knowledge or 0):
        budget.record("knowledge_search", counts)
    assert "知识检索" in (budget.deny("knowledge_read", counts) or "")

    counts = {}
    for _ in range(budget.max_lab or 0):
        budget.record("generate_sql", counts)
    assert "实验室" in (budget.deny("ask_lab", counts) or "")

    counts = {}
    for _ in range(budget.max_query_db or 0):
        budget.record("query_db", counts)
    assert "query_db" in (budget.deny("query_db", counts) or "")


def test_unlimited_budget_never_denies() -> None:
    budget = AgentLoopBudget()
    counts = {"update_ledger": 99, "knowledge": 99, "lab": 99, "query_db": 99}
    assert budget.deny("update_ledger", counts) is None
    assert budget.deny("knowledge_search", counts) is None
    assert budget.deny("ask_lab", counts) is None
    assert budget.deny("query_db", counts) is None
