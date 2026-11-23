"""Stream deltas must be concatenated verbatim: no whitespace may be lost.

Regression: trimming every delta fragment used to eat the space between tool
argument tokens, turning ``SELECT SUM(x) FROM t`` into ``SELECTSUM(x)FROMt``.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from xiaoying_quick.infrastructure.llm import ChatTurn, TurnComplete
from xiaoying_quick.infrastructure.llm.client import ChatCompletionClient
from xiaoying_quick.infrastructure.llm.config import LlmConfig


def _sse(*chunks: object) -> bytes:
    lines = [f"data: {json.dumps(chunk)}" for chunk in chunks]
    lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode("utf-8")


def _client(transport: httpx.MockTransport) -> ChatCompletionClient:
    return ChatCompletionClient(
        LlmConfig(
            endpoint_url="https://example.test/v1/chat/completions",
            api_key="sk-test",
            model_id="test-model",
        ),
        client=httpx.AsyncClient(transport=transport),
    )


def test_tool_call_arguments_keep_whitespace_between_deltas() -> None:
    chunks = (
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "query_db",
                                    "arguments": '{"sql": "SELECT ',
                                },
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [{"index": 0, "function": {"arguments": 'SUM(x) FROM t"}'}}]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=_sse(*chunks), headers={"content-type": "text/event-stream"}
        )
    )

    async def scenario() -> TurnComplete:
        client = _client(transport)
        try:
            events = [
                event
                async for event in client.stream_chat(
                    purpose="test", messages=[ChatTurn(role="user", content="hi")]
                )
            ]
        finally:
            await client.aclose()
        return next(event for event in events if isinstance(event, TurnComplete))

    complete = asyncio.run(scenario())
    call = complete.turn.tool_calls[0]
    assert json.loads(call.arguments) == {"sql": "SELECT SUM(x) FROM t"}


def test_content_deltas_keep_surrounding_whitespace() -> None:
    chunks = (
        {"choices": [{"delta": {"content": "你好 "}}]},
        {"choices": [{"delta": {"content": "世界"}, "finish_reason": "stop"}]},
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=_sse(*chunks), headers={"content-type": "text/event-stream"}
        )
    )

    async def scenario() -> TurnComplete:
        client = _client(transport)
        try:
            events = [
                event
                async for event in client.stream_chat(
                    purpose="test", messages=[ChatTurn(role="user", content="hi")]
                )
            ]
        finally:
            await client.aclose()
        return next(event for event in events if isinstance(event, TurnComplete))

    complete = asyncio.run(scenario())
    assert complete.turn.content == "你好 世界"
