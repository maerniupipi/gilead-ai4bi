from __future__ import annotations

import pytest

from xiaoying_quick.infrastructure.chatbots import ChatbotStore
from xiaoying_quick.infrastructure.workbook_lab import WorkbookLab
from xiaoying_quick.shared.errors import ValidationFailed


def test_workbook_queries_use_only_bound_values_and_weighted_ratios(tmp_path):
    store = ChatbotStore(tmp_path / "chatbots.sqlite3")
    book = store.workbook("workbook_behavior_sample")
    lab = WorkbookLab([book], lambda: None, None, lambda *_: pytest.fail("cross-source query"))
    columns, rows, truncated, _ = lab.execute(
        'SELECT "区域", SUM("活跃用户"), SUM("转化用户")/SUM("活跃用户") '
        'FROM wb_behavior_sample WHERE "月份"=\'2026-09-01\' GROUP BY "区域"',
        100,
    )
    assert columns[0] == "区域" and len(rows) == 3 and not truncated
    south = next(row for row in rows if row[0] == "华南")
    expected = [
        row for row in book["sheets"][0]["rows"] if row[0] == "2026-09-01" and row[1] == "华南"
    ]
    assert south[1] == sum(row[4] for row in expected)
    assert south[2] == pytest.approx(
        sum(row[5] for row in expected) / sum(row[4] for row in expected)
    )
    assert lab.execute("SELECT * FROM wb_behavior_sample", 5)[2] is True
    assert lab.source_for("SELECT * FROM wb_behavior_sample")["lab_provider"] == "xlsx"
    assert lab.source_for("SELECT * FROM sales_target_ai4bi") == {}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM wb_other_chatbot",
        "SELECT * FROM sales_target_ai4bi",
        "SELECT * FROM sqlite_master",
        "SELECT 1",
        "ATTACH DATABASE '/tmp/other' AS other",
        "SELECT * FROM wb_behavior_sample; SELECT 2",
        "DELETE FROM wb_behavior_sample",
        "SELECT load_extension('x') FROM wb_behavior_sample",
    ],
)
def test_workbook_cannot_fall_back_to_another_source_or_write(tmp_path, sql):
    import sqlite3

    store = ChatbotStore(tmp_path / "chatbots.sqlite3")
    lab = WorkbookLab(
        [store.workbook("workbook_behavior_sample")],
        lambda: None,
        None,
        lambda *_: pytest.fail("cross-source query"),
    )
    with pytest.raises((ValidationFailed, sqlite3.DatabaseError)):
        lab.execute(sql, 10)
