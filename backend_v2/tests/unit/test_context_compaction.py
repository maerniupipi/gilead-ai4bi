import asyncio
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from xiaoying_quick.application.agent_run.loop import AgentRunService
from xiaoying_quick.infrastructure.llm import ChatCompletionClient, ChatTurn, ToolCallFragment
from xiaoying_quick.infrastructure.llm.config import LlmConfig
from xiaoying_quick.infrastructure.llm.context_window import TARGET, TRIGGER, prepare_context
from xiaoying_quick.infrastructure.llm.token_count import PromptCounter


def _body():
    return {
        "model": "qwen3.5-122b-a10b",
        "enable_thinking": False,
        "messages": [
            {"role": "system", "content": "只读数据；保留单位。"},
            {"role": "user", "content": "2025年10月，全国人民币，限品牌甲"},
            {"role": "assistant", "content": "人民币 153.42；旧步骤"},
            {"role": "user", "content": "同口径，按省呢？"},
        ],
    }


@pytest.mark.parametrize("limit,expected", [(TRIGGER - 1, False), (TRIGGER, True)])
def test_threshold_counts_templated_qwen_tokens_and_keeps_scope(limit, expected):
    body = _body()
    counter = PromptCounter(body)
    body["messages"][2]["content"] += " x" * (limit - counter.messages_size(body["messages"]))
    original = copy.deepcopy(body)
    assert counter.messages_size(body["messages"]) == limit
    reading = prepare_context(body)
    assert reading.compacted is expected
    assert reading.source == "tokenizer"
    assert body["messages"][0] == original["messages"][0]
    assert body["messages"][-1] == original["messages"][-1]
    assert "2025年10月，全国人民币，限品牌甲" in repr(body)
    assert "153.42" in repr(body)
    if expected:
        assert reading.used <= TARGET and not prepare_context(body).compacted
    else:
        assert body["messages"] == original["messages"]


def test_tool_results_and_pending_parallel_calls_remain_valid_after_compaction():
    body = _body()
    body["messages"] = [body["messages"][0], body["messages"][-1]]
    replies = [
        {
            "role": "tool",
            "tool_call_id": name,
            "content": json.dumps(
                {"columns": ["人民币金额"], "rows": [[153.42], *([[216.34]] * 14000)]},
                ensure_ascii=False,
            ),
        }
        for name in ("a", "b")
    ]
    calls = [
        {
            "id": name,
            "type": "function",
            "function": {"name": "query_db", "arguments": '{"sql":"SELECT 1"}'},
        }
        for name in ("a", "b")
    ]
    body["messages"] += [
        {"role": "assistant", "tool_calls": calls},
        *replies,
        {"role": "assistant", "tool_calls": [{**calls[0], "id": "pending"}]},
    ]
    original = copy.deepcopy(body["messages"])
    reading = prepare_context(body)
    assert reading.compacted and reading.used < TARGET
    assert [m.get("tool_call_id") for m in body["messages"] if m["role"] == "tool"] == ["a", "b"]
    assert body["messages"][-1] == original[-1]
    assert "14001" in body["messages"][3]["content"] and "153.42" in body["messages"][3]["content"]
    assert len(original[3]["content"]) > len(body["messages"][3]["content"]) * 100


def test_context_meter_and_compaction_within_one_streamed_tool_chain():
    calls = []

    def send(request):
        calls.append(json.loads(request.content))
        choice = {"delta": {"content": "已核对。"}, "finish_reason": "stop"}
        data = {"choices": [choice], "usage": {"prompt_tokens": 3500, "completion_tokens": 8}}
        return httpx.Response(200, text="data: " + json.dumps(data) + "\n\ndata: [DONE]\n\n")

    client = ChatCompletionClient(
        LlmConfig(
            endpoint_url="https://example.test/v1/chat/completions",
            model_id="qwen3.5-122b-a10b",
            api_key="test",
        ),
        client=httpx.AsyncClient(transport=httpx.MockTransport(send)),
    )
    loop = object.__new__(AgentRunService)
    loop._tools = SimpleNamespace(schemas=lambda: [])
    events = []
    loop._emit = lambda run_id, kind, data: events.append((str(kind), data))
    loop._tool_dependencies = {"lab_provider": "gilead"}
    loop._context_run_ids = ["earlier"]
    messages = [
        ChatTurn(role="system", content="只读"),
        ChatTurn(role="user", content="仅浙江；使用人民币"),
    ]
    loop._working_messages = messages

    async def exercise():
        await loop._stream_one_step(run_id="r", step=1, client=client, messages=messages)
        messages.extend(
            [
                ChatTurn(
                    role="assistant",
                    tool_calls=(
                        ToolCallFragment(id="q", name="query_db", arguments='{"sql":"SELECT 1"}'),
                    ),
                ),
                ChatTurn(
                    role="tool",
                    tool_call_id="q",
                    content="销售额 153.42\n" + " x" * 49000 + "\n共 8 行",
                ),
            ]
        )
        await loop._stream_one_step(run_id="r", step=2, client=client, messages=messages)
        await loop._stream_one_step(run_id="r", step=3, client=client, messages=messages)
        await client.aclose()

    asyncio.run(exercise())
    notices = [data for kind, data in events if kind == "context.compacted"]
    assert len(notices) == 1 and notices[0]["step"] == 2
    assert notices[0]["before_tokens"] >= TRIGGER and notices[0]["used_tokens"] < TARGET
    assert calls[1]["messages"] == calls[2]["messages"]
    assert "153.42" in messages[-1].content
    saved = loop._snapshot("r")
    assert loop._restore_model_view("session", "r", saved, []) == messages[1:]
    loop._artifacts = SimpleNamespace(
        list_for_session=lambda **kwargs: [
            {
                "context_run_id": "sibling",
                "status": "completed",
                "turn_messages": [{"role": "user", "content": "另一轮"}],
            },
            {**saved, "status": "completed"},
            {
                **saved,
                "context_run_id": "other-bot",
                "context_scope": {"chatbot": "other"},
                "status": "completed",
            },
        ]
    )
    restored = loop._replay_history(session_id="session", excluding_run_id="new")
    assert restored[:-1] == messages[1:] and restored[-1].content == "另一轮"


def test_provider_completion_crossing_threshold_compacts_before_next_question():
    loop = object.__new__(AgentRunService)
    events = []
    loop._tools = SimpleNamespace(schemas=lambda: [])
    loop._emit = lambda run_id, kind, data: events.append((str(kind), data))
    client = SimpleNamespace(
        context_body=lambda messages, tools: {
            **_body(),
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
    )
    messages = [ChatTurn(role=m["role"], content=m["content"]) for m in _body()["messages"]]
    messages[2] = ChatTurn(role="assistant", content="金额 153.42" + " x" * 45000)
    messages.append(ChatTurn(role="assistant", content="仍限品牌甲。"))
    loop._context_after_reply(
        "r", 1, client, messages, {"prompt_tokens": 47003, "completion_tokens": 997}
    )
    assert events[-1][0] == "context.compacted" and events[-1][1]["phase"] == "reply"
    assert events[-1][1]["before_tokens"] == TRIGGER
    assert messages[-1].content == "仍限品牌甲。" and "153.42" in repr(messages)


def test_pinned_question_uses_remaining_output_budget_without_cutting_the_question():
    question = " x" * 57000
    body = _body()
    body.update(
        messages=[body["messages"][0], {"role": "user", "content": question}], max_tokens=8192
    )
    reading = prepare_context(body)
    assert body["messages"][-1]["content"] == question
    assert not reading.compacted and reading.used > TRIGGER
    assert body["max_tokens"] + reading.reserved_input == 60000
    body["messages"][-1]["content"] += " x" * 4000
    with pytest.raises(ValueError, match="缩短提问"):
        prepare_context(body)


def test_confirmed_scope_survives_a_second_compaction():
    body = _body()
    body["messages"][1:1] = [
        {"role": "user", "content": "按哪个渠道？"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "type": "function",
                    "id": "confirm",
                    "function": {"name": "ask_user", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "confirm", "content": "用户的回答：仅限医院渠道"},
        {"role": "assistant", "content": "已确认。"},
    ]
    body["messages"][6]["content"] += " x" * 49000
    assert prepare_context(body).compacted
    body["messages"].extend(
        [
            {"role": "assistant", "content": "各省合计已核对。" + " y" * 49000},
            {"role": "user", "content": "按相同渠道继续。"},
        ]
    )
    assert prepare_context(body).compacted
    assert "仅限医院渠道" in body["messages"][1]["content"]
    assert body["messages"][-1]["content"] == "按相同渠道继续。"
