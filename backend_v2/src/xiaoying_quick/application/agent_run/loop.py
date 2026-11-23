"""The agent loop: one model, its tools, and an append-only event trail.

Everything the model ever sees is reconstructed from durable state — the
session history replays from committed transcripts, a crashed run continues
from its last checkpoint, and a clarification resume injects the user's answer
as the tool result it always was. Events are the projection for humans; the
transcript artifact is the projection for the model.

There are deliberately no step or token budgets: the loop runs until the model
stops calling tools, the user cancels, or something fails loudly.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any

from xiaoying_quick.application.agent_run.loop_budget import AgentLoopBudget
from xiaoying_quick.application.agent_run.sql_review import (
    SQL_REVIEW_SYSTEM,
    build_sql_review_user_prompt,
    format_sql_review_notice,
    interpret_sql_review,
)
from xiaoying_quick.application.agent_run.tools import snapshot_query_table
from xiaoying_quick.infrastructure.llm import (
    ChatCompletionClient,
    ChatTurn,
    ContentDelta,
    ReasoningDelta,
    ToolCallFragment,
    TurnComplete,
)
from xiaoying_quick.infrastructure.llm.context_window import TRIGGER, ContextReading, prepare_context
from xiaoying_quick.infrastructure.llm.registry import ModelRegistry
from xiaoying_quick.modules.agent import (
    MAIN_SYSTEM_PROMPT,
    AgentEventType,
    AgentToolContext,
    ToolCallResult,
    ToolRegistry,
)
from xiaoying_quick.modules.chat.contracts import ChatSession
from xiaoying_quick.modules.chat.service import ChatService
from xiaoying_quick.modules.clarification import (
    ClarificationAnswer,
    ClarificationCase,
    ClarificationChoice,
    ClarificationQuestion,
    ClarificationReason,
    ClarificationStatus,
)
from xiaoying_quick.modules.clarification.ports import ClarificationCaseRepository
from xiaoying_quick.modules.context import RecallLevel, RecallRequest, RecallSourceType
from xiaoying_quick.modules.identity import AuthenticatedPrincipal
from xiaoying_quick.modules.knowledge.contracts import MemoryWriteRequest
from xiaoying_quick.modules.runs import RunStatus
from xiaoying_quick.modules.runs.service import RunService
from xiaoying_quick.modules.usage import UsageAttribution, bind_usage_attribution
from xiaoying_quick.shared.errors import InvalidTransition
from xiaoying_quick.shared.ids import new_id

_LOGGER = logging.getLogger(__name__)

#: Run events are capped at 64 KiB by the runs service; the agent loop must
#: keep projecting events even when a tool output or an answer outgrows it.
_EVENT_PAYLOAD_BYTES = 64 * 1024
_TRUNCATION_MARKER = "\n…（内容过长已截断）"


#: Identical tool calls are allowed a couple of honest retries; beyond this
#: the loop refuses to re-run them so a stuck model cannot spin forever.
_REPEAT_BLOCK_AT = 4

AGENT_PROMPT_VERSION = "agent-v17"
TRANSCRIPT_KIND = "agent_transcript"
TOOL_RESULT_KIND = "tool_result"

#: Deltas are flushed to the event stream in readable chunks rather than one
#: row per provider fragment.
_DELTA_FLUSH_CHARS = 120
#: Events are capped at 64 KiB by the run service; keep reasoning below it.
_EVENT_REASONING_CHARS = 48_000

#: The progress ledger is the caliber card of the current question: parsed
#: slots (product/KPI/time) plus confirmed scopes. Raw query facts stay in a
#: private anchor list — they pin the model without cluttering the card.
_LEDGER_MAX_ENTRIES = 20
_LEDGER_ENTRY_CHARS = 200
_FACT_MAX_ENTRIES = 12
#: Scopes and time facts survive into the next turn; process notes do not.
_DURABLE_LEDGER_KINDS = frozenset({"scope", "time"})
#: Updating these kinds means the previous query no longer matches the caliber.
_CONSTRAINT_LEDGER_KINDS = frozenset({"scope", "time", "qualifier"})
_HOP_MAX_ENTRIES = 3
_HOP_MAX_ROWS = 80
#: Full query grids kept for export_xlsx; larger than hops so a later 1-row
#: probe does not drop the 462-row answer set.
_QUERY_TABLE_MAX = 12
#: Priming admits at most this many memory hits / clarification conclusions.
_PRIMED_MEMORY_LIMIT = 6
_PRIMED_CLARIFY_LIMIT = 6

#: Time-window tokens recognised in the question text for the caliber card.
_TIME_TOKEN_PATTERN = re.compile(
    r"YTD\s*\d{0,4}|QTD|MTD|H[12]|Q[1-4]|\d{4}\s*年"
    r"|今年|去年|前年|全年|上半年|下半年|本月|上月|当月|同比|环比",
    re.IGNORECASE,
)

AGENT_SYSTEM_PROMPT = MAIN_SYSTEM_PROMPT


class AgentSuspended(Exception):
    """Control-flow: the loop paused for a user clarification."""


class AgentModelUnavailable(RuntimeError):
    """No active model configuration — fail the run loudly."""


class AgentCancelled(RuntimeError):
    """The run was cancelled by the user; exit workers without failing loudly."""


class AgentRunService:
    """Executes one durable agent turn against the run's own transaction."""

    def __init__(
        self,
        *,
        runs: RunService,
        chats: ChatService,
        artifacts: Any,
        clarifications: ClarificationCaseRepository,
        model_registry: ModelRegistry,
        tools: ToolRegistry,
        lab_ids: tuple[str, ...],
        tool_dependencies: Mapping[str, Any],
        checkpoint: Callable[[], None],
        loop_budget: AgentLoopBudget | None = None,
    ) -> None:
        self._runs = runs
        self._chats = chats
        self._artifacts = artifacts
        self._clarifications = clarifications
        self._model_registry = model_registry
        self._tools = tools
        self._lab_ids = lab_ids
        self._tool_dependencies = tool_dependencies
        self._checkpoint = checkpoint
        #: Optional explicit execution caps; both chat modes default to unlimited.
        self._loop_budget = loop_budget
        self._budget_counts: dict[str, int] = {}
        self._call_repeats: dict[str, int] = {}
        #: Per-run model selection and thinking overrides (from the composer).
        self._model_config_id: str | None = None
        self._thinking: str | None = None
        self._thinking_level: str | None = None
        #: Eval runs turn this off so personal memory is never primed, recalled
        #: or written. Default True keeps the ordinary chat path unchanged.
        self._use_memory = True
        #: Progress ledger of the current turn: caliber slots of the current
        #: question plus confirmed scopes; seeded by priming in start() or
        #: restored from the checkpoint on resume/continue.
        self._ledger: list[dict[str, Any]] = []
        #: Successful query_db summaries; anchor the model but stay off the card.
        self._facts: list[str] = []
        #: Verified query_db hops this turn, for ask_lab attach_upstream.
        self._hops: list[dict[str, Any]] = []
        #: Full query_db grids (not clipped) so export_xlsx can write every row.
        self._query_tables: list[dict[str, Any]] = []
        self._last_lab_question = ""
        self._run_id = ""
        self._report_attempted = False
        self._working_messages: list[ChatTurn] | None = None
        self._context_run_ids: list[str] = []

    # ------------------------------------------------------------------ turns

    def _is_cancelled(self, run_id: str) -> bool:
        checker = getattr(self._runs, "is_cancelled", None)
        return bool(callable(checker) and checker(run_id))

    def _ensure_not_cancelled(self, run_id: str) -> None:
        if self._is_cancelled(run_id):
            raise AgentCancelled()

    def _repeat_block_at(self) -> int:
        if self._loop_budget is not None and self._loop_budget.repeat_block_at is not None:
            return max(1, int(self._loop_budget.repeat_block_at))
        return _REPEAT_BLOCK_AT

    def _budget_force_finish(self, step: int) -> bool:
        budget = self._loop_budget
        return bool(budget and budget.max_steps is not None and step >= budget.max_steps)

    def _forced_budget_answer(self, assistant_content: str) -> str:
        text = str(assistant_content or "").strip()
        if text:
            return text
        facts = [str(item).strip() for item in self._facts if str(item).strip()]
        if facts:
            lines = [
                "（执行步数预算已用尽，基于已取数事实作答）",
                *[f"- {item}" for item in facts[-6:]],
            ]
            return "\n".join(lines)
        return "（执行步数预算已用尽，当前尚无足够取数结果。）"

    async def _publish_suggestions_after_answer(
        self,
        *,
        run_id: str,
        client: ChatCompletionClient,
        question: str,
        answer: str,
    ) -> None:
        """Post-loop only: suggest from the finished answer +取数, never in parallel."""

        if self._loop_budget is not None and self._loop_budget.skip_suggest:
            return
        if self._is_cancelled(run_id):
            return
        try:
            from xiaoying_quick.application.suggest import build_suggestions

            payload = await build_suggestions(
                client=client,
                question=question,
                answer=answer,
                facts=self._facts,
                query_tables=self._query_tables,
                is_cancelled=lambda: self._is_cancelled(run_id),
            )
        except Exception:  # noqa: BLE001 — suggest must not fail a completed run
            _LOGGER.warning("suggest post-step raised", exc_info=True)
            return
        if self._is_cancelled(run_id) or not isinstance(payload, dict):
            return
        questions = payload.get("questions")
        if not isinstance(questions, list) or len(questions) != 3:
            return
        try:
            body: dict[str, Any] = {"questions": questions}
            category = payload.get("category")
            if category:
                body["category"] = category
            self._emit(run_id, AgentEventType.SUGGEST_READY, body)
        except Exception:  # noqa: BLE001 — silent
            _LOGGER.warning("suggest.ready emit failed", exc_info=True)

    def _build_client(self):
        """Client for this run: composer model pick + thinking overrides.

        Falls back to ``active_client`` so registries without run-level
        selection (older wiring, test fakes) keep working.
        """

        factory = getattr(self._model_registry, "client", None)
        if callable(factory):
            return factory(
                self._model_config_id,
                thinking=self._thinking,
                thinking_level=self._thinking_level,
            )
        return self._model_registry.active_client()

    async def start(
        self,
        *,
        principal: AuthenticatedPrincipal,
        run_id: str,
        session: ChatSession,
        question: str,
        model_config_id: str | None = None,
        thinking: str | None = None,
        thinking_level: str | None = None,
        use_memory: bool | None = None,
    ) -> None:
        self._model_config_id = model_config_id
        self._thinking = thinking
        self._thinking_level = thinking_level
        checkpoint = self._artifacts.latest(run_id=run_id, kind=TRANSCRIPT_KIND)
        self._use_memory = _resolve_use_memory(use_memory, checkpoint)
        self._run_id = run_id
        usage_attr = self._usage_attribution(
            principal=principal, run_id=run_id, session_id=session.id
        )
        with bind_usage_attribution(usage_attr):
            if checkpoint is not None:
                # A previous attempt crashed mid-turn: continue from where it got.
                try:
                    await self._continue_from_checkpoint(
                        actor_id=principal.user_id,
                        run_id=run_id,
                        session=session,
                        checkpoint=checkpoint,
                    )
                except AgentCancelled:
                    return
                return

            try:
                self._runs.transition(run_id=run_id, target=RunStatus.RUNNING)
            except InvalidTransition:
                # A retry found the run already running (crashed after the
                # transition committed but before the first checkpoint).
                pass
            self._emit(run_id, AgentEventType.TURN_START, {"question": question})

            self._ledger = []
            self._facts = []
            self._hops = []
            self._query_tables = []
            self._last_lab_question = ""
            self._prime_context(
                actor_id=principal.user_id,
                run_id=run_id,
                session_id=session.id,
                question=question,
            )
            self._inherit_ledger(session_id=session.id, excluding_run_id=run_id)
            history = self._replay_history(session_id=session.id, excluding_run_id=run_id)
            turn_messages: list[dict[str, Any]] = [
                _serialize_turn(ChatTurn(role="user", content=question))
            ]
            messages = [
                ChatTurn(role="system", content=self._system_prompt()),
                *history,
                ChatTurn(role="user", content=question),
            ]
            try:
                await self._loop(
                    actor_id=principal.user_id,
                    run_id=run_id,
                    session=session,
                    messages=messages,
                    turn_messages=turn_messages,
                    step=0,
                    anchor_question=question,
                )
            except AgentCancelled:
                return
            except AgentSuspended:
                return

    def _usage_attribution(
        self,
        *,
        principal: AuthenticatedPrincipal,
        run_id: str,
        session_id: str,
    ) -> UsageAttribution:
        mode = "normal"
        question = ""
        # Insight children share the parent run_id so Token 消耗 shows one row
        # per user question, not one row per sub-problem.
        attr_run_id = run_id
        try:
            record = self._runs.get_run(principal=principal, run_id=run_id)
            raw_mode = getattr(record, "mode", None)
            mode = str(getattr(raw_mode, "value", raw_mode) or "normal")
            question = str(record.question or "").strip()
            parent_id = getattr(record, "parent_run_id", None)
            if parent_id:
                attr_run_id = str(parent_id)
                try:
                    parent = self._runs.get_run(principal=principal, run_id=str(parent_id))
                    if str(parent.question or "").strip():
                        question = str(parent.question).strip()
                    raw_parent_mode = getattr(parent, "mode", None)
                    parent_mode = str(getattr(raw_parent_mode, "value", raw_parent_mode) or "")
                    if parent_mode:
                        mode = parent_mode
                    if parent.session_id:
                        session_id = str(parent.session_id)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass
        return UsageAttribution(
            user_id=principal.user_id,
            username=principal.username,
            display_name=principal.display_name,
            run_id=attr_run_id,
            session_id=session_id,
            mode=mode,
            question=question,
        )

    async def resume(
        self,
        *,
        principal: AuthenticatedPrincipal,
        run_id: str,
        session: ChatSession,
        answer: str,
        answers: Mapping[str, str] | None = None,
        model_config_id: str | None = None,
        thinking: str | None = None,
        thinking_level: str | None = None,
        use_memory: bool | None = None,
    ) -> None:
        self._model_config_id = model_config_id
        self._thinking = thinking
        self._thinking_level = thinking_level
        checkpoint = self._artifacts.latest(run_id=run_id, kind=TRANSCRIPT_KIND)
        if checkpoint is None:
            raise AgentModelUnavailable("agent checkpoint with pending clarification is missing")
        self._use_memory = _resolve_use_memory(use_memory, checkpoint)
        self._run_id = run_id
        usage_attr = self._usage_attribution(
            principal=principal, run_id=run_id, session_id=session.id
        )
        with bind_usage_attribution(usage_attr):
            self._ledger = _load_ledger(checkpoint.get("ledger"))
            self._facts = _load_facts(checkpoint.get("facts"))
            self._hops = _load_hops(checkpoint.get("hops"))
            self._last_lab_question = str(checkpoint.get("last_lab_question") or "")
            self._restore_query_tables(run_id)
            resume_question = _run_question_from_checkpoint(checkpoint)
            if not checkpoint.get("pending"):
                # A previous resume attempt already consumed the answer and may
                # have crashed mid-loop; continue from where it got to.
                try:
                    await self._continue_from_checkpoint(
                        actor_id=principal.user_id,
                        run_id=run_id,
                        session=session,
                        checkpoint=checkpoint,
                    )
                except AgentCancelled:
                    return
                return
            try:
                self._runs.transition(run_id=run_id, target=RunStatus.RUNNING)
            except InvalidTransition:
                pass

            pending = dict(checkpoint["pending"])
            case_id = str(pending.get("case_id") or "")
            case = self._clarifications.get(case_id) if case_id else None
            if case is not None and case.status.value == "waiting":
                answered = self._answer_case(case, answer, answers)
                for prompt, reply in answered:
                    self._add_ledger(
                        step=int(checkpoint.get("step", 0)),
                        kind="scope",
                        text=f"用户确认：{prompt} → {reply}",
                        key=_clarify_key(prompt),
                    )
                self._remember_clarification(
                    actor_id=principal.user_id,
                    run_id=run_id,
                    case=case,
                    answer=answer,
                    checkpoint=checkpoint,
                    answered=answered,
                )
            self._emit(
                run_id,
                AgentEventType.ASK_USER_ANSWERED,
                {"case_id": case_id, "answer": answer[:2_000]},
            )

            # Replace the provisional ask_user tool reply with the answer. Two
            # replies for the same call ID are rejected by OpenAI-compatible APIs.
            turn_messages: list[dict[str, Any]] = [
                record
                for record in checkpoint.get("turn_messages", [])
                if not (
                    record.get("role") == "tool"
                    and record.get("tool_call_id") == str(pending["call_id"])
                )
            ]
            history_turns = self._restore_model_view(session.id, run_id, checkpoint, turn_messages)
            history_turns = [turn for turn in history_turns if not (
                turn.role == "tool" and turn.tool_call_id == str(pending["call_id"])
            )]
            tool_message = ChatTurn(
                role="tool",
                content=f"用户的回答：{answer.strip()[:2_000]}",
                tool_call_id=str(pending["call_id"]),
            )
            history_turns.append(tool_message)
            turn_messages.append(_serialize_turn(tool_message))
            # Any tool calls queued after ask_user were dropped by the suspension;
            # each still needs a tool message to keep the protocol consistent.
            for call in _pending_calls_after(checkpoint, str(pending["call_id"])):
                skipped = ChatTurn(
                    role="tool",
                    content="（该调用因等待用户澄清而未执行，如需请重新发起。）",
                    tool_call_id=call.id,
                )
                history_turns.append(skipped)
                turn_messages.append(_serialize_turn(skipped))

            messages = [
                ChatTurn(role="system", content=self._system_prompt()),
                *history_turns,
            ]
            try:
                await self._loop(
                    actor_id=principal.user_id,
                    run_id=run_id,
                    session=session,
                    messages=messages,
                    turn_messages=turn_messages,
                    step=int(checkpoint.get("step", 0)),
                    anchor_question=resume_question,
                )
            except AgentCancelled:
                return
            except AgentSuspended:
                return

    # ------------------------------------------------------------------- loop

    async def _loop(
        self,
        *,
        actor_id: str,
        run_id: str,
        session: ChatSession,
        messages: list[ChatTurn],
        turn_messages: list[dict[str, Any]],
        step: int,
        anchor_question: str = "",
    ) -> None:
        try:
            client = self._build_client()
        except ValueError:
            self._fail(
                run_id,
                "MODEL_CONFIG_INVALID",
                "模型配置无效，请在模型管理页检查接口地址和参数，并执行连接测试。",
            )
            return
        if client is None:
            self._fail(
                run_id,
                "NO_ACTIVE_MODEL",
                "没有激活的模型配置，请先在模型管理页激活一个模型",
            )
            raise AgentModelUnavailable("no active model configuration")
        self._working_messages = messages
        report_repairs = 0
        sql_answer_repairs = 0
        try:
            while True:
                self._ensure_not_cancelled(run_id)
                step += 1
                # Re-anchor every step: the ledger keeps the original question,
                # confirmed scopes and established facts in the model's face so
                # a long trail of tool outputs cannot drift the run away.
                messages[0] = ChatTurn(
                    role="system",
                    content=self._system_prompt()
                    + _anchor_block(anchor_question, self._ledger, self._facts),
                )
                self._emit(run_id, AgentEventType.STEP_START, {"step": step})
                assistant = await self._stream_one_step(
                    run_id=run_id, step=step, client=client, messages=messages
                )
                self._ensure_not_cancelled(run_id)
                if self._tool_dependencies.get("lab_provider") == "gilead" and assistant.content:
                    from xiaoying_quick.infrastructure.lab_http.atomic_sql import render_sql_answer

                    try:
                        content = render_sql_answer(assistant.content, self._artifacts, run_id)
                    except ValueError as exc:
                        if not assistant.tool_calls and sql_answer_repairs < 2:
                            sql_answer_repairs += 1
                            messages.append(ChatTurn(role="system", content=str(exc)))
                            continue
                        content = "" if assistant.tool_calls else "本轮未能确认可展示的 SQL。"
                    assistant = replace(assistant, content=content)
                    if content:
                        self._emit(run_id, AgentEventType.CONTENT_DELTA, {"step": step, "text": content})
                self._emit(
                    run_id,
                    AgentEventType.ASSISTANT_MESSAGE,
                    {
                        "step": step,
                        "content": assistant.content,
                        "reasoning": assistant.reasoning[:_EVENT_REASONING_CHARS],
                        "reasoning_truncated": len(assistant.reasoning) > _EVENT_REASONING_CHARS,
                        "finish_reason": assistant.finish_reason,
                        "usage": dict(assistant.usage),
                        "tool_calls": [
                            {"call_id": call.id, "name": call.name} for call in assistant.tool_calls
                        ],
                    },
                )
                assistant_record = _serialize_turn(
                    ChatTurn(
                        role="assistant",
                        content=assistant.content,
                        reasoning=assistant.reasoning,
                        tool_calls=assistant.tool_calls,
                    )
                )
                turn_messages.append(assistant_record)
                messages.append(
                    ChatTurn(
                        role="assistant",
                        content=assistant.content,
                        reasoning=assistant.reasoning,
                        tool_calls=assistant.tool_calls,
                    )
                )
                if isinstance(client, ChatCompletionClient):
                    self._context_after_reply(run_id, step, client, messages, assistant.usage)
                self._save_checkpoint(run_id, step, turn_messages, pending=None)

                if not assistant.tool_calls or self._budget_force_finish(step):
                    report_context = self._tool_dependencies.get("report_context") or {}
                    report_edit = report_context.get("intent") == "revise_report" or (
                        report_context.get("report_id") and self._report_attempted
                    )
                    if (
                        report_edit
                        and self._artifacts.latest(run_id=run_id, kind="bi_report") is None
                    ):
                        if report_repairs >= 2:
                            self._fail(
                                run_id,
                                "REPORT_REVISION_NOT_SAVED",
                                "报告修改尚未保存成功，原报告已保留。请根据字段提示重试。",
                            )
                            return
                        report_repairs += 1
                        repair = ChatTurn(
                            role="user",
                            content=(
                                "报告修改尚未保存：本轮没有成功生成报告产物，不能声称已更新或当前已满足。"
                                "请依据工具返回的missing_fields补查缺少的真实字段，保留原筛选维度与指标，"
                                "然后成功调用render_report保存修订，再给出完成说明。"
                            ),
                        )
                        messages.append(repair)
                        turn_messages.append(_serialize_turn(repair))
                        continue
                    # Charts → suggestions → complete. Suggest must emit before
                    # the run flips terminal, or SSE closes and the client never
                    # sees suggest.ready. Still post-answer only (not parallel).
                    answer = (
                        self._forced_budget_answer(assistant.content)
                        if assistant.tool_calls and self._budget_force_finish(step)
                        else assistant.content
                    )
                    self._ensure_not_cancelled(run_id)
                    await self._emit_charts_if_any(
                        run_id=run_id,
                        client=client,
                        question=anchor_question,
                        answer=answer,
                    )
                    self._ensure_not_cancelled(run_id)
                    await self._publish_suggestions_after_answer(
                        run_id=run_id,
                        client=client,
                        question=anchor_question,
                        answer=answer,
                    )
                    self._ensure_not_cancelled(run_id)
                    self._complete(run_id, session, answer=answer, turn_messages=turn_messages)
                    return

                for call in assistant.tool_calls:
                    self._ensure_not_cancelled(run_id)
                    suspended = await self._execute_call(
                        actor_id=actor_id,
                        run_id=run_id,
                        session=session,
                        step=step,
                        call=call,
                        messages=messages,
                        turn_messages=turn_messages,
                        anchor_question=anchor_question,
                        client=client,
                    )
                    if suspended:
                        raise AgentSuspended()
        except Exception as exc:
            from xiaoying_quick.infrastructure.monthly_quota import QuotaUnavailable
            if not isinstance(exc, QuotaUnavailable):
                raise
            self._fail(run_id, "MONTHLY_QUOTA_EXCEEDED", str(exc))
        finally:
            await client.aclose()

    def _context_event(self, run_id, step, phase, reading, messages, prepared):
        if reading.compacted:
            messages[:] = [_turn_from_record(record) for record in prepared]
        kind = AgentEventType.CONTEXT_COMPACTED if reading.compacted else AgentEventType.CONTEXT_UPDATED
        self._emit(run_id, kind, {"step": step, "phase": phase, **reading.payload()})

    def _context_after_reply(self, run_id, step, client, messages, usage):
        measured = int(usage.get("prompt_tokens") or 0)
        used = measured + int(usage.get("completion_tokens") or 0)
        if measured and used < TRIGGER:
            reading = ContextReading(used, used, False, "provider")
            self._context_event(run_id, step, "reply", reading, messages, ())
            return
        body = client.context_body(messages, self._tools.schemas())
        reading = prepare_context(body, observed_tokens=used)
        if measured and not reading.compacted:
            reading = ContextReading(used, used, False, "provider")
        self._context_event(run_id, step, "reply", reading, messages, body["messages"])

    async def _stream_one_step(
        self,
        *,
        run_id: str,
        step: int,
        client: ChatCompletionClient,
        messages: list[ChatTurn],
    ):
        think_buffer: list[str] = []
        content_buffer: list[str] = []
        completed: TurnComplete | None = None

        def flush(kind: AgentEventType, buffer: list[str]) -> None:
            text = "".join(buffer)
            buffer.clear()
            if text:
                self._emit(run_id, kind, {"step": step, "text": text})

        current = None
        pending_text = []
        pending_chars = 0

        def on_context(reading, prepared):
            nonlocal current
            current = reading
            self._context_event(run_id, step, "input", reading, messages, prepared)

        options = {"on_context": on_context} if isinstance(client, ChatCompletionClient) else {}
        async for event in client.stream_chat(
            purpose=f"agent.step{step}", messages=messages, tools=self._tools.schemas(), **options
        ):
            if current and isinstance(event, (ContentDelta, ReasoningDelta)):
                pending_text.append(event.text)
                pending_chars += len(event.text)
                if pending_chars >= 512:
                    used = current.used + client.output_size("".join(pending_text))
                    current = ContextReading(used, used, False, current.source)
                    self._context_event(run_id, step, "generating", current, messages, ())
                    pending_text.clear()
                    pending_chars = 0
            if isinstance(event, ReasoningDelta):
                think_buffer.append(event.text)
                if sum(len(part) for part in think_buffer) >= _DELTA_FLUSH_CHARS:
                    flush(AgentEventType.THINK_DELTA, think_buffer)
            elif isinstance(event, ContentDelta):
                # The paired SQL lab expands verified SQL references before publishing.
                if self._tool_dependencies.get("lab_provider") != "gilead":
                    content_buffer.append(event.text)
                    if sum(len(part) for part in content_buffer) >= _DELTA_FLUSH_CHARS:
                        flush(AgentEventType.CONTENT_DELTA, content_buffer)
            elif isinstance(event, TurnComplete):
                completed = event
        flush(AgentEventType.THINK_DELTA, think_buffer)
        flush(AgentEventType.CONTENT_DELTA, content_buffer)
        if completed is None:
            raise RuntimeError("model stream ended without a completion")
        return completed.turn

    async def _execute_call(
        self,
        *,
        actor_id: str,
        run_id: str,
        session: ChatSession,
        step: int,
        call: ToolCallFragment,
        messages: list[ChatTurn],
        turn_messages: list[dict[str, Any]],
        anchor_question: str = "",
        client: ChatCompletionClient | None = None,
    ) -> bool:
        arguments = self._tools.parse_arguments(call.arguments)
        if call.name == "render_report":
            self._report_attempted = True
        call_payload: dict[str, Any] = {
            "call_id": call.id,
            "name": call.name,
            "step": step,
            "arguments": arguments,
        }
        if call.name.startswith("agent_"):
            call_payload["kind"] = "agent"
        self._emit(run_id, AgentEventType.TOOL_CALL, call_payload)
        repeats = self._count_repeat(call.name, arguments)
        review: dict[str, Any] | None = None
        repeat_at = self._repeat_block_at()
        budget_deny = (
            self._loop_budget.deny(call.name, self._budget_counts)
            if self._loop_budget is not None
            else None
        )
        if budget_deny:
            result = ToolCallResult(ok=False, output=budget_deny)
        elif repeats >= repeat_at:
            result = ToolCallResult(
                ok=False,
                output=(
                    f"完全相同的 {call.name} 调用已经重复 {repeats} 次，再执行不会产生任何新信息。"
                    "请停止重复：更换参数或工具，或直接基于已掌握的信息回答用户。"
                ),
            )
        else:
            if self._loop_budget is not None:
                self._loop_budget.record(call.name, self._budget_counts)
            extras = dict(self._tool_dependencies)
            extras["upstream_hops"] = self._hops
            extras["query_tables"] = self._query_tables
            extras["use_memory"] = self._use_memory
            if client is not None:
                extras["llm_client"] = client
            context = AgentToolContext(
                run_id=run_id,
                session_id=session.id,
                actor_id=actor_id,
                emit=lambda event_type, payload: self._emit(run_id, event_type, payload),
                extras=extras,
                active_scopes=self._active_scopes(),
                call_id=call.id,
            )
            sql = str(arguments.get("sql") or "").strip()
            allow_review = not (self._loop_budget is not None and self._loop_budget.skip_sql_review)
            review_task = (
                asyncio.create_task(
                    self._review_sql_coverage(client=client, sql=sql, question=anchor_question)
                )
                if call.name == "query_db" and sql and allow_review and self._tool_dependencies.get("lab_provider") != "gilead"
                else None
            )
            result = await self._tools.execute(name=call.name, context=context, arguments=arguments)
            if review_task is not None:
                try:
                    review = await review_task
                except Exception:  # noqa: BLE001 — review must not fail the query
                    _LOGGER.warning("sql coverage review failed", exc_info=True)
                    review = interpret_sql_review(None)
            if review is not None:
                notice = format_sql_review_notice(review)
                payload = dict(result.payload)
                payload["sql_review"] = review
                result = ToolCallResult(
                    ok=result.ok,
                    output=result.output + notice,
                    payload=payload,
                    suspended=result.suspended,
                )
            if repeats == repeat_at - 1 and not result.suspended:
                result = ToolCallResult(
                    ok=result.ok,
                    output=result.output + f"\n注意：相同参数的调用已重复 {repeat_at - 1} 次，"
                    "再重复将被拒绝执行，请尽快调整策略。",
                    payload=result.payload,
                )

        if (
            call.name == "query_db" and result.ok
            and (review is None or bool(review.get("ok")))
            and self._tool_dependencies.get("lab_provider") not in ("gilead","xlsx")
        ):
            index = min(len(self._query_tables), _QUERY_TABLE_MAX - 1)
            result = ToolCallResult(
                ok=result.ok,
                payload=result.payload,
                suspended=result.suspended,
                output=result.output
                + f"\n本份已核验结果的报告query_index={index}（从0起算，最近12份有效）。"
                + "生成趋势报告必须在同一查询保留月份与所需筛选维度。",
            )
        full_payload = dict(result.payload)
        artifact_id = self._artifacts.append(
            run_id=run_id,
            kind=TOOL_RESULT_KIND,
            atom_id=call.id,
            payload={"name": call.name, "ok": result.ok, "payload": full_payload},
        )
        if (
            call.name == "query_db" and result.ok
            and (review is None or bool(review.get("ok")))
            and self._tool_dependencies.get("lab_provider") == "xlsx"
        ):
            result = ToolCallResult(
                ok=result.ok, payload=result.payload, suspended=result.suspended,
                output=result.output + f"\n本份已核验结果的固定 query_ref={artifact_id}。"
                "生成图表时原样引用此编号，下钻查询不会改变它。",
            )
        self._emit(
            run_id,
            AgentEventType.TOOL_RESULT,
            {
                "call_id": call.id,
                "name": call.name,
                "step": step,
                "ok": result.ok,
                "output": result.output,
                "preview": _event_preview(full_payload),
            },
        )
        tool_message = ChatTurn(role="tool", content=result.output, tool_call_id=call.id)
        messages.append(tool_message)
        turn_messages.append(_serialize_turn(tool_message))
        if call.name == "ask_lab":
            self._last_lab_question = str(arguments.get("question") or "")[:500]
        if call.name == "query_db" and result.ok:
            trusted = review is None or bool(review.get("ok"))
            if trusted:
                self._add_fact(_fact_text(call.arguments, full_payload))
                self._record_hop(arguments, full_payload)
                self._record_query_table(full_payload)
        if call.name == "update_ledger" and result.ok:
            delete_key = full_payload.get("delete_key")
            if isinstance(delete_key, str) and delete_key:
                self._remove_ledger_entry(delete_key)
            else:
                entry = full_payload.get("entry")
                if isinstance(entry, Mapping):
                    self._upsert_ledger_entry(step=step, entry=entry)

        if result.suspended:
            groups = list(full_payload.get("groups", []))
            case = self._open_case(run_id=run_id, session=session, groups=groups)
            self._emit(
                run_id,
                AgentEventType.ASK_USER_OPENED,
                {
                    "call_id": call.id,
                    "case_id": case.case_id,
                    # Tools hand in free-form groups; the case carries the
                    # canonical ids the UI needs to submit answers back.
                    "groups": _card_groups(case),
                },
            )
            self._save_checkpoint(
                run_id,
                step,
                turn_messages,
                pending={"call_id": call.id, "name": call.name, "case_id": case.case_id},
            )
            self._runs.transition(run_id=run_id, target=RunStatus.WAITING_CLARIFICATION)
            return True
        self._save_checkpoint(run_id, step, turn_messages, pending=None)
        return False

    def _count_repeat(self, name: str, arguments: Mapping[str, Any]) -> int:
        key = f"{name}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)}"
        repeats = self._call_repeats.get(key, 0) + 1
        self._call_repeats[key] = repeats
        return repeats

    def _record_hop(self, arguments: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
        """Keep the last verified query_db result for attach_upstream."""

        sql = str(payload.get("sql") or arguments.get("sql") or "").strip()
        if not sql:
            return
        raw_rows = payload.get("rows")
        rows = raw_rows if isinstance(raw_rows, list) else []
        columns = payload.get("columns")
        hop = {
            "question": self._last_lab_question,
            "sql": sql[:4_000],
            "columns": [str(column) for column in columns][:24]
            if isinstance(columns, list)
            else [],
            "rows": [list(row) if isinstance(row, (list, tuple)) else [row] for row in rows][
                :_HOP_MAX_ROWS
            ],
            "row_count": len(rows),
        }
        self._hops = [*self._hops[-(_HOP_MAX_ENTRIES - 1) :], hop]

    def _record_query_table(self, payload: Mapping[str, Any]) -> None:
        """Keep the full grid for export_xlsx; hops stay clipped for labs."""

        table = snapshot_query_table(payload, question=self._last_lab_question)
        if table is None:
            return
        self._query_tables = [*self._query_tables[-(_QUERY_TABLE_MAX - 1) :], table]

    def _restore_query_tables(self, run_id: str) -> None:
        """Rebuild full grids from stored query_db artifacts after resume."""

        self._query_tables = []
        lister = getattr(self._artifacts, "list_for_run", None)
        if not callable(lister):
            return
        try:
            items = lister(run_id)
        except Exception:  # noqa: BLE001 — resume must not die on a missing helper
            return
        if not isinstance(items, (list, tuple)):
            return
        tables: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, Mapping) or item.get("kind") != TOOL_RESULT_KIND:
                continue
            body = item.get("payload")
            if not isinstance(body, Mapping):
                continue
            if body.get("name") != "query_db" or not body.get("ok"):
                continue
            inner = body.get("payload")
            if not isinstance(inner, Mapping):
                continue
            table = snapshot_query_table(inner, question=str(inner.get("question") or ""))
            if table is not None:
                tables.append(table)
        self._query_tables = tables[-_QUERY_TABLE_MAX:]

    def _invalidate_facts(self) -> None:
        """Drop query facts and hops after a caliber change."""

        self._facts = []
        self._hops = []
        self._query_tables = []

    async def _review_sql_coverage(
        self,
        *,
        client: ChatCompletionClient | None,
        sql: str,
        question: str,
    ) -> dict[str, Any] | None:
        """Judge SQL against the question and ledger; never raises to the loop."""

        reviewer = getattr(client, "complete_json", None)
        if not callable(reviewer) or not sql.strip():
            return None
        try:
            completion = await reviewer(
                purpose="agent.sql_review",
                system_prompt=SQL_REVIEW_SYSTEM,
                user_prompt=build_sql_review_user_prompt(
                    question=question, ledger=self._ledger, sql=sql
                ),
                max_tokens=400,
            )
            payload = getattr(completion, "payload", None)
            if not isinstance(payload, Mapping):
                payload = None
            return interpret_sql_review(payload)
        except Exception:  # noqa: BLE001 — a reviewer outage must not drop the query
            _LOGGER.warning("sql coverage review raised", exc_info=True)
            return interpret_sql_review(None)

    # ------------------------------------------------------------ projections

    async def _emit_charts_if_any(
        self,
        *,
        run_id: str,
        client: ChatCompletionClient,
        question: str,
        answer: str,
    ) -> None:
        """Post-loop chart stage: never registered as an Agent tool."""

        if self._artifacts.latest(run_id=run_id, kind="analysis_chart") is not None:
            return
        if self._artifacts.latest(run_id=run_id, kind="bi_report") is not None:
            return

        from xiaoying_quick.application.agent_run.chart_post import maybe_build_charts

        if self._is_cancelled(run_id):
            raise AgentCancelled()
        try:
            # Excel charts use present_chart with explicitly confirmed units.
            if self._tool_dependencies.get("lab_provider") == "xlsx":
                return
            payload = await maybe_build_charts(
                client=client,
                question=question,
                answer=answer,
                query_tables=self._query_tables,
                is_cancelled=lambda: self._is_cancelled(run_id),
            )
            if self._is_cancelled(run_id):
                raise AgentCancelled()
            if not payload:
                return
            self._emit(run_id, AgentEventType.CHART_READY, payload)
        except AgentCancelled:
            raise
        except Exception:  # noqa: BLE001 — charts must not fail a completed run
            _LOGGER.warning("chart post-step raised", exc_info=True)

    def _complete(
        self,
        run_id: str,
        session: ChatSession,
        *,
        answer: str,
        turn_messages: list[dict[str, Any]],
    ) -> None:
        self._emit(run_id, AgentEventType.AGENT_DONE, {"answer": answer})
        self._chats.append_assistant_message(session, run_id, answer, ())
        self._artifacts.append(
            run_id=run_id,
            kind=TRANSCRIPT_KIND,
            payload={
                "turn_messages": turn_messages,
                **self._snapshot(run_id),
                "status": "completed",
                # The final ledger is the turn's understanding of its question;
                # the next turn of the session inherits it.
                "ledger": self._ledger,
            },
        )
        self._checkpoint()
        self._runs.transition(run_id=run_id, target=RunStatus.COMPLETED)
        self._emit(run_id, AgentEventType.TURN_END, {})

    def _fail(self, run_id: str, code: str, message: str) -> None:
        self._emit(
            run_id,
            AgentEventType.AGENT_FAILED,
            {"code": code, "message": message[:500]},
        )
        try:
            self._runs.transition(run_id=run_id, target=RunStatus.FAILED)
        except InvalidTransition:
            # Already terminal (completed/cancelled concurrently): keep state.
            pass

    def _emit(self, run_id: str, event_type: str | AgentEventType, payload: dict[str, Any]) -> None:
        rich_chart = str(event_type) == "chart.ready" and payload.get("version") == 2
        self._runs.append_event(
            run_id=run_id, event_type=str(event_type),
            payload=dict(payload) if rich_chart else _fit_event_payload(payload)
        )
        self._checkpoint()

    def _save_checkpoint(
        self,
        run_id: str,
        step: int,
        turn_messages: list[dict[str, Any]],
        *,
        pending: dict[str, Any] | None,
    ) -> None:
        payload: dict[str, Any] = {
            "turn_messages": turn_messages,
            **self._snapshot(run_id),
            "status": "suspended" if pending else "running",
            "step": step,
            "prompt_version": AGENT_PROMPT_VERSION,
            "ledger": self._ledger,
            "facts": self._facts,
            "hops": self._hops,
            "last_lab_question": self._last_lab_question,
            "use_memory": self._use_memory,
        }
        if pending is not None:
            payload["pending"] = pending
        self._artifacts.append(run_id=run_id, kind=TRANSCRIPT_KIND, payload=payload)
        self._checkpoint()

    async def _continue_from_checkpoint(
        self,
        *,
        actor_id: str,
        run_id: str,
        session: ChatSession,
        checkpoint: Mapping[str, Any],
    ) -> None:
        self._run_id = run_id
        self._ledger = _load_ledger(checkpoint.get("ledger"))
        self._facts = _load_facts(checkpoint.get("facts"))
        self._hops = _load_hops(checkpoint.get("hops"))
        self._last_lab_question = str(checkpoint.get("last_lab_question") or "")
        self._restore_query_tables(run_id)
        turn_messages: list[dict[str, Any]] = list(checkpoint.get("turn_messages", []))
        messages = [
            ChatTurn(role="system", content=self._system_prompt()),
            *self._restore_model_view(session.id, run_id, checkpoint, turn_messages),
        ]
        # An assistant message whose tool calls never got results would break
        # the protocol; drop it and let the model think again from the trail.
        if messages and messages[-1].role == "assistant" and messages[-1].tool_calls:
            messages.pop()
            turn_messages.pop()
        try:
            await self._loop(
                actor_id=actor_id,
                run_id=run_id,
                session=session,
                messages=messages,
                turn_messages=turn_messages,
                step=int(checkpoint.get("step", 0)),
                anchor_question=_run_question_from_checkpoint(checkpoint),
            )
        except AgentSuspended:
            return

    def _context_scope(self):
        return {
            "provider": self._tool_dependencies.get("lab_provider") or "",
            "chatbot": self._tool_dependencies.get("chatbot_id") or "ddi",
            "workbooks": sorted(self._tool_dependencies.get("workbook_ids") or []),
        }

    def _snapshot(self, run_id):
        if self._working_messages is None:
            return {}
        records = [_serialize_turn(m) for m in self._working_messages if m.role != "system"]
        for record in records:
            record.pop("reasoning", None)
        return {"working_context": records, "context_scope": self._context_scope(),
                "context_run_id": run_id, "context_run_ids": self._context_run_ids[-64:]}

    def _restore_model_view(self, session_id, run_id, checkpoint, raw_turn):
        if "working_context" in checkpoint and checkpoint.get("context_scope") == self._context_scope():
            self._context_run_ids = list(checkpoint.get("context_run_ids") or [])
            return [_turn_from_record(rec) for rec in checkpoint["working_context"]]
        return [*self._replay_history(session_id=session_id, excluding_run_id=run_id),
                *(_turn_from_record(rec) for rec in raw_turn)]

    def _replay_history(self, *, session_id: str, excluding_run_id: str) -> list[ChatTurn]:
        scope = self._context_scope()
        args = dict(session_id=session_id, kind=TRANSCRIPT_KIND, excluding_run_id=excluding_run_id,
                    workbook_ids=scope["workbooks"])

        def compatible(rows):
            return [row for row in rows if row.get("status") == "completed"
                    and row.get("context_scope", scope) == scope]

        recent = self._artifacts.list_for_session(**args, limit=32)
        rows = compatible(recent)
        if len(recent) == 32 and not any("working_context" in row for row in rows):
            rows = compatible(self._artifacts.list_for_session(**args, limit=None))
        base = next((row for row in reversed(rows) if "working_context" in row), None)
        records = list(base["working_context"]) if base else []
        included = set(base.get("context_run_ids", [])) if base else set()
        if base:
            included.add(base.get("context_run_id"))
        for row in rows:
            if row is base or row.get("context_run_id") in included:
                continue
            records.extend(row.get("turn_messages") or [])
        self._context_run_ids = [row["context_run_id"] for row in rows if row.get("context_run_id")]
        return [_turn_from_record(record) for record in records]

    def _system_prompt(self) -> str:
        template = self._tool_dependencies.get("agent_system_prompt") or AGENT_SYSTEM_PROMPT
        base = template.format(
            today=date.today().isoformat(),
            labs="、".join(self._lab_ids) if self._lab_ids else "（未配置）",
        ) + str(self._tool_dependencies.get("lab_runtime_prompt") or "")
        base += str(self._tool_dependencies.get("mode_system_prompt") or "")
        if self._loop_budget is not None and self._loop_budget.system_addon:
            return base + self._loop_budget.system_addon
        return base

    # ----------------------------------------------------------------- ledger

    def _prime_context(self, *, actor_id: str, run_id: str, session_id: str, question: str) -> None:
        """Recall the asker's confirmed scopes before the first model call.

        Memory is saved but useless unless it is injected: personal memory
        entries and this session's answered clarifications become binding
        scope entries in the ledger, and the anchor re-states them at every
        step. Priming runs once per turn; resume/continue reuse the ledger.
        """

        step = 0
        for text in _question_caliber_slots(
            question, self._tool_dependencies.get("knowledge_root")
        ):
            self._add_ledger(step=step, kind="caliber", text=text, key="时间窗口")
        if self._use_memory:
            for key, text in self._recall_memory_scopes(
                actor_id=actor_id, run_id=run_id, session_id=session_id, question=question
            ):
                self._add_ledger(step=step, kind="scope", text=text, key=key)
        for key, text in self._session_clarified_scopes(session_id):
            self._add_ledger(step=step, kind="scope", text=text, key=key)

    def _inherit_ledger(self, *, session_id: str, excluding_run_id: str) -> None:
        """Seed the new turn with the last completed turn's understanding.

        Multi-turn follow-ups (“那盒数呢?”) keep everything the previous turn
        figured out; unrelated new questions rebuild via the prompt's hygiene
        rule (the model overwrites stale entries).
        """

        source_filter = {}
        if self._tool_dependencies.get("workbook_ids") is not None:
            source_filter["workbook_ids"] = self._tool_dependencies["workbook_ids"]
        transcripts = self._artifacts.list_for_session(
            session_id=session_id,
            kind=TRANSCRIPT_KIND,
            excluding_run_id=excluding_run_id,
            limit=32,
            **source_filter,
        )
        latest: Mapping[str, Any] | None = None
        for transcript in transcripts:
            if transcript.get("status") == "completed" and transcript.get("ledger"):
                latest = transcript
        if latest is None:
            return
        existing_text = {entry["text"] for entry in self._ledger}
        existing_keys = {str(entry.get("key") or "") for entry in self._ledger if entry.get("key")}
        inherited = []
        for entry in _load_ledger(latest.get("ledger")):
            if entry.get("kind") not in _DURABLE_LEDGER_KINDS:
                continue
            if entry["text"] in existing_text:
                continue
            key = str(entry.get("key") or "")
            # Source-filtered clarification records already supply the latest answer.
            if (
                self._tool_dependencies.get("workbook_ids") is not None
                and key.startswith("clarify:")
            ):
                continue
            if key and key in existing_keys:
                continue
            inherited.append(entry)
        if not inherited:
            return
        self._ledger = _trim_ledger([*self._ledger, *inherited])
        self._emit_ledger()

    def _remove_ledger_entry(self, key: str) -> None:
        """Drop the entry with this key (multi-turn tidying)."""

        kept = [entry for entry in self._ledger if entry.get("key") != key]
        if len(kept) == len(self._ledger):
            return
        self._ledger = kept
        self._emit_ledger()

    def _recall_memory_scopes(
        self, *, actor_id: str, run_id: str, session_id: str, question: str
    ) -> list[tuple[str, str]]:
        broker = self._tool_dependencies.get("context_broker")
        if broker is None:
            return []
        try:
            pack = broker.recall(
                RecallRequest(
                    request_id=new_id("recall"),
                    level=RecallLevel.L1_UNDERSTANDING,
                    actor_id=actor_id,
                    session_id=session_id,
                    frame_id=run_id,
                    query=question[:1_000],
                    allowed_source_types=frozenset({RecallSourceType.PERSONAL_MEMORY}),
                ),
                performed_at=datetime.now(timezone.utc),
            )
        except Exception:  # noqa: BLE001 - priming must never fail the run
            _LOGGER.warning("memory priming recall failed", exc_info=True)
            return []
        scopes: list[tuple[str, str]] = []
        seen: set[str] = set()
        for hit in pack.items:
            if hit.source_type is not RecallSourceType.PERSONAL_MEMORY:
                continue
            text = _scope_text(_memory_conclusion(hit.content))
            # Attention history and legacy slot dumps are not binding scopes.
            if not text or text.startswith("问过") or text.startswith("提问「") or text in seen:
                continue
            seen.add(text)
            key = (
                f"memory:{hit.content_id}"
                if getattr(hit, "content_id", None)
                else f"memory:{text[:32]}"
            )
            scopes.append((key[:40], text))
            if len(scopes) >= _PRIMED_MEMORY_LIMIT:
                break
        return scopes

    def _session_clarified_scopes(self, session_id: str) -> list[tuple[str, str]]:
        lister = getattr(self._clarifications, "list_answered_for_session", None)
        if lister is None:
            return []
        source_filter = {}
        if self._tool_dependencies.get("workbook_ids") is not None:
            source_filter["workbook_ids"] = self._tool_dependencies["workbook_ids"]
        try:
            cases = lister(session_id, **source_filter)
        except Exception:  # noqa: BLE001 - priming must never fail the run
            _LOGGER.warning("clarification scope lookup failed", exc_info=True)
            return []
        scopes: list[tuple[str, str]] = []
        seen: set[str] = set()
        seen_keys: set[str] = set()
        for case in cases:
            by_question = {entry.question_id: entry for entry in case.answers}
            for question in case.questions:
                entry = by_question.get(question.question_id)
                if entry is None:
                    continue
                choice = next(
                    (
                        item.label
                        for item in question.choices
                        if entry.choice_id and item.choice_id == entry.choice_id
                    ),
                    None,
                )
                reply = choice or (entry.free_text or "").strip()
                if not reply:
                    continue
                text = _scope_text(f"用户确认：{question.prompt} → {reply}")
                key = _clarify_key(question.prompt)
                if not text or text in seen or key in seen_keys:
                    continue
                seen.add(text)
                seen_keys.add(key)
                scopes.append((key, text))
                if len(scopes) >= _PRIMED_CLARIFY_LIMIT:
                    return scopes
        return scopes

    def _add_ledger(self, *, step: int, kind: str, text: str, key: str = "") -> None:
        clean = " ".join(str(text).split()).strip()
        if not clean:
            return
        if key.strip():
            self._upsert_ledger_entry(
                step=step,
                entry={"key": key.strip()[:40], "kind": kind, "text": clean},
            )
            return
        if len(clean) > _LEDGER_ENTRY_CHARS:
            clean = clean[:_LEDGER_ENTRY_CHARS] + "…"
        self._ledger = _trim_ledger([*self._ledger, {"step": step, "kind": kind, "text": clean}])
        self._emit_ledger()

    def _add_fact(self, text: str) -> None:
        clean = " ".join(str(text).split()).strip()
        if not clean:
            return
        self._facts = [*self._facts[-(_FACT_MAX_ENTRIES - 1) :], clean[:_LEDGER_ENTRY_CHARS]]

    def _upsert_ledger_entry(self, *, step: int, entry: Mapping[str, Any]) -> None:
        """Insert or refresh one model-written entry; same key replaces in place."""

        key = str(entry.get("key") or "").strip()
        kind = str(entry.get("kind") or "term").strip()
        text = " ".join(str(entry.get("text") or "").split()).strip()
        if not key or len(text) < 2:
            return
        if len(text) > _LEDGER_ENTRY_CHARS:
            text = text[:_LEDGER_ENTRY_CHARS] + "…"
        previous = next(
            (item for item in self._ledger if item.get("key") and item.get("key") == key),
            None,
        )
        if (
            previous is not None
            and previous.get("text") != text
            and (
                previous.get("kind") in _CONSTRAINT_LEDGER_KINDS or kind in _CONSTRAINT_LEDGER_KINDS
            )
        ):
            self._invalidate_facts()
        kept = [item for item in self._ledger if not (item.get("key") and item.get("key") == key)]
        kept.append({"step": step, "kind": kind, "text": text, "key": key})
        self._ledger = _trim_ledger(kept)
        self._emit_ledger()

    def _emit_ledger(self) -> None:
        if self._tool_dependencies.get("lab_provider") in ("gilead", "xlsx"):
            return
        self._emit(
            self._run_id,
            AgentEventType.LEDGER_UPDATED,
            {"entries": [dict(entry) for entry in self._ledger]},
        )

    def _active_scopes(self) -> tuple[str, ...]:
        return tuple(entry["text"] for entry in self._ledger if entry.get("kind") == "scope")[:8]

    def _open_case(
        self, *, run_id: str, session: ChatSession, groups: list[dict[str, Any]]
    ) -> ClarificationCase:
        questions = []
        for group in groups:
            choices = tuple(
                ClarificationChoice(
                    choice_id=new_id("choice"),
                    label=str(option.get("label", "")).strip(),
                    recommended=bool(option.get("recommended")),
                )
                for option in group.get("options", [])
                if str(option.get("label", "")).strip()
            )
            questions.append(
                ClarificationQuestion(
                    question_id=new_id("question"),
                    prompt=str(group.get("question", "")).strip(),
                    reason=ClarificationReason.CRITICAL_SLOT_AMBIGUITY,
                    choices=choices,
                    allow_free_text=bool(group.get("allow_free_text")),
                    multi_select=bool(group.get("multi_select")),
                    why=str(group.get("why") or "")[:600],
                )
            )
        case = ClarificationCase.open(
            case_id=new_id("case"),
            run_id=run_id,
            session_id=session.id,
            frame_id=run_id,
            questions=tuple(questions),
            created_at=datetime.now(timezone.utc),
            topic_id=run_id,
        )
        # A run can suspend more than once; the clarification table is unique
        # per (run_id, revision), so each new case bumps the revision.
        latest = self._clarifications.for_run(run_id)
        if latest is not None:
            case = replace(case, version=latest.version + 1)
        self._clarifications.save(case)
        self._checkpoint()
        return case

    def _answer_case(
        self,
        case: ClarificationCase,
        answer: str,
        answers: Mapping[str, str] | None = None,
    ) -> list[tuple[str, str]]:
        """Record the answers and return the (question, answer) pairs."""

        now = datetime.now(timezone.utc)
        recorded: list[ClarificationAnswer] = []
        pairs: list[tuple[str, str]] = []
        by_question = dict(answers or {})
        for question in case.questions:
            text = str(by_question.get(question.question_id) or "").strip()[:2_000]
            if not text:
                continue
            matched = next(
                (choice for choice in question.choices if choice.label == text),
                None,
            )
            recorded.append(
                ClarificationAnswer(
                    question_id=question.question_id,
                    answered_at=now,
                    choice_id=matched.choice_id if matched else None,
                    free_text=None if matched else text,
                )
            )
            pairs.append((question.prompt, text))
        if not recorded:
            # Legacy resume payload without per-question answers: keep the old
            # single-answer behaviour so an in-flight job still lands.
            first = case.questions[0] if case.questions else None
            choices = first.choices if first else ()
            matched = next(
                (choice for choice in choices if choice.label == answer),
                None,
            )
            recorded.append(
                ClarificationAnswer(
                    question_id=first.question_id if first else "free_text",
                    answered_at=now,
                    choice_id=matched.choice_id if matched else None,
                    free_text=None if matched else answer[:2_000],
                )
            )
            pairs.append((first.prompt if first else "", answer.strip()[:2_000]))
        self._clarifications.save(
            replace(
                case,
                status=ClarificationStatus.ANSWERED,
                answers=case.answers + tuple(recorded),
                answered_at=now,
            )
        )
        self._checkpoint()
        return pairs

    def _remember_clarification(
        self,
        *,
        actor_id: str,
        run_id: str,
        case: ClarificationCase,
        answer: str,
        checkpoint: Mapping[str, Any],
        answered: Sequence[tuple[str, str]] = (),
    ) -> None:
        """Persist every answered clarification into the asker's memory.

        A clarification conclusion is a durable scope/definition for this
        user, so the write happens deterministically here instead of relying
        on the model remembering to call ``memory_save``.
        """
        if not self._use_memory:
            return
        writer = self._tool_dependencies.get("memory_writer")
        if writer is None:
            return
        pairs = [(prompt, reply) for prompt, reply in answered if prompt and reply]
        if not pairs:
            question = case.questions[0] if case.questions else None
            prompt = question.prompt.strip() if question is not None else ""
            reply = answer.strip()
            if not prompt or not reply:
                return
            pairs = [(prompt, reply)]
        original = _run_question_from_checkpoint(checkpoint)
        content = f"原始问题：{original}\n" if original else ""
        content += "\n".join(f"澄清问题：{prompt}\n用户结论：{reply}" for prompt, reply in pairs)
        content += "\n（系统依据本轮澄清自动记录）"
        content = content[:1_800]
        try:
            entry = writer.write(
                actor_id,
                MemoryWriteRequest(category="scope", content=content, source_run_id=run_id),
            )
        except Exception:  # noqa: BLE001 - memory write must never fail the resume
            _LOGGER.warning("clarification memory write failed", exc_info=True)
            return
        self._emit(
            run_id,
            AgentEventType.MEMORY_AUTO_SAVED,
            {"entry_id": entry.id, "category": entry.category, "case_id": case.case_id},
        )


# ------------------------------------------------------------- serialization


def _serialize_turn(turn: ChatTurn) -> dict[str, Any]:
    record: dict[str, Any] = {"role": turn.role, "content": turn.content}
    if turn.reasoning:
        record["reasoning"] = turn.reasoning
    if turn.tool_calls:
        record["tool_calls"] = [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in turn.tool_calls
        ]
    if turn.tool_call_id:
        record["tool_call_id"] = turn.tool_call_id
    return record


def _turn_from_record(record: Mapping[str, Any]) -> ChatTurn:
    raw_calls = record.get("tool_calls") or []
    calls = tuple(
        ToolCallFragment(
            id=str(call.get("id", "")),
            name=str((call.get("function") or call).get("name", "")),
            arguments=str((call.get("function") or call).get("arguments", "{}")),
        )
        for call in raw_calls
        if isinstance(call, Mapping)
    )
    return ChatTurn(
        role=str(record.get("role", "user")),
        content=str(record.get("content") or ""),
        reasoning=str(record.get("reasoning") or ""),
        tool_calls=calls,
        tool_call_id=str(record.get("tool_call_id", "")),
    )


def _resolve_use_memory(explicit: bool | None, checkpoint: Mapping[str, Any] | None) -> bool:
    """Job payload wins; a resumed checkpoint keeps the original choice."""

    return False


def _run_question_from_checkpoint(checkpoint: Mapping[str, Any]) -> str:
    """The user question that opened the current turn (first user message)."""

    for record in checkpoint.get("turn_messages", []):
        if isinstance(record, Mapping) and record.get("role") == "user":
            return str(record.get("content", "")).strip()[:200]
    return ""


def _pending_calls_after(
    checkpoint: Mapping[str, Any], call_id: str
) -> tuple[ToolCallFragment, ...]:
    """Tool calls issued in the same assistant turn after the suspended one."""

    for record in reversed(list(checkpoint.get("turn_messages", []))):
        if not isinstance(record, Mapping) or record.get("role") != "assistant":
            continue
        calls = tuple(
            ToolCallFragment(
                id=str(call.get("id", "")),
                name=str(call.get("name", "")),
                arguments=str(call.get("arguments", "{}")),
            )
            for call in record.get("tool_calls", [])
            if isinstance(call, Mapping)
        )
        ids = [call.id for call in calls]
        if call_id in ids:
            return calls[ids.index(call_id) + 1 :]
        return ()
    return ()


def _event_preview(payload: Mapping[str, Any]) -> dict[str, Any]:
    """A bounded projection of the full tool payload for the event stream."""

    preview: dict[str, Any] = {}
    for key in (
        "sql",
        "sql_ref",
        "source_sql_refs",
        "lab_id",
        "lab_provider",
        "mock_enabled",
        "question",
        "query",
        "lab_type",
        "text",
        "path",
        "columns",
        "truncated",
        "duration_ms",
        "scope",
        "category",
        "title",
        "content",
        "entry_id",
        "lab_session_id",
        "attach_upstream",
        "sql_review",
        "filename",
        "summary",
        "download_path",
        "export_id",
        "row_count",
    ):
        if key in payload:
            value = payload[key]
            if key == "text" and isinstance(value, str):
                preview[key] = value[:1_200]
            else:
                preview[key] = value
    loop_prompts = payload.get("loop_prompts")
    if isinstance(loop_prompts, Mapping):
        # Bounded per-slot clip: the preview is for display, the artifact keeps
        # the full text.
        preview["loop_prompts"] = {key: str(value)[:1_200] for key, value in loop_prompts.items()}
    rows = payload.get("rows")
    if isinstance(rows, list):
        preview["rows"] = rows[:30]
        preview["row_count"] = len(rows)
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        preview["candidates"] = candidates[:5]
    return preview


def _fit_event_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Shrink text fields without looping when nested data exceeds the cap."""

    fitted = dict(payload)
    encoded = json.dumps(fitted, ensure_ascii=False, separators=(",", ":"), default=str)
    while len(encoded.encode("utf-8")) > _EVENT_PAYLOAD_BYTES:
        target = max(
            (key for key, value in fitted.items()
             if isinstance(value, str) and len(value) > 4 * len(_TRUNCATION_MARKER)),
            key=lambda key: len(fitted[key]),
            default=None,
        )
        if target is None:
            break
        text = fitted[target]
        fitted[target] = text[: max(0, len(text) * 3 // 4)] + _TRUNCATION_MARKER
        encoded = json.dumps(fitted, ensure_ascii=False, separators=(",", ":"), default=str)
    return fitted


def _load_ledger(raw: Any) -> list[dict[str, Any]]:
    """Restore ledger entries from a checkpoint payload, defensively."""

    if not isinstance(raw, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        record = {
            "step": int(item.get("step") or 0),
            "kind": str(item.get("kind") or "fact"),
            "text": text[: _LEDGER_ENTRY_CHARS + 1],
        }
        key = str(item.get("key") or "").strip()
        if key:
            record["key"] = key[:40]
        entries.append(record)
    return _trim_ledger(entries)


def _load_hops(raw: Any) -> list[dict[str, Any]]:
    """Restore verified query hops from a checkpoint payload."""

    if not isinstance(raw, list):
        return []
    hops: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        sql = str(item.get("sql") or "").strip()
        if not sql:
            continue
        rows_raw = item.get("rows")
        rows = rows_raw if isinstance(rows_raw, list) else []
        columns = item.get("columns")
        hops.append(
            {
                "question": str(item.get("question") or "")[:500],
                "sql": sql[:4_000],
                "columns": [str(column) for column in columns][:24]
                if isinstance(columns, list)
                else [],
                "rows": [list(row) if isinstance(row, (list, tuple)) else [row] for row in rows][
                    :_HOP_MAX_ROWS
                ],
                "row_count": int(item.get("row_count") or len(rows)),
            }
        )
        if len(hops) >= _HOP_MAX_ENTRIES:
            break
    return hops


def _clarify_key(prompt: str) -> str:
    """Stable ledger key for one clarification prompt."""

    clean = " ".join(str(prompt or "").split()).strip()
    if len(clean) > 32:
        digest = hashlib.sha256(clean.encode()).hexdigest()[:8]
        return f"clarify:{clean[:23]}:{digest}"
    return f"clarify:{clean[:32]}"


def _trim_ledger(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bound the ledger; scopes are never dropped, oldest facts go first."""

    if len(entries) <= _LEDGER_MAX_ENTRIES:
        return entries
    overflow = len(entries) - _LEDGER_MAX_ENTRIES
    droppable = [index for index, entry in enumerate(entries) if entry.get("kind") != "scope"]
    drop = set(droppable[:overflow])
    kept = [entry for index, entry in enumerate(entries) if index not in drop]
    if len(kept) > _LEDGER_MAX_ENTRIES:
        # Scopes alone overflow the cap; keep the most recent ones.
        kept = kept[-_LEDGER_MAX_ENTRIES:]
    return kept


def _anchor_block(question: str, ledger: Sequence[Mapping[str, Any]], facts: Sequence[str]) -> str:
    """Compact re-anchoring block appended to the system prompt each step."""

    clean = " ".join(str(question or "").split())
    if not clean and not ledger and not facts:
        return ""
    lines = ["", "## 进度锚点（每一步都必须以此为准）"]
    if clean:
        lines.append(f"原始问题：{clean[:300]}")
    elements = [
        entry["text"]
        for entry in ledger
        if entry.get("kind") in {"caliber", "term", "constant", "qualifier", "formula"}
    ]
    times = [entry["text"] for entry in ledger if entry.get("kind") == "time"]
    scopes = [entry["text"] for entry in ledger if entry.get("kind") == "scope"]
    if times:
        lines.append("已确认时间事实（一切取数时间的依据，优先于任何默认估算）：")
        lines.extend(f"- {text}" for text in times)
    if elements:
        lines.append("当前问题的口径要素（产品/时间/指标等）：")
        lines.extend(f"- {text}" for text in elements)
    if scopes:
        lines.append("已确认口径（必须遵守，与问题明显冲突时先 ask_user 确认）：")
        lines.extend(f"- {text}" for text in scopes)
    if facts:
        lines.append("已确立事实（均来自 query_db 真实结果，不要重复查询、不得改写）：")
        lines.extend(f"- {text}" for text in facts)
    return "\n".join(lines) + "\n"


def _question_caliber_slots(question: str, knowledge_root: Any = None) -> list[str]:
    """Seed the ledger with the time window named in the question.

    Everything else — products, institutions, qualifiers, formulas — is
    written by the model through update_ledger as its understanding grows;
    static parsing of glossaries produced more noise than signal.
    """

    del knowledge_root
    tokens = [match.group(0).strip() for match in _TIME_TOKEN_PATTERN.finditer(str(question or ""))]
    if tokens:
        return [f"时间窗口：{'、'.join(dict.fromkeys(tokens))}（问题原文，待确认）"]
    return []


def _memory_conclusion(content: str) -> str:
    """Reduce a stored clarification memory to its conclusion line."""

    text = str(content or "")
    marker_length = len("用户结论：")
    index = max(text.rfind("用户结论："), text.rfind("用户结论:"))
    if index >= 0:
        conclusion = text[index + marker_length :].splitlines()[0].strip()
        for marker in ("（系统", "(系统"):
            marker_at = conclusion.find(marker)
            if marker_at >= 0:
                conclusion = conclusion[:marker_at]
        return conclusion.strip()
    return text.strip()


def _load_facts(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    facts = [
        str(item).strip()[:_LEDGER_ENTRY_CHARS]
        for item in raw
        if isinstance(item, str) and str(item).strip()
    ]
    return facts[-_FACT_MAX_ENTRIES:]


def _fact_text(arguments: str, payload: Mapping[str, Any]) -> str:
    """One ledger line for a successful query_db call."""

    try:
        sql = str((json.loads(arguments) if arguments else {}).get("sql") or "")
    except (TypeError, ValueError):
        sql = ""
    sql = " ".join(sql.split())[:120]
    raw_rows = payload.get("rows")
    rows: list[Any] = raw_rows if isinstance(raw_rows, list) else []
    first = rows[0] if rows else None
    preview = ""
    if isinstance(first, list) and first:
        preview = "；首行 " + " | ".join(str(cell) for cell in first[:4])[:80]
    return f"查询成功，共 {len(rows)} 行{preview}。SQL：{sql}"


def _scope_text(content: str) -> str:
    """A memory hit becomes a scope line: keep it short and self-contained."""

    clean = " ".join(str(content or "").split()).strip()
    return clean[:300]


def _card_groups(case: ClarificationCase) -> list[dict[str, Any]]:
    """Project a case into the group shape the clarify card renders and submits."""

    return [
        {
            "question_id": question.question_id,
            "prompt": question.prompt,
            "why": question.why or "",
            "required": question.required,
            "multi_select": question.multi_select,
            "allow_free_text": question.allow_free_text,
            "choices": [
                {
                    "id": choice.choice_id,
                    "label": choice.label,
                    "explanation": choice.explanation or "",
                    "recommended": choice.recommended,
                    "source": choice.source,
                }
                for choice in question.choices
            ],
        }
        for question in case.questions
    ]
