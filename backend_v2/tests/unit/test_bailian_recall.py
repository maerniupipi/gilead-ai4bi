from __future__ import annotations

import asyncio
import json

from xiaoying_quick.application.agent_run.loop import AGENT_SYSTEM_PROMPT
from xiaoying_quick.application.agent_run.tools import build_bailian_recall_tool
from xiaoying_quick.infrastructure.source_db.bailian_runner import (
    format_bailian_knowledge,
    parse_bailian_recall_payload,
)
from xiaoying_quick.modules.agent import AgentToolContext


def _context(**extras) -> AgentToolContext:
    return AgentToolContext(
        run_id="run-1",
        session_id="session-1",
        actor_id="user-1",
        emit=lambda event_type, payload: None,
        extras=extras,
    )


def test_parse_end_event_knowledge_json() -> None:
    payload = {
        "end": True,
        "content": [
            {
                "type": "text",
                "text": {
                    "value": json.dumps(
                        {
                            "知识词条": {"院外": "ddi_category in ('From DTP')"},
                            "NER": {"院外": "ddi_category='From DTP'"},
                            "候选值": {"tw_performance_sales_cvh.inst_type": ["医院", "药店"]},
                        },
                        ensure_ascii=False,
                    )
                },
            }
        ],
    }
    body = parse_bailian_recall_payload(payload)
    assert isinstance(body, dict)
    assert body["知识词条"]["院外"].startswith("ddi_category")
    rendered = format_bailian_knowledge(body)
    assert "知识词条" in rendered
    assert "院外" in rendered
    assert "候选值" in rendered


def test_format_raw_text_when_not_json() -> None:
    payload = {"content": [{"text": {"value": "没有结构化词条"}}]}
    body = parse_bailian_recall_payload(payload)
    assert format_bailian_knowledge(body) == "没有结构化词条"


def test_tool_requires_lab_type() -> None:
    result = asyncio.run(
        build_bailian_recall_tool(("actual", "demand")).executor(
            _context(bailian_recall=lambda query, lab_type: "ok"),
            {"query": "院外"},
        )
    )
    assert result.ok is False
    assert "lab_type" in result.output


def test_tool_rejects_unknown_lab_type() -> None:
    result = asyncio.run(
        build_bailian_recall_tool(("actual", "demand")).executor(
            _context(bailian_recall=lambda query, lab_type: "ok"),
            {"query": "院外", "lab_type": "unknown"},
        )
    )
    assert result.ok is False
    assert "actual" in result.output


def test_tool_returns_recall_text() -> None:
    result = asyncio.run(
        build_bailian_recall_tool(("actual",)).executor(
            _context(bailian_recall=lambda query, lab_type: f"{lab_type}:{query}"),
            {"query": "院外", "lab_type": "actual"},
        )
    )
    assert result.ok is True
    assert "actual:院外" in result.output
    assert result.payload["lab_type"] == "actual"


def test_tool_skips_when_unconfigured() -> None:
    result = asyncio.run(
        build_bailian_recall_tool(("actual",)).executor(
            _context(),
            {"query": "院外", "lab_type": "actual"},
        )
    )
    assert result.ok is True
    assert "未配置" in result.output


def test_prompt_describes_bailian_as_knowledge_recall() -> None:
    assert "召回智能体" in AGENT_SYSTEM_PROMPT
    assert "field_recall" in AGENT_SYSTEM_PROMPT
    assert "用户原问题全文" in AGENT_SYSTEM_PROMPT
    assert "某个短词" in AGENT_SYSTEM_PROMPT
