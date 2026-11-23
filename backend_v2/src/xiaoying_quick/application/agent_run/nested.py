"""A nested agent loop: same model, a subset of tools, events tagged with the parent call."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date
from typing import Any

from xiaoying_quick.infrastructure.llm import (
    ChatTurn,
    ContentDelta,
    ReasoningDelta,
    ToolCallFragment,
    TurnComplete,
)
from xiaoying_quick.modules.agent import (
    AgentEventType,
    AgentSpec,
    AgentToolContext,
    ToolCallResult,
    ToolRegistry,
)

_LOGGER = logging.getLogger(__name__)
_MAX_STEPS = 8
_DELTA_FLUSH_CHARS = 120
_EVENT_REASONING_CHARS = 48_000


class NestedAgentRunner:
    """Run one sub-agent as a tool. Failures become the parent tool's observation."""

    def __init__(self, *, lab_ids: tuple[str, ...] = ()) -> None:
        self._lab_ids = lab_ids

    async def run(
        self,
        *,
        context: AgentToolContext,
        spec: AgentSpec,
        tools: ToolRegistry,
        arguments: Mapping[str, Any],
    ) -> ToolCallResult:
        parent_call_id = context.call_id or "nested"
        question = _question_from_arguments(spec, arguments)
        if not question:
            return ToolCallResult(ok=False, output="缺少要交给子智能体的问题。")
        try:
            client = context.dependency("llm_client")
        except LookupError:
            return ToolCallResult(ok=False, output=f"{spec.name}无法调用模型。")

        def emit(event_type: str, payload: dict[str, Any]) -> None:
            body = dict(payload)
            body["parent_call_id"] = parent_call_id
            body["agent_id"] = spec.id
            body["agent_name"] = spec.name
            context.emit(event_type, body)

        emit(AgentEventType.TURN_START, {"question": question})
        try:
            runtime_prompt = str(context.dependency("lab_runtime_prompt") or "")
        except LookupError:
            runtime_prompt = ""
        messages = [
            ChatTurn(role="system", content=_system_prompt(spec, self._lab_ids) + runtime_prompt),
            ChatTurn(role="user", content=question),
        ]
        last_answer = ""
        try:
            for step in range(1, _MAX_STEPS + 1):
                emit(AgentEventType.STEP_START, {"step": step})
                assistant = await _stream_step(
                    emit=emit, step=step, client=client, messages=messages, tools=tools
                )
                emit(
                    AgentEventType.ASSISTANT_MESSAGE,
                    {
                        "step": step,
                        "content": assistant.content,
                        "reasoning": assistant.reasoning[:_EVENT_REASONING_CHARS],
                        "finish_reason": assistant.finish_reason,
                        "usage": dict(assistant.usage),
                        "tool_calls": [
                            {"call_id": call.id, "name": call.name} for call in assistant.tool_calls
                        ],
                    },
                )
                messages.append(
                    ChatTurn(
                        role="assistant",
                        content=assistant.content,
                        reasoning=assistant.reasoning,
                        tool_calls=assistant.tool_calls,
                    )
                )
                if not assistant.tool_calls:
                    last_answer = assistant.content.strip()
                    break
                for call in assistant.tool_calls:
                    result = await _execute_nested_call(
                        context=context,
                        tools=tools,
                        emit=emit,
                        step=step,
                        call=call,
                    )
                    messages.append(
                        ChatTurn(role="tool", content=result.output, tool_call_id=call.id)
                    )
                    if (
                        call.name in {"ask_lab", "generate_sql"}
                        and result.ok
                        and (result.payload.get("sql") or result.payload.get("candidates"))
                    ):
                        last_answer = str(result.payload.get("sql") or result.output)
                    elif result.ok:
                        last_answer = result.output
            else:
                return ToolCallResult(
                    ok=False,
                    output=f"{spec.name}超过 {_MAX_STEPS} 步仍未结束。",
                    payload={"agent_id": spec.id},
                )
        except Exception as exc:  # noqa: BLE001 — nested failure is a tool observation
            _LOGGER.warning("nested agent failed", extra={"agent": spec.id, "error": str(exc)})
            emit(
                AgentEventType.AGENT_FAILED,
                {"code": type(exc).__name__, "message": str(exc)[:500]},
            )
            return ToolCallResult(
                ok=False,
                output=f"{spec.name}执行失败：{str(exc)[:800]}",
                payload={"agent_id": spec.id, "error": type(exc).__name__},
            )

        answer = last_answer or f"{spec.name}没有给出可用结果。"
        emit(AgentEventType.AGENT_DONE, {"answer": answer})
        return ToolCallResult(
            ok=True,
            output=answer,
            payload={"agent_id": spec.id, "agent_name": spec.name, "text": answer},
        )


def _system_prompt(spec: AgentSpec, lab_ids: tuple[str, ...]) -> str:
    template = spec.system_prompt or "你是一个子智能体。用可用工具完成任务，最终给出简短结论。"
    return template.format(
        today=date.today().isoformat(),
        labs="、".join(lab_ids) if lab_ids else "（未配置）",
    )


def _question_from_arguments(spec: AgentSpec, arguments: Mapping[str, Any]) -> str:
    from xiaoying_quick.modules.labs.labels import lab_display_name

    question = str(arguments.get("question") or arguments.get("query") or "").strip()
    if spec.id == "lab_sql":
        lab_id = str(arguments.get("lab_id") or "").strip()
        if lab_id:
            # Trace / nested user turn show the business name; tools still get lab_id.
            return f"实验室：{lab_display_name(lab_id)}\n问题：{question}"
    if spec.id == "bailian":
        lab_type = str(arguments.get("lab_type") or "").strip()
        if lab_type:
            return f"实验室：{lab_display_name(lab_type)}\nquery：{question}"
    return question


async def _stream_step(
    *,
    emit,
    step: int,
    client: Any,
    messages: list[ChatTurn],
    tools: ToolRegistry,
):
    think_buffer: list[str] = []
    content_buffer: list[str] = []
    completed: TurnComplete | None = None

    def flush(kind: AgentEventType, buffer: list[str]) -> None:
        text = "".join(buffer)
        buffer.clear()
        if text:
            emit(kind, {"step": step, "text": text})

    async for event in client.stream_chat(
        purpose=f"nested.step{step}",
        messages=messages,
        tools=tools.schemas(),
    ):
        if isinstance(event, ReasoningDelta):
            think_buffer.append(event.text)
            if sum(len(part) for part in think_buffer) >= _DELTA_FLUSH_CHARS:
                flush(AgentEventType.THINK_DELTA, think_buffer)
        elif isinstance(event, ContentDelta):
            content_buffer.append(event.text)
            if sum(len(part) for part in content_buffer) >= _DELTA_FLUSH_CHARS:
                flush(AgentEventType.CONTENT_DELTA, content_buffer)
        elif isinstance(event, TurnComplete):
            completed = event
    flush(AgentEventType.THINK_DELTA, think_buffer)
    flush(AgentEventType.CONTENT_DELTA, content_buffer)
    if completed is None:
        raise RuntimeError("nested model stream ended without a completion")
    return completed.turn


async def _execute_nested_call(
    *,
    context: AgentToolContext,
    tools: ToolRegistry,
    emit,
    step: int,
    call: ToolCallFragment,
) -> ToolCallResult:
    arguments = tools.parse_arguments(call.arguments)
    emit(
        AgentEventType.TOOL_CALL,
        {
            "call_id": call.id,
            "name": call.name,
            "step": step,
            "arguments": arguments,
        },
    )
    nested_context = AgentToolContext(
        run_id=context.run_id,
        session_id=context.session_id,
        actor_id=context.actor_id,
        emit=lambda event_type, payload: emit(event_type, payload),
        extras=context._extras,
        active_scopes=context.active_scopes,
        call_id=call.id,
    )
    if call.name == "ask_user":
        result = ToolCallResult(
            ok=False,
            output="子智能体不能向用户澄清。请在最终回答里写明缺什么。",
        )
    else:
        result = await tools.execute(name=call.name, context=nested_context, arguments=arguments)
    emit(
        AgentEventType.TOOL_RESULT,
        {
            "call_id": call.id,
            "name": call.name,
            "step": step,
            "ok": result.ok,
            "output": result.output,
            "preview": _preview(result.payload),
        },
    )
    return result


def _preview(payload: Mapping[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for key in (
        "sql",
        "lab_id",
        "question",
        "query",
        "lab_type",
        "text",
        "path",
        "candidates",
        "ddl",
        "tables",
        "hits",
        "groups",
        "valid",
        "errors",
    ):
        if key in payload:
            preview[key] = payload[key]
    return preview
