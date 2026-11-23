"""Workbook evidence and clarification choices must not silently invent a meaning."""

from __future__ import annotations

import asyncio
import io
import json
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from xiaoying_quick.application.agent_run.chart_tool import build_present_chart_tool
from xiaoying_quick.application.agent_run.loop import _clarify_key
from xiaoying_quick.application.agent_run.tools import build_ask_user_tool
from xiaoying_quick.application.agent_run.workbook_tool import build_inspect_workbook_tool
from xiaoying_quick.infrastructure.chatbots import ChatbotStore
from xiaoying_quick.infrastructure.workbook_lab import WorkbookLab
from xiaoying_quick.modules.agent import AgentToolContext
from xiaoying_quick.shared.errors import ValidationFailed


def context(**extras):
    return AgentToolContext(
        run_id="run-1", session_id="session-1", actor_id="owner",
        emit=lambda *_: None, extras=extras,
    )


def test_inspection_reports_all_rows_and_bounds_examples_and_distinct_tracking():
    rows = [[index, None, 0.9] for index in range(1200)]
    rows.append(["未填", " ", "90%"])
    lab = WorkbookLab([{
        "filename": "业务.xlsx", "sheets": [{
            "table": "wb_owned_1", "name": "明细", "columns": ["编号", "金额", "达成率"],
            "rows": rows,
        }],
    }], lambda: None, None, None)
    spec = build_inspect_workbook_tool()
    result = asyncio.run(spec.executor(context(workbook_inspect=lab.inspect), {
        "table": "wb_owned_1", "columns": ["编号", "金额", "达成率"],
    }))
    assert result.ok
    data = json.loads(result.output)
    assert data["row_count"] == 1201
    number, amount, rate = data["fields"]
    assert number["distinct_count"] is None and number["distinct_lower_bound"] == 1001
    assert number["type_counts"] == {"number": 1200, "text": 1}
    assert number["numeric_max"] == 1199
    assert len(number["examples"]) == 3
    assert amount["empty_count"] == 1201
    assert rate["type_counts"] == {"number": 1200, "text": 1}
    assert rate["excel_formats"] == []
    with pytest.raises(ValidationFailed):
        lab.inspect("wb_other_1")
    with pytest.raises(ValidationFailed):
        lab.inspect("wb_owned_1", ["不存在"])
    with pytest.raises(ValidationFailed):
        lab.inspect("wb_owned_1", ["编号", "编号"])


def test_upload_retains_display_format_evidence_without_rescaling_values(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.append(["金额", "达成率", "编码"])
    sheet.append([1.25, 0.9, "0007"])
    sheet["A2"].number_format = '0.00"万元"'
    sheet["B2"].number_format = "0.0%"
    output = io.BytesIO()
    book.save(output)
    store = ChatbotStore(tmp_path / "books.sqlite3", xlsx_only=True)
    parsed = store.upload_personal_workbook("xlsx", "owner", "未知业务.xlsx", output.getvalue())
    restored = ChatbotStore(store.path, xlsx_only=True).personal_workbooks("xlsx", "owner")
    lab = WorkbookLab(restored, lambda: None, None, None)
    profile = lab.inspect(parsed["sheets"][0]["table"])
    amount, rate, code = profile["fields"]
    assert amount["examples"] == [1.25]
    assert amount["excel_formats"] == ['0.00"万元"']
    assert rate["examples"] == [0.9] and rate["excel_formats"] == ["0.0%"]
    assert code["examples"] == ["0007"] and code["type_counts"] == {"text": 1}


def test_xlsx_clarification_has_no_unsupported_default_and_explains_impact():
    spec = build_ask_user_tool(recommend_choices=False)
    arguments = {"questions": [{
        "question": "销售使用开票金额还是回款金额？",
        "why": "这两列对应的业务环节不同，会影响销售额和达成率。",
        "options": ["开票金额", "回款金额"],
    }]}
    result = asyncio.run(spec.executor(context(), arguments))
    assert result.ok and result.suspended
    group = result.payload["groups"][0]
    assert group["why"] == arguments["questions"][0]["why"]
    assert not any(option["recommended"] for option in group["options"])
    arguments["questions"][0]["recommended_index"] = 1
    result = asyncio.run(spec.executor(context(), arguments))
    assert not any(option["recommended"] for option in result.payload["groups"][0]["options"])
    generic = build_ask_user_tool()
    result = asyncio.run(generic.executor(context(), arguments))
    assert result.payload["groups"][0]["options"][1]["recommended"] is True
    arguments["questions"][0]["recommended_index"] = 3
    assert not asyncio.run(generic.executor(context(), arguments)).ok


def test_long_clarification_prompts_keep_separate_ledger_keys():
    prefix = "在2026年全年度医药经营数据工作簿的销售明细工作表中，" * 2
    assert _clarify_key(prefix + "金额采用哪个字段？") != _clarify_key(prefix + "数量是什么单位？")
    assert len(_clarify_key(prefix + "金额采用哪个字段？")) <= 40


def test_chart_schema_requires_confirmed_units_on_the_xlsx_path():
    spec = build_present_chart_tool(require_units=True)
    assert "metrics" in spec.parameters["required"]
    assert "unit" in spec.parameters["properties"]["metrics"]["items"]["required"]
    artifact = {
        "run_id": "run-1", "kind": "tool_result", "payload": {
            "name": "query_db", "ok": True,
            "payload": {"columns": ["月份", "销售金额"], "rows": [["2026-10", 30]]},
        },
    }
    artifacts = SimpleNamespace(get=lambda _: artifact, append=lambda **_: "chart-1")
    tool_context = context(artifacts=artifacts)
    arguments = {"query_ref": "query-1", "title": "销售"}
    missing = asyncio.run(spec.executor(tool_context, arguments))
    assert not missing.ok and "单位" in missing.output
    arguments["metrics"] = [{"column": "销售金额", "unit": "万元"}]
    confirmed = asyncio.run(spec.executor(tool_context, arguments))
    assert confirmed.ok
    assert confirmed.payload["kpis"][0]["value"] == 30
    assert confirmed.payload["kpis"][0]["unit"] == "万元"
