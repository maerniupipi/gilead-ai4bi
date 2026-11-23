"""Suggested-questions classify/generate parsing and silent failures."""

from __future__ import annotations

import asyncio
from typing import Any

from xiaoying_quick.application.suggest.prompts import generate_user_prompt
from xiaoying_quick.application.suggest.service import (
    _parse_questions,
    build_suggestions,
    format_answer_data,
)
from xiaoying_quick.modules.agent.events import AgentEventType, validate_agent_event
from xiaoying_quick.modules.runs.contracts import RunStatus
from xiaoying_quick.modules.runs.service import RunService


class _FakeClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self._payloads = list(payloads)
        self.calls: list[dict[str, Any]] = []

    async def complete_json(self, **kwargs: Any) -> Any:
        self.calls.append(dict(kwargs))

        class _Completion:
            def __init__(self, body: dict[str, Any]) -> None:
                self.payload = body

        if not self._payloads:
            raise RuntimeError("no payload")
        return _Completion(self._payloads.pop(0))


def test_parse_questions_requires_three_unique() -> None:
    assert _parse_questions({"questions": [{"text": "a"}, {"text": "b"}]}) is None
    assert _parse_questions(
        {"questions": [{"text": "a"}, {"text": "b"}, {"text": "c"}]}
    ) == [{"text": "a"}, {"text": "b"}, {"text": "c"}]


def test_generate_user_prompt_requires_answer_context() -> None:
    text = generate_user_prompt(
        question="各省份销量？",
        answer="东区领先，西区偏低。",
        answer_data="【取数表1】列：区域 | 销量\n  东 | 100",
        category="lab_kpi",
    )
    assert "东区领先" in text
    assert "取数表" in text
    assert "挖原因" in text
    assert "不要生成与原问相似" in text


def test_format_answer_data_from_tables_and_facts() -> None:
    text = format_answer_data(
        facts=["东区销量 100"],
        query_tables=[
            {"columns": ["区域", "销量"], "rows": [["东", 100], ["西", 40]]},
        ],
    )
    assert "东区销量 100" in text
    assert "区域 | 销量" in text


def test_build_suggestions_happy_path_uses_answer() -> None:
    client = _FakeClient(
        [
            {"category": "lab_kpi", "reason": "销量"},
            {
                "questions": [
                    {"text": "东区领先的主要产品驱动是什么？"},
                    {"text": "西区偏低是否集中在某几个省份？"},
                    {"text": "同比看东区优势是否扩大？"},
                ]
            },
        ]
    )
    result = asyncio.run(
        build_suggestions(
            client=client,
            question="各省份销量？",
            answer="东区销量最高，西区明显偏低。",
            answer_data="【取数表1】列：区域 | 销量\n  东 | 100\n  西 | 40",
        )
    )
    assert result is not None
    assert result["category"] == "lab_kpi"
    assert len(result["questions"]) == 3
    assert len(client.calls) == 2
    generate_prompt = client.calls[1]["user_prompt"]
    assert "东区销量最高" in generate_prompt
    assert "取数表1" in generate_prompt
    validate_agent_event(
        AgentEventType.SUGGEST_READY,
        {"questions": result["questions"], "category": result["category"]},
    )


def test_build_suggestions_silent_on_bad_category() -> None:
    client = _FakeClient([{"category": "nope"}])
    assert (
        asyncio.run(
            build_suggestions(client=client, question="hi", answer="你好呀")
        )
        is None
    )


def test_build_suggestions_respects_cancel() -> None:
    client = _FakeClient(
        [
            {"category": "chitchat", "reason": "闲聊"},
            {"questions": [{"text": "1"}, {"text": "2"}, {"text": "3"}]},
        ]
    )
    result = asyncio.run(
        build_suggestions(
            client=client,
            question="你好",
            answer="你好！",
            is_cancelled=lambda: True,
        )
    )
    assert result is None


class _MemRuns:
    def __init__(self) -> None:
        self.run = None

    def get(self, run_id: str):
        return self.run if self.run and self.run.id == run_id else None

    def find_by_idempotency(self, *args, **kwargs):
        return None

    def add(self, run):
        self.run = run

    def set_status(self, run_id, *, expected, target, now):
        assert self.run and self.run.id == run_id and self.run.status == expected
        from dataclasses import replace

        self.run = replace(self.run, status=target, updated_at=now, version=self.run.version + 1)
        return self.run

    def append_event(self, run_id, *, event_type, payload, now):
        return None

    def list_runs(self, **kwargs):
        return ()

    def list_children(self, parent_run_id: str):
        return ()

    def update_insight_meta(self, run_id, *, insight_meta, now):
        from dataclasses import replace

        assert self.run and self.run.id == run_id
        self.run = replace(self.run, insight_meta=dict(insight_meta), updated_at=now)
        return self.run

    def list_events(self, *args, **kwargs):
        from xiaoying_quick.shared.result import CursorPage

        return CursorPage(items=(), next_cursor=0, has_more=False)


def test_cancel_run_idempotent(monkeypatch=None) -> None:
    from datetime import datetime, timezone

    from xiaoying_quick.modules.identity import AuthenticatedPrincipal, Role
    from xiaoying_quick.modules.runs.contracts import RunRecord

    repo = _MemRuns()
    service = RunService(repo)
    now = datetime.now(timezone.utc)
    repo.run = RunRecord(
        id="run_1",
        owner_user_id="u1",
        session_id=None,
        question="q",
        status=RunStatus.RUNNING,
        idempotency_key=None,
        next_event_cursor=1,
        version=1,
        created_at=now,
        updated_at=now,
    )
    principal = AuthenticatedPrincipal(
        user_id="u1", username="a", display_name="Admin", role=Role.ADMIN
    )
    first = service.cancel_run(principal=principal, run_id="run_1")
    assert first.status is RunStatus.CANCELLED
    second = service.cancel_run(principal=principal, run_id="run_1")
    assert second.status is RunStatus.CANCELLED
    assert service.is_cancelled("run_1") is True
