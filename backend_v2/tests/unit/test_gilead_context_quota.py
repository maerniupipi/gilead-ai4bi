from datetime import datetime, timezone

from xiaoying_quick.infrastructure.llm.context_window import WINDOW, bound_context
from xiaoying_quick.infrastructure.monthly_quota import month_window


def test_chinese_conversation_fits_window_and_preserves_current_tool_exchange():
    history = []
    for _ in range(30):
        history.extend(
            [
                {"role": "user", "content": "2025年10月，全国销售金额？"},
                {"role": "assistant", "content": "全国实际销售金额人民币" * 400},
            ]
        )
    calls = [{"type": "function", "id": "q1", "function": {"name": "query_db", "arguments": "{}"}}]
    body = {
        "messages": [
            {"role": "system", "content": "使用真实查询"},
            *history,
            {"role": "user", "content": "改按品牌呢？"},
            {"role": "assistant", "content": "", "tool_calls": calls},
            {"role": "tool", "tool_call_id": "q1", "content": "行内容" * 8000},
        ],
        "tools": [{"type": "function", "function": {"name": "query_db"}}],
        "max_tokens": 4096,
    }
    assert bound_context(body) + body["max_tokens"] <= WINDOW
    assert any("历史对话摘要" in m.get("content", "") for m in body["messages"])
    assert body["messages"][-3]["content"] == "改按品牌呢？"
    assert body["messages"][-2]["tool_calls"][0]["id"] == body["messages"][-1]["tool_call_id"]


def test_shanghai_month_boundary_including_new_year():
    last, next_month = month_window(datetime(2026, 12, 31, 15, 59, 59, tzinfo=timezone.utc))
    now, following = month_window(datetime(2026, 12, 31, 16, tzinfo=timezone.utc))
    assert last.strftime("%Y-%m") == "2026-12"
    assert now == next_month
    assert following.isoformat() == "2027-02-01T00:00:00+08:00"
