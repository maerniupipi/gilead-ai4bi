"""Regression checks for compound charts and business aggregation semantics."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from xiaoying_quick.application.agent_run.chart_tool import build_present_chart_tool
from xiaoying_quick.application.charts.analysis import automatic_analysis, build_analysis_bundle
from xiaoying_quick.modules.agent import AgentToolContext
from xiaoying_quick.modules.agent.events import AgentEventType, validate_agent_event
from xiaoying_quick.shared.errors import ValidationFailed


@pytest.fixture
def table():
    return {
        "columns": [
            "月份",
            "城市",
            "销售金额",
            "目标金额",
            "销售数量",
            "达成率",
            "同期金额",
            "同比",
            "毛利额",
            "终端数",
        ],
        "rows": [
            ["2026-01", "北京", 100, 100, 10, 1, 80, 0.25, 60, 1],
            ["2026-01", "上海", 50, 300, 5, 1 / 6, 40, 0.25, 30, 1],
            ["2026-02", "北京", 200, 200, 20, 1, 150, 1 / 3, 120, 1],
            ["2026-02", "上海", 100, 400, 10, 0.25, 80, 0.25, 60, 1],
        ],
        "truncated": False,
    }


@pytest.fixture
def metrics():
    return [
        {"column": name}
        for name in ("销售金额", "目标金额", "销售数量", "达成率", "同比", "毛利额")
    ]


@pytest.fixture
def summary(table):
    return {
        "columns": [*table["columns"][2:], "记录数"],
        "rows": [[450, 1000, 45, 0.45, 350, 450 / 350 - 1, 270, 2, 4]],
        "truncated": False,
    }


def test_weighted_rates_multibar_multiline_and_distinct_summary(table, metrics, summary):
    bundle = build_analysis_bundle(table, dimension="月份", metrics=metrics, summary=summary)
    cards = {item["label"]: item for item in bundle["kpis"]}
    assert cards["达成率"]["value"] == 0.45
    assert cards["同比"]["value"] == pytest.approx(450 / 350 - 1)
    assert cards["终端数"]["value"] == 2
    assert cards["终端数"]["unit"] == "家"
    assert cards["记录数"]["value"] == 4
    combo = bundle["charts"][0]["option"]
    assert [item["type"] for item in combo["series"]] == [
        "bar",
        "bar",
        "bar",
        "line",
        "line",
        "bar",
    ]
    assert len(combo["yAxis"]) == 3
    assert combo["series"][3]["data"] == [37.5, 50.0]
    assert bundle["data"]["rows"][0][4] == 0.375
    assert bundle["data"]["formats"]["达成率"]["percent"] is True
    assert {chart["type"] for chart in bundle["charts"]} == {
        "combo",
        "grouped_bar",
        "line",
        "horizontal_bar",
        "area",
        "pie",
        "donut",
        "pareto",
        "heatmap",
        "stacked_bar",
        "stacked_area",
        "scatter",
        "bubble",
        "radar",
    }
    validate_agent_event(AgentEventType.CHART_READY, bundle)
    json.dumps(bundle, allow_nan=False)


def test_count_metrics_do_not_add_a_fourth_plot_axis(table, summary):
    bundle = build_analysis_bundle(table, dimension="月份", summary=summary)
    assert len(bundle["charts"][0]["option"]["yAxis"]) == 3
    assert next(item for item in bundle["metrics"] if item["column"] == "终端数")["chart"] == "kpi"


def test_total_row_is_excluded_from_cards_and_breakdown_views(table, metrics):
    table["rows"].append(["合计", "合计", 450, 1000, 45, 0.45, 350, 450 / 350 - 1, 270, 2])
    bundle = build_analysis_bundle(table, dimension="月份", metrics=metrics)
    assert bundle["kpis"][0]["value"] == 450
    assert len(bundle["data"]["rows"]) == 2
    heatmap = next(chart for chart in bundle["charts"] if chart["type"] == "heatmap")
    assert len(heatmap["data"]["rows"]) == 4
    assert "合计" not in heatmap["option"]["xAxis"]["data"]
    assert any("合计行" in item for item in bundle["warnings"])


def test_mismatched_or_multirow_summary_is_rejected(table, metrics, summary):
    summary["rows"][0][0] = 451
    with pytest.raises(ValidationFailed, match="顶部汇总与图表数据不一致"):
        build_analysis_bundle(table, metrics=metrics, summary=summary)
    summary["rows"].append(summary["rows"][0])
    with pytest.raises(ValidationFailed, match="一行完整"):
        build_analysis_bundle(table, metrics=metrics, summary=summary)


def test_summary_aliases_follow_verified_sql_expressions():
    table = {
        "sql": 'SELECT "月份", SUM("金额") AS 销售金额, SUM("目标") AS 目标金额, '
        'SUM("盒数") AS 销售数量, SUM("金额") * 1.0 / NULLIF(SUM("目标"), 0) AS 达成率 '
        'FROM workbook GROUP BY "月份"',
        "columns": ["月份", "销售金额", "目标金额", "销售数量", "达成率"],
        "rows": [
            ["2026-09", 180000, 195000, 1800, 180000 / 195000],
            ["2026-10", 220000, 225000, 2200, 220000 / 225000],
        ],
    }
    summary = {
        "sql": 'SELECT SUM("金额") AS 累计销售额, SUM("目标") AS 累计目标额, '
        'SUM("盒数") AS 总销量, SUM("金额") * 1.0 / NULLIF(SUM("目标"), 0) AS 整体达成率, '
        'COUNT(DISTINCT "终端") AS 去重终端数 FROM workbook',
        "columns": ["累计销售额", "累计目标额", "总销量", "整体达成率", "去重终端数"],
        "rows": [[400000, 420000, 4000, 400000 / 420000, 2]],
    }
    bundle = build_analysis_bundle(table, summary=summary)
    values = {item["label"]: item["value"] for item in bundle["kpis"]}
    assert values == {
        "销售金额": 400000,
        "目标金额": 420000,
        "销售数量": 4000,
        "达成率": pytest.approx(400000 / 420000),
        "去重终端数": 2,
    }
    assert summary["columns"][0] == "累计销售额"
    summary["rows"][0][0] = 999999
    with pytest.raises(ValidationFailed, match="顶部汇总与图表数据不一致"):
        build_analysis_bundle(table, summary=summary)


def test_summary_alias_matching_requires_one_unambiguous_expression():
    table = {
        "sql": "SELECT 城市, SUM(金额) AS 销售金额 FROM workbook GROUP BY 城市",
        "columns": ["城市", "销售金额"],
        "rows": [["北京", 100]],
    }
    for sql, columns, values in [
        ("SELECT AVG(金额) AS 累计销售额 FROM workbook", ["累计销售额"], [100]),
        ("SELECT SUM(金额) AS A, SUM(金额) AS B FROM workbook", ["A", "B"], [100, 100]),
    ]:
        result = build_analysis_bundle(
            table, summary={"sql": sql, "columns": columns, "rows": [values]}
        )
        assert result["kpis"][0]["value"] is None


def test_truncated_queries_require_complete_summary_for_cards(table, metrics, summary):
    table["truncated"] = True
    bundle = build_analysis_bundle(table, metrics=metrics)
    assert all(card["value"] is None for card in bundle["kpis"])
    assert bundle["data"]["query_truncated"] is True
    assert any("截断" in warning for warning in bundle["warnings"])
    with_summary = build_analysis_bundle(table, metrics=metrics, summary=summary)
    assert with_summary["kpis"][0]["value"] == 450


def test_zero_denominator_does_not_produce_infinity():
    table = {
        "columns": ["城市", "销售金额", "目标金额", "达成率"],
        "rows": [["北京", 10, 0, None], ["上海", 20, 0, None]],
    }
    bundle = build_analysis_bundle(table)
    assert bundle["kpis"][0]["value"] == 30
    assert bundle["kpis"][2]["value"] is None
    assert bundle["charts"][0]["option"]["series"][2]["data"] == [None, None]
    json.dumps(bundle, allow_nan=False)


def test_nonadditive_rates_and_terminal_counts_are_not_summed():
    table = {
        "columns": ["城市", "销售金额", "达成率", "终端数"],
        "rows": [["北京", 10, 0.5, 2], ["上海", 20, 1, 3]],
    }
    bundle = build_analysis_bundle(table)
    cards = {item["label"]: item["value"] for item in bundle["kpis"]}
    assert cards == {"销售金额": 30, "达成率": None, "终端数": None}


def test_negative_money_disables_pie_pareto_and_radar(table, metrics):
    table["rows"][0][8] = -100
    table["rows"][0][2] = -100
    bundle = build_analysis_bundle(table, metrics=metrics)
    assert not {"pie", "donut", "pareto", "radar"} & {item["type"] for item in bundle["charts"]}


def test_unknown_columns_are_rejected(table):
    with pytest.raises(ValidationFailed, match="有效数值字段"):
        build_analysis_bundle(table, metrics=[{"column": "虚构金额"}])
    with pytest.raises(ValidationFailed, match="不存在的字段"):
        build_analysis_bundle(table, metrics=[{"column": "达成率", "numerator": "虚构金额"}])


def test_automatic_chart_does_not_use_unrelated_probe_as_summary(table):
    probe = {"columns": ["终端数"], "rows": [[99999]]}
    bundle = automatic_analysis([probe, table], "看月度销售金额和达成率趋势")
    assert bundle["kpis"][0]["value"] == 450
    assert next(card for card in bundle["kpis"] if card["label"] == "终端数")["value"] is None


def test_table_preview_is_bounded_but_retains_full_row_count():
    table = {"columns": ["城市", "销售金额"], "rows": [[f"城市{i}", i] for i in range(1200)]}
    bundle = build_analysis_bundle(table)
    assert len(bundle["data"]["rows"]) == 1000
    assert bundle["data"]["preview_truncated"] is True
    assert bundle["data"]["row_count"] == 1200
    assert bundle["kpis"][0]["value"] == sum(range(1200))


def test_city_month_card_with_many_views_is_transmitted_without_truncation():
    from xiaoying_quick.modules.runs.service import RunService

    table = {
        "columns": ["月份", "城市", "销售金额", "目标金额", "销售数量", "达成率", "毛利额"],
        "rows": [
            [f"2026-{month:02}", f"城市{city}", 100, 200, 10, 0.5, 40]
            for month in range(1, 11)
            for city in range(10)
        ],
    }
    bundle = build_analysis_bundle(table, dimension="月份")
    assert len(json.dumps(bundle, ensure_ascii=False).encode()) > 64 * 1024
    RunService._validate_event("chart.ready", bundle)
    assert len(bundle["details"]["rows"]) == 100


def test_quantity_growth_uses_quantity_instead_of_amount():
    table = {
        "columns": ["城市", "销售金额", "同期金额", "销售数量", "同期数量", "数量同比"],
        "rows": [["北京", 200, 100, 10, 20, -0.5], ["上海", 400, 100, 30, 20, 0.5]],
    }
    bundle = build_analysis_bundle(table)
    assert bundle["kpis"][-1]["value"] == 0
    assert bundle["charts"][0]["option"]["series"][-1]["data"] == [-50, 50]


@pytest.mark.parametrize("value", [45, "45%"])
def test_explicit_percent_scale_and_percent_text_are_normalized_once(value):
    table = {"columns": ["城市", "达成率"], "rows": [["北京", value]]}
    bundle = build_analysis_bundle(table, metrics=[{"column": "达成率", "scale": "percent"}])
    assert bundle["kpis"][0]["value"] == 0.45
    assert bundle["data"]["rows"][0][1] == 0.45


def test_present_chart_reads_only_verified_query_results(table, metrics, summary):
    stored, events = [], []
    records = {
        name: {
            "run_id": "run-1",
            "kind": "tool_result",
            "payload": {"name": "query_db", "ok": True, "payload": source},
        }
        for name, source in (("main-result", table), ("summary-result", summary))
    }
    records["foreign-result"] = {**records["main-result"], "run_id": "run-2"}
    context = AgentToolContext(
        run_id="run-1",
        session_id="session-1",
        actor_id="user-1",
        emit=lambda kind, payload: events.append((kind, payload)),
        extras={
            "query_tables": [table, summary],
            "artifacts": SimpleNamespace(
                append=lambda **kwargs: stored.append(kwargs), get=records.get
            ),
        },
    )
    tool = build_present_chart_tool()
    for invalid_ref in (True, 0, "missing", "foreign-result"):
        invalid = asyncio.run(tool.executor(context, {"query_ref": invalid_ref, "title": "无效"}))
        assert not invalid.ok and not events
    result = asyncio.run(
        tool.executor(
            context,
            {
                "query_ref": "main-result",
                "summary_ref": "summary-result",
                "title": "经营",
                "metrics": metrics,
                "rows": [["伪造", 99999]],
            },
        )
    )
    assert result.ok
    assert events[0][0] == "chart.ready"
    assert events[0][1]["kpis"][0]["value"] == 450
    assert stored[0]["kind"] == "analysis_chart"
