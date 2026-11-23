"""The progress ledger: caliber card, anchoring, persistence and priming."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from xiaoying_quick.application.agent_run.loop import (
    AgentRunService,
    _anchor_block,
    _clarify_key,
    _fact_text,
    _load_facts,
    _load_hops,
    _load_ledger,
    _memory_conclusion,
    _question_caliber_slots,
    _trim_ledger,
)
from xiaoying_quick.application.agent_run.tools import (
    build_knowledge_read_tool,
    build_update_ledger_tool,
)
from xiaoying_quick.infrastructure.llm import ToolCallFragment
from xiaoying_quick.modules.agent import ToolCallResult
from xiaoying_quick.modules.clarification import (
    ClarificationAnswer,
    ClarificationCase,
    ClarificationChoice,
    ClarificationQuestion,
    ClarificationReason,
    ClarificationStatus,
)
from xiaoying_quick.modules.context import RecallSourceType


class _CaseStore:
    def __init__(self, answered: list | None = None) -> None:
        self.cases: list = []
        self.answered = answered or []

    def get(self, case_id: str):
        return next((case for case in self.cases if case.case_id == case_id), None)

    def for_run(self, run_id: str):
        matches = [case for case in self.cases if case.run_id == run_id]
        return max(matches, key=lambda case: case.version) if matches else None

    def save(self, case) -> None:
        existing = self.get(case.case_id)
        if existing is not None:
            self.cases[self.cases.index(existing)] = case
        else:
            self.cases.append(case)

    def list_answered_for_session(self, session_id: str):
        return [case for case in self.answered if case.session_id == session_id]


def _build_agent(store=None, dependencies=None) -> AgentRunService:
    tools = MagicMock()
    tools.parse_arguments.side_effect = lambda raw: __import__("json").loads(raw or "{}")
    tools.execute = AsyncMock(return_value=ToolCallResult(ok=True, output="ok", payload={}))
    return AgentRunService(
        runs=MagicMock(),
        chats=MagicMock(),
        artifacts=MagicMock(),
        clarifications=store or _CaseStore(),
        model_registry=MagicMock(),
        tools=tools,
        lab_ids=(),
        tool_dependencies=dependencies or {},
        checkpoint=lambda: None,
    )


def test_invalid_model_configuration_emits_a_visible_failure_without_retry() -> None:
    agent = _build_agent()
    agent._model_registry.client.side_effect = ValueError("invalid endpoint")
    asyncio.run(agent._loop(
        actor_id="owner", run_id="run-config-error", session=MagicMock(),
        messages=[], turn_messages=[], step=0,
    ))
    events = [call.kwargs for call in agent._runs.append_event.call_args_list]
    failure = next(event for event in events if event["event_type"] == "agent.failed")
    assert failure["payload"]["code"] == "MODEL_CONFIG_INVALID"
    assert "模型管理" in failure["payload"]["message"]
    agent._model_registry.client.assert_called_once()


# ------------------------------------------------------------- pure helpers


def test_trim_ledger_drops_oldest_calibers_but_keeps_scopes() -> None:
    entries = [{"step": 0, "kind": "scope", "text": "口径A"}]
    entries += [
        {"step": index, "kind": "caliber", "text": f"要素{index}"} for index in range(1, 30)
    ]
    trimmed = _trim_ledger(entries)
    assert len(trimmed) == 20
    assert trimmed[0]["kind"] == "scope"
    assert trimmed[0]["text"] == "口径A"
    # The oldest caliber entries were dropped, the newest kept.
    assert trimmed[1]["text"] == "要素11"
    assert trimmed[-1]["text"] == "要素29"


def test_anchor_block_lists_question_calibers_scopes_and_facts() -> None:
    ledger = [
        {"step": 0, "kind": "caliber", "text": "时间窗口：YTD（问题原文，待确认）"},
        {"step": 3, "kind": "time", "text": "外部市场数据最新月=2026-05"},
        {"step": 0, "kind": "scope", "text": "只查重点民营机构"},
    ]
    block = _anchor_block("倍择瑞的 EI 是多少？", ledger, ["查询成功，共 3 行"])
    assert "原始问题：倍择瑞的 EI 是多少？" in block
    assert "时间窗口：YTD（问题原文，待确认）" in block
    assert "已确认时间事实" in block
    assert "外部市场数据最新月=2026-05" in block
    assert "只查重点民营机构" in block
    assert "查询成功，共 3 行" in block


def test_load_ledger_is_defensive() -> None:
    loaded = _load_ledger(
        [{"step": 1, "kind": "caliber", "text": "a"}, "junk", {"kind": "scope"}, None]
    )
    assert loaded == [{"step": 1, "kind": "caliber", "text": "a"}]
    assert _load_ledger(None) == []
    assert _load_facts(["x", "", 5]) == ["x"]


def test_load_ledger_preserves_keys() -> None:
    loaded = _load_ledger([{"step": 1, "kind": "scope", "text": "BU=渠道", "key": "BU"}])
    assert loaded == [{"step": 1, "kind": "scope", "text": "BU=渠道", "key": "BU"}]


def test_load_hops_is_defensive() -> None:
    hops = _load_hops(
        [
            {"sql": "SELECT 1", "columns": ["x"], "rows": [[1]], "question": "q", "row_count": 1},
            {"sql": ""},
            "junk",
        ]
    )
    assert hops[0]["sql"] == "SELECT 1"
    assert hops[0]["rows"] == [[1]]
    assert _load_hops(None) == []


def test_fact_text_summarizes_sql_and_rows() -> None:
    text = _fact_text(
        '{"sql": "SELECT  province,  amount FROM sales LIMIT 3"}',
        {"rows": [["广东", 100], ["江苏", 90]]},
    )
    assert "共 2 行" in text
    assert "SELECT province, amount FROM sales LIMIT 3" in text
    assert "广东" in text


# ------------------------------------------------------------ loop capture


def test_query_db_review_failure_does_not_record_fact_or_hop() -> None:
    agent = _build_agent()
    agent._run_id = "run-1"
    agent._last_lab_question = "安达唐销量"
    agent._tools.execute = AsyncMock(
        return_value=ToolCallResult(
            ok=True,
            output="查询成功",
            payload={"sql": "SELECT 1", "columns": ["x"], "rows": [[1]]},
        )
    )
    client = MagicMock()
    client.complete_json = AsyncMock(
        return_value=SimpleNamespace(
            payload={"ok": False, "uncertain": False, "missing": ["时间窗口"], "reason": "无日期"}
        )
    )
    messages: list = []
    asyncio.run(
        agent._execute_call(
            actor_id="user-1",
            run_id="run-1",
            session=MagicMock(id="session-1"),
            step=2,
            call=ToolCallFragment(id="call-1", name="query_db", arguments='{"sql": "SELECT 1"}'),
            messages=messages,
            turn_messages=[],
            client=client,
        )
    )
    assert agent._facts == []
    assert agent._hops == []
    assert "不可作为最终事实" in messages[-1].content


def test_query_db_success_records_an_internal_fact() -> None:
    agent = _build_agent()
    agent._run_id = "run-1"
    agent._tools.execute = AsyncMock(
        return_value=ToolCallResult(
            ok=True,
            output="查询成功",
            payload={"sql": "SELECT 1", "columns": ["x"], "rows": [[1]]},
        )
    )
    asyncio.run(
        agent._execute_call(
            actor_id="user-1",
            run_id="run-1",
            session=MagicMock(id="session-1"),
            step=2,
            call=ToolCallFragment(id="call-1", name="query_db", arguments='{"sql": "SELECT 1"}'),
            messages=[],
            turn_messages=[],
        )
    )
    # Facts anchor the model but never reach the caliber card.
    assert len(agent._facts) == 1
    assert "共 1 行" in agent._facts[0]
    assert agent._ledger == []
    ledger_events = [
        call
        for call in agent._runs.append_event.call_args_list
        if call.kwargs.get("event_type") == "agent.ledger.updated"
    ]
    assert ledger_events == []


def test_active_scopes_flow_from_ledger() -> None:
    agent = _build_agent()
    agent._ledger = [
        {"step": 0, "kind": "scope", "text": "时间窗口=YTD"},
        {"step": 0, "kind": "caliber", "text": "产品：安达唐"},
    ]
    assert agent._active_scopes() == ("时间窗口=YTD",)


def test_checkpoint_persists_ledger_and_facts() -> None:
    agent = _build_agent()
    agent._ledger = [{"step": 1, "kind": "caliber", "text": "产品：安达唐"}]
    agent._facts = ["查询成功，共 1 行"]
    agent._save_checkpoint("run-1", 1, [], pending=None)
    payload = agent._artifacts.append.call_args.kwargs["payload"]
    assert payload["ledger"] == agent._ledger
    assert payload["facts"] == agent._facts


# ----------------------------------------------------------------- priming


def test_priming_seeds_memory_and_clarification_scopes() -> None:
    question = ClarificationQuestion(
        question_id="question-1",
        prompt="按哪种口径？",
        reason=ClarificationReason.CRITICAL_SLOT_AMBIGUITY,
        choices=(ClarificationChoice(choice_id="choice-1", label="金额"),),
        allow_free_text=True,
    )
    answered_case = ClarificationCase(
        case_id="case-old",
        run_id="run-old",
        session_id="session-1",
        frame_id="run-old",
        status=ClarificationStatus.ANSWERED,
        questions=(question,),
        created_at=datetime.now(timezone.utc),
        answers=(
            ClarificationAnswer(
                question_id="question-1",
                answered_at=datetime.now(timezone.utc),
                free_text="金额",
            ),
        ),
        answered_at=datetime.now(timezone.utc),
    )
    store = _CaseStore(answered=[answered_case])
    broker = MagicMock()
    hit = SimpleNamespace(
        source_type=RecallSourceType.PERSONAL_MEMORY,
        content=(
            "原始问题：查销量\n澄清问题：机构范围？\n用户结论：只查重点民营机构\n"
            "（系统依据本轮澄清自动记录）"
        ),
    )
    broker.recall.return_value = SimpleNamespace(items=(hit,))
    agent = _build_agent(store=store, dependencies={"context_broker": broker})
    agent._run_id = "run-1"

    agent._prime_context(
        actor_id="user-1", run_id="run-1", session_id="session-1", question="销量？"
    )

    scopes = [entry["text"] for entry in agent._ledger if entry["kind"] == "scope"]
    # The clarification memory is reduced to its conclusion line.
    assert "只查重点民营机构" in scopes
    assert not any("原始问题" in scope for scope in scopes)
    assert any("按哪种口径？" in scope and "金额" in scope for scope in scopes)
    assert all(entry.get("key") for entry in agent._ledger if entry["kind"] == "scope")


def test_priming_survives_a_broken_broker() -> None:
    broker = MagicMock()
    broker.recall.side_effect = RuntimeError("recall down")
    agent = _build_agent(dependencies={"context_broker": broker})
    agent._run_id = "run-1"
    agent._prime_context(
        actor_id="user-1", run_id="run-1", session_id="session-1", question="销量？"
    )
    assert agent._ledger == []


# ------------------------------------------------------- caliber slot parsing


def test_question_caliber_slots_seed_only_the_time_window() -> None:
    # Products/institutions/qualifiers are written by the model via
    # update_ledger; the seed sticks to the time token from the question.
    slots = _question_caliber_slots("耐信 H2 的销量是多少？", None)
    assert slots == ["时间窗口：H2（问题原文，待确认）"]
    assert _question_caliber_slots("销量是多少？", None) == []


def test_update_ledger_upsert_replaces_same_key_entries() -> None:
    agent = _build_agent()
    agent._run_id = "run-1"
    agent._tools.execute = AsyncMock(
        return_value=ToolCallResult(
            ok=True,
            output="已更新进度台账：Severe Asthma（术语映射）。",
            payload={
                "entry": {
                    "key": "Severe Asthma",
                    "kind": "term",
                    "text": "重度哮喘适应症人群（RESP）",
                }
            },
        )
    )
    asyncio.run(
        agent._execute_call(
            actor_id="user-1",
            run_id="run-1",
            session=MagicMock(id="session-1"),
            step=2,
            call=ToolCallFragment(id="call-1", name="update_ledger", arguments="{}"),
            messages=[],
            turn_messages=[],
        )
    )
    entries = [entry for entry in agent._ledger if entry.get("key")]
    assert len(entries) == 1
    assert entries[0]["text"] == "重度哮喘适应症人群（RESP）"

    # A second call with the same key replaces the entry instead of stacking.
    agent._tools.execute = AsyncMock(
        return_value=ToolCallResult(
            ok=True,
            output="ok",
            payload={
                "entry": {
                    "key": "Severe Asthma",
                    "kind": "qualifier",
                    "text": "限定重度哮喘人群，排除轻中度",
                }
            },
        )
    )
    asyncio.run(
        agent._execute_call(
            actor_id="user-1",
            run_id="run-1",
            session=MagicMock(id="session-1"),
            step=4,
            call=ToolCallFragment(id="call-2", name="update_ledger", arguments="{}"),
            messages=[],
            turn_messages=[],
        )
    )
    keyed = [entry for entry in agent._ledger if entry.get("key") == "Severe Asthma"]
    assert len(keyed) == 1
    assert keyed[0]["kind"] == "qualifier"
    assert keyed[0]["text"] == "限定重度哮喘人群，排除轻中度"


def test_update_ledger_tool_validates_its_arguments() -> None:
    spec = build_update_ledger_tool()
    context = MagicMock()
    good = asyncio.run(
        spec.executor(
            context,
            {"key": "中南大学湘雅医院", "kind": "constant", "text": "机构常量，顶级三甲"},
        )
    )
    assert good.ok
    assert good.payload["entry"]["key"] == "中南大学湘雅医院"

    bad_kind = asyncio.run(spec.executor(context, {"key": "x", "kind": "nope", "text": "一二"}))
    assert not bad_kind.ok
    time_kind = asyncio.run(
        spec.executor(
            context,
            {"key": "数据最新月", "kind": "time", "text": "外部市场数据最新月=2026-05"},
        )
    )
    assert time_kind.ok and time_kind.payload["entry"]["kind"] == "time"
    missing_key = asyncio.run(spec.executor(context, {"kind": "term", "text": "一二"}))
    assert not missing_key.ok
    short_text = asyncio.run(spec.executor(context, {"key": "x", "kind": "term", "text": "一"}))
    assert not short_text.ok


def test_knowledge_read_resolves_nested_paths(tmp_path) -> None:
    # Docs live under a nested folder; a guessed short path must still land.
    nested = tmp_path / "项目知识文档" / "labs"
    nested.mkdir(parents=True)
    (nested / "actual.md").write_text("# actual 实验室\n职责说明", encoding="utf-8")
    spec = build_knowledge_read_tool(tmp_path)

    result = asyncio.run(spec.executor(MagicMock(), {"path": "labs/actual.md"}))
    assert result.ok
    assert "职责说明" in result.output
    assert result.payload["path"].replace("\\", "/") == "项目知识文档/labs/actual.md"

    missing = asyncio.run(spec.executor(MagicMock(), {"path": "labs/nope.md"}))
    assert not missing.ok


def test_knowledge_read_works_with_relative_root(tmp_path, monkeypatch) -> None:
    # Production often sets XIAOYING_KNOWLEDGE_ROOT=../knowledge_gilead.
    # Fuzzy match must not raise ValueError from mixed relative/absolute Paths.
    docs = tmp_path / "knowledge_gilead" / "项目知识文档" / "labs"
    docs.mkdir(parents=True)
    (docs / "actual.md").write_text("# actual\n上海口径", encoding="utf-8")
    cwd = tmp_path / "backend_v2"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    spec = build_knowledge_read_tool(Path("../knowledge_gilead"))

    result = asyncio.run(spec.executor(MagicMock(), {"path": "labs/actual.md"}))
    assert result.ok
    assert "上海口径" in result.output

    prefixed = asyncio.run(
        spec.executor(
            MagicMock(),
            {"path": "../knowledge_gilead/项目知识文档/labs/actual.md"},
        )
    )
    assert prefixed.ok
    assert "上海口径" in prefixed.output


def test_memory_conclusion_extracts_the_conclusion_line() -> None:
    content = "原始问题：X\n澄清问题：Y\n用户结论：只查重点民营机构\n（系统自动记录）"
    assert _memory_conclusion(content) == "只查重点民营机构"
    assert _memory_conclusion("以后默认按金额口径") == "以后默认按金额口径"


# ----------------------------------------------------- multi-turn inheritance


def test_inherit_ledger_seeds_from_last_completed_turn() -> None:
    agent = _build_agent()
    agent._run_id = "run-2"
    agent._ledger = [{"step": 0, "kind": "scope", "text": "只查重点民营机构"}]
    agent._artifacts = MagicMock()
    agent._artifacts.list_for_session.return_value = [
        {"status": "completed", "ledger": []},  # empty ledger ignored
        {
            "status": "completed",
            "ledger": [
                {"step": 2, "kind": "term", "text": "PDOT：分子内份额"},
                {"step": 0, "kind": "scope", "text": "只查重点民营机构"},  # duplicate
                {"step": 3, "kind": "time", "text": "外部市场数据最新月=2026-06"},
            ],
        },
        {"status": "running", "ledger": [{"step": 1, "kind": "term", "text": "不应被继承"}]},
    ]

    agent._inherit_ledger(session_id="session-1", excluding_run_id="run-2")

    texts = [entry["text"] for entry in agent._ledger]
    assert texts == [
        "只查重点民营机构",
        "外部市场数据最新月=2026-06",
    ]
    assert "PDOT：分子内份额" not in texts


def test_inherit_ledger_noop_without_completed_turns() -> None:
    agent = _build_agent()
    agent._run_id = "run-2"
    agent._artifacts = MagicMock()
    agent._artifacts.list_for_session.return_value = [
        {"status": "suspended", "ledger": [{"step": 1, "kind": "term", "text": "x"}]},
    ]
    agent._inherit_ledger(session_id="session-1", excluding_run_id="run-2")
    assert agent._ledger == []


def test_remove_ledger_entry_drops_by_key_and_emits() -> None:
    agent = _build_agent()
    agent._run_id = "run-1"
    agent._ledger = [
        {"step": 1, "kind": "term", "text": "茁乐：Tezspire", "key": "茁乐"},
        {"step": 1, "kind": "term", "text": "渠道：取值开放", "key": "渠道"},
    ]
    agent._remove_ledger_entry("茁乐")
    assert [entry["key"] for entry in agent._ledger] == ["渠道"]
    ledger_events = [
        call
        for call in agent._runs.append_event.call_args_list
        if call.kwargs.get("event_type") == "agent.ledger.updated"
    ]
    assert len(ledger_events) == 1
    # Removing a missing key is a no-op.
    agent._remove_ledger_entry("不存在")
    assert len(agent._runs.append_event.call_args_list) == 1


def test_update_ledger_tool_delete_action() -> None:
    spec = build_update_ledger_tool()
    context = MagicMock()
    removed = asyncio.run(spec.executor(context, {"action": "delete", "key": "茁乐"}))
    assert removed.ok and removed.payload == {"delete_key": "茁乐"}

    missing_key = asyncio.run(spec.executor(context, {"action": "delete"}))
    assert not missing_key.ok


def test_updating_constraint_scope_invalidates_facts_and_hops() -> None:
    agent = _build_agent()
    agent._run_id = "run-1"
    agent._facts = ["查询成功，共 1 行"]
    agent._hops = [{"sql": "SELECT 1", "columns": ["x"], "rows": [[1]], "row_count": 1}]
    agent._upsert_ledger_entry(
        step=1,
        entry={"key": "BU", "kind": "scope", "text": "BU=组织维度"},
    )
    agent._upsert_ledger_entry(
        step=2,
        entry={"key": "BU", "kind": "scope", "text": "BU=渠道维度"},
    )
    assert agent._facts == []
    assert agent._hops == []
    keyed = [entry for entry in agent._ledger if entry.get("key") == "BU"]
    assert keyed[0]["text"] == "BU=渠道维度"


def test_clarify_key_is_stable() -> None:
    assert _clarify_key("增速口径？") == _clarify_key("  增速口径？  ")
    assert _clarify_key("增速口径？").startswith("clarify:")


def test_memory_conclusion_handles_legacy_single_line_format() -> None:
    legacy = "原始问题:耐信销量 澄清问题:哪一年? 用户结论:2024年H2 Actual （系统自动记录）"
    assert _memory_conclusion(legacy) == "2024年H2 Actual"


# ------------------------------------------------------- multi-question case


def _two_question_case() -> ClarificationCase:
    questions = (
        ClarificationQuestion(
            question_id="question-window",
            prompt="查询时间窗口？",
            reason=ClarificationReason.CRITICAL_SLOT_AMBIGUITY,
            choices=(
                ClarificationChoice(choice_id="choice-ytd", label="YTD"),
                ClarificationChoice(choice_id="choice-h1", label="H1"),
            ),
        ),
        ClarificationQuestion(
            question_id="question-metric",
            prompt="统计口径？",
            reason=ClarificationReason.CRITICAL_SLOT_AMBIGUITY,
            choices=(
                ClarificationChoice(choice_id="choice-amount", label="金额"),
                ClarificationChoice(choice_id="choice-box", label="盒数"),
            ),
        ),
    )
    return ClarificationCase.open(
        case_id="case-1",
        run_id="run-1",
        session_id="session-1",
        frame_id="run-1",
        questions=questions,
        created_at=datetime.now(timezone.utc),
    )


def test_answer_case_records_each_question() -> None:
    store = _CaseStore()
    agent = _build_agent(store=store)
    case = _two_question_case()
    store.save(case)

    pairs = agent._answer_case(
        case,
        "问：查询时间窗口？\n答：YTD\n问：统计口径？\n答：金额",
        {"question-window": "YTD", "question-metric": "金额"},
    )

    saved = store.get("case-1")
    assert saved.status is ClarificationStatus.ANSWERED
    assert [answer.question_id for answer in saved.answers] == [
        "question-window",
        "question-metric",
    ]
    assert saved.answers[0].choice_id == "choice-ytd"
    assert pairs == [("查询时间窗口？", "YTD"), ("统计口径？", "金额")]


def test_answer_case_keeps_legacy_single_answer_behaviour() -> None:
    store = _CaseStore()
    agent = _build_agent(store=store)
    case = _two_question_case()
    store.save(case)

    pairs = agent._answer_case(case, "YTD", None)

    saved = store.get("case-1")
    assert len(saved.answers) == 1
    assert saved.answers[0].question_id == "question-window"
    assert pairs == [("查询时间窗口？", "YTD")]
