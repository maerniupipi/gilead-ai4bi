import asyncio
from types import SimpleNamespace

import pytest

from xiaoying_quick.infrastructure.lab_http.atomic_sql import render_sql_answer, resolve_query
from xiaoying_quick.infrastructure.lab_http.gilead import GileadLabs, field_recall_result
from xiaoying_quick.modules.agent.contracts import AgentToolContext, ToolCallResult, ToolSpec


class Records:
    def __init__(self):
        self.rows = {}

    def tool_records(self, run_id, name):
        return self.rows.get((run_id, name), [])

    def add(self, run_id, name, result):
        self.rows.setdefault((run_id, name), []).append({"ok": result.ok, "payload": result.payload})


def test_database_value_matches_keep_the_exact_field_and_value():
    candidates = [
        {"type": "table_value", "table": "monthly", "field": "monthly&&platform", "text": "医院"},
        {"type": "table_value", "table": "monthly", "field": "monthly&&terminal", "text": "医院进药"},
    ]
    match = field_recall_result("字段里有“医院进药”吗", candidates, "ddi")
    assert match.payload["items"] == [candidates[1]]
    assert match.payload["exact_matches"] == [{"表": "monthly", "字段": "terminal", "取值": "医院进药"}]
    assert "platform" not in match.output
    assert "exact_matches" not in field_recall_result("其他终端", candidates, "ddi").payload


def test_generation_is_required_per_run_and_queries_can_combine_atoms(monkeypatch):
    asyncio.run(_check_lab_tools(monkeypatch))


async def _check_lab_tools(monkeypatch):
    store = Records()
    calls = []
    connection = SimpleNamespace(pair_names={"ddi":"DDI"})
    labs = GileadLabs(connection)
    async def invoke(role, pair, question, context):
        if role == "recall":
            return {"kind": role, "items": [{"type":"table_value","text":"上海市"},
                                            {"type":"knowledge_term","text":"销售金额含义"},
                                            {"type":"sql_sample","content":"sample"}]}
        if question == "缺少哪个期间":
            return {"kind":"clarification","message":"请指定期间"}
        return {"kind": role, "sql": f"SELECT {10 if question == '七月' else 12} AS amount"}
    monkeypatch.setattr(labs, "invoke", invoke)
    async def query(ctx, args):
        calls.append(args["sql"])
        return ToolCallResult(True, "查询成功", {"sql":args["sql"]})
    tool = labs.query_tool(ToolSpec("query_db", "", {}, query))
    ctx = AgentToolContext(run_id="r1", session_id="session", actor_id="admin",
                           emit=lambda *_: None, extras={"artifacts":store})
    recall = await labs.tool("recall", ["ddi"]).executor(ctx, {"question":"金额", "lab_id":"ddi"})
    assert [item["type"] for item in recall.payload["items"]] == ["table_value"]
    assert not (await tool.executor(ctx, {"sql":"SELECT amount FROM q1"})).ok
    assert not calls
    with pytest.raises(ValueError):
        render_sql_answer("SELECT amount FROM sales", store, "r1")
    for question, ref in [("七月", "q1"), ("八月", "q2")]:
        result = await labs.tool("sql", ["ddi"]).executor(ctx, {"question":question, "lab_id":"ddi"})
        assert result.payload["sql_ref"] == ref
        store.add("r1", "generate_sql", result)
    outer = "SELECT b.amount - a.amount AS change FROM q1 a CROSS JOIN q2 b"
    outcome = await tool.executor(ctx, {"sql": outer})
    assert outcome.ok and outcome.payload["source_sql_refs"] == ["q1","q2"]
    assert "SELECT 10 AS amount" in calls[0] and "SELECT 12 AS amount" in calls[0]
    store.add("r1", "query_db", outcome)
    assert calls[0] in render_sql_answer("[[SQL:result]]", store, "r1")
    assert "SELECT 10 AS amount" in render_sql_answer("[[SQL:q1]]", store, "r1")
    with pytest.raises(ValueError):
        render_sql_answer("[[SQL:q1]]", store, "next_run")
    unresolved = await labs.tool("sql", ["ddi"]).executor(ctx, {"question":"缺少哪个期间", "lab_id":"ddi"})
    store.add("r1","generate_sql",unresolved)
    assert not (await tool.executor(ctx, {})).ok
    assert (await tool.executor(ctx, {"sql":"q1"})).ok
    assert not (await tool.executor(ctx, {"sql":"SELECT amount FROM sales"})).ok


@pytest.mark.parametrize("requested", ["SELECT 1", "SELECT * FROM q2", "SELECT * FROM public.q1",
                                    "SELECT * FROM q1; SELECT 2", "SELECT total FROM business_data"])
def test_derived_query_requires_current_lab_results(requested):
    legacy = [{"ok":True, "payload":{"sql":"SELECT 1 AS amount"}}]
    with pytest.raises(ValueError):
        resolve_query(requested, legacy)
    assert resolve_query("q1", legacy) == ("SELECT 1 AS amount", ["q1"])


def test_analysis_ctes_and_unions_resolve_to_current_atomic_results():
    records = [{"ok":True, "payload":{"sql":"SELECT 2 AS actual"}}]
    query = "WITH totals AS (SELECT SUM(actual)::numeric AS v FROM q1) SELECT v FROM totals UNION ALL SELECT actual FROM q1"
    sql, refs = resolve_query(query, records)
    assert refs == ["q1"] and sql.count("WITH ") == 1 and "totals AS" in sql
    for bad in ("WITH q1 AS (SELECT * FROM q1) SELECT * FROM q1",
                "WITH totals AS (SELECT * FROM elsewhere) SELECT * FROM totals JOIN q1 ON TRUE"):
        with pytest.raises(ValueError):
            resolve_query(bad, records)


def test_sql_only_reply_renders_the_saved_query_even_when_the_model_drafts_its_own():
    store = Records()
    store.rows["run", "generate_sql"] = [{"ok": True, "payload": {"sql": "SELECT 42 AS amount"}}]
    for draft in ("SELECT 12 AS amount", "```sql\n[[SQL:q1]]\n```", "[[SQL:q1]]"):
        assert render_sql_answer(draft, store, "run") == "```sql\nSELECT 42 AS amount\n```"
    with pytest.raises(ValueError):
        render_sql_answer("SELECT 12 AS amount", store, "other-run")
    store.rows["run", "generate_sql"].append({"ok": True, "payload": {"sql": "SELECT 20 AS target"}})
    with pytest.raises(ValueError):
        render_sql_answer("SELECT 12 AS amount", store, "run")
