from __future__ import annotations

import asyncio
from xiaoying_quick.application.agent_run.local_tools import (
    build_field_recall_tool,
    build_generate_sql_tool,
    build_inspect_schema_tool,
    build_validate_sql_tool,
    build_value_recall_tool,
)
from xiaoying_quick.infrastructure.llm.client import JsonCompletion
from xiaoying_quick.infrastructure.source_db.local_catalog import ColumnInfo, SchemaCatalog, TableInfo
from xiaoying_quick.modules.agent import AgentToolContext


class FakeGateway:
    def __init__(self) -> None:
        self.catalog = SchemaCatalog(
            database="sales",
            dialect="sqlite",
            tables=(
                TableInfo(
                    name="sales",
                    comment="销量明细",
                    columns=(
                        ColumnInfo("sales", "brand", "TEXT", "品牌"),
                        ColumnInfo("sales", "channel", "TEXT", "渠道"),
                    ),
                ),
            ),
        )

    def inspect(self, tables=None):
        del tables
        return self.catalog

    def recall_fields(self, query, limit=16):
        del limit
        return [
            {
                "term": query,
                "table": "sales",
                "column": "channel",
                "data_type": "TEXT",
                "comment": "渠道",
                "table_comment": "销量明细",
                "score": 70,
            }
        ]

    def recall_values(self, query, table=None, column=None, max_values=24):
        del query, table, column, max_values
        return [{"table": "sales", "column": "channel", "comment": "渠道", "values": ["院外", "院内"]}]


def _context(**extras) -> AgentToolContext:
    extras.setdefault("local_source", FakeGateway())
    extras.setdefault("recall_settings", {"probe_values": True, "max_values": 24})
    return AgentToolContext(
        run_id="run-1",
        session_id="session-1",
        actor_id="user-1",
        emit=lambda event_type, payload: None,
        extras=extras,
    )


def test_inspect_schema_renders_ddl() -> None:
    result = asyncio.run(build_inspect_schema_tool().executor(_context(), {}))
    assert result.ok
    assert "CREATE TABLE sales" in result.output
    assert "brand" in result.payload["ddl"]


def test_validate_sql_reports_unknown_table() -> None:
    result = asyncio.run(
        build_validate_sql_tool().executor(_context(), {"sql": "select 1 from missing"})
    )
    assert result.ok is False
    assert result.payload["valid"] is False


def test_field_and_value_recall() -> None:
    fields = asyncio.run(build_field_recall_tool().executor(_context(), {"query": "院外"}))
    assert fields.ok
    assert "channel" in fields.output
    values = asyncio.run(build_value_recall_tool().executor(_context(), {"query": "院外"}))
    assert values.ok
    assert "院外" in values.output


def test_value_recall_respects_disabled_setting() -> None:
    result = asyncio.run(
        build_value_recall_tool().executor(
            _context(recall_settings={"probe_values": False, "max_values": 24}),
            {"query": "院外"},
        )
    )
    assert result.ok
    assert "关闭" in result.output


def test_generate_sql_returns_candidates() -> None:
    class Client:
        async def complete_json(self, **kwargs):
            del kwargs
            return JsonCompletion(
                request_id="req-1",
                payload={
                    "candidates": [
                        {
                            "candidate_no": 1,
                            "sql": "SELECT brand FROM sales",
                            "narrative": "按品牌列出",
                        }
                    ]
                },
            )

    result = asyncio.run(
        build_generate_sql_tool(("actual",)).executor(
            _context(llm_client=Client()),
            {"question": "品牌有哪些", "lab_id": "actual"},
        )
    )
    assert result.ok
    assert result.payload["sql"] == "SELECT brand FROM sales"
    assert result.payload["candidates"][0]["narrative"] == "按品牌列出"


def test_generate_sql_requires_question() -> None:
    result = asyncio.run(build_generate_sql_tool(("actual",)).executor(_context(), {}))
    assert result.ok is False
    assert "question" in result.output


def test_inspect_schema_without_gateway() -> None:
    result = asyncio.run(
        build_inspect_schema_tool().executor(
            AgentToolContext(
                run_id="r",
                session_id="s",
                actor_id="u",
                emit=lambda *args: None,
            ),
            {},
        )
    )
    assert result.ok is False
    assert "未配置" in result.output
