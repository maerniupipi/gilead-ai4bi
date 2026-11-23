import asyncio
import json
from decimal import Decimal

import pytest

from xiaoying_quick.application.agent_run.report_tool import (
    build_render_report_tool,
    make_report,
    report_summary,
)
from xiaoying_quick.modules.agent import AgentToolContext


def table():
    return {
        "columns": ["date", "region", "province", "amount", "target", "prior"],
        "rows": [
            ["2026-09-01", "华东", "江苏", Decimal("80.25"), 40, 70],
            ["2026-09-01", "华南", "广东", 120, 160, None],
        ],
        "sql": "SELECT date, region, province, amount, target, prior FROM sales_target",
        "mock_enabled": True,
    }


def test_report_uses_verified_values_and_keeps_missing_comparisons():
    report = make_report(
        table=table(),
        previous=None,
        design={
            "metrics": {"amount": "amount", "target": "target", "prior": "prior"},
            "dimension": "region",
            "date_field": "date",
            "filter_fields": ["region"],
        },
    )
    assert report["rows"][0]["amount"] == 80.25
    assert report["rows"][1]["prior"] is None
    assert report["source"]["demo"] is True
    assert report["source"]["sql"] == table()["sql"]
    summary = report_summary(report)
    assert summary["实际"] == 200.25
    assert summary["达成率%"] == 100.125


def test_design_cannot_inject_rows_or_invent_new_source_columns():
    with pytest.raises(ValueError, match="rows"):
        make_report(table=table(), previous=None, design={"rows": [{"amount": 999}]})
    with pytest.raises(ValueError, match="先补查"):
        make_report(table=table(), previous=None, design={"visible_columns": ["gross_margin"]})


def test_revision_preserves_data_identity_and_current_filter_but_accepts_explicit_edits():
    first = make_report(table=table(), previous=None, design={"dimension": "region"})
    second = make_report(
        table=None,
        previous=first,
        report_context={"report_id": first["id"], "filters": {"region": "华东"}},
        design={"visible_columns": ["region", "province", "amount", "_share"], "chart_type": "bar"},
    )
    assert second["id"] == first["id"]
    assert second["revision"] == 2
    assert second["rows"] == first["rows"]
    assert second["filters"] == {"region": "华东"}
    assert second["visible_columns"][-1] == "_share"
    assert second["chart_type"] == "bar"
    third = make_report(
        table=None,
        previous=second,
        design={"filters": {"region": "华南"}},
        report_context={"report_id": first["id"], "filters": {"region": "华东"}},
    )
    assert third["filters"] == {"region": "华南"}


def test_context_for_an_unrelated_report_does_not_override_filters():
    first = make_report(table=table(), previous=None, design={"dimension": "region"})
    revised = make_report(
        table=None,
        previous=first,
        design={},
        report_context={"report_id": "unrelated", "filters": {"region": "华东"}},
    )
    assert revised["filters"] == {}


def test_missing_data_is_explicit_and_truncation_is_preserved():
    with pytest.raises(ValueError, match="先query_db"):
        make_report(table=None, previous=None, design={})
    source = {**table(), "truncated": True}
    report = make_report(table=source, previous=None, design={})
    assert report["source"]["truncated"] is True


def test_complete_multidimensional_report_is_not_rejected_at_220_kilobytes():
    grid = table()
    grid["rows"] = grid["rows"] * 1000
    report = make_report(table=grid, previous=None, design={"dimension": "region"})
    assert len(report["rows"]) == 2000
    assert len(json.dumps(report, ensure_ascii=False).encode()) > 220_000
    assert report["source"]["truncated"] is False


def test_summary_reconciles_group_deficits_and_uses_the_same_current_filters():
    report = make_report(
        table=table(),
        previous=None,
        design={
            "dimension": "region",
            "filter_fields": ["region"],
            "metrics": {"amount": "amount", "target": "target"},
        },
    )
    summary = report_summary(report)
    groups = summary["分组核验"]["region"]
    assert sum(group["目标差额"] for group in groups) == 0.25
    report["filters"] = {"region": "华南"}
    summary = report_summary(report)
    assert summary["实际"] == 120
    assert summary["分组核验"]["region"][0]["达成率%"] == 75


class MemoryArtifacts:
    def __init__(self):
        self.saved = []

    def latest(self, **kwargs):
        return None

    def append(self, **kwargs):
        self.saved.append(kwargs)


def test_report_finds_matching_verified_grid_after_a_metadata_probe():
    artifacts = MemoryArtifacts()
    emitted = []
    context = AgentToolContext(
        run_id="run",
        session_id="session",
        actor_id="admin",
        emit=lambda *args: emitted.append(args),
        extras={
            "artifacts": artifacts,
            "previous_report": None,
            "report_context": None,
            "report_data_provenance": {"sample": True},
            "query_tables": [{"columns": ["max_month"], "rows": [[202609]]}, table()],
        },
    )
    result = asyncio.run(
        build_render_report_tool().executor(
            context,
            {
                "query_index": 0,
                "design": {
                    "date_field": "date",
                    "dimension": "region",
                    "metrics": {"amount": "amount"},
                },
            },
        )
    )
    assert result.ok
    report = artifacts.saved[0]["payload"]
    assert report["rows"][0]["amount"] == 80.25
    assert report["source"]["sample"] is True
    assert emitted[0][0] == "report.ready"


def test_missing_report_fields_return_query_inventory_without_mixing_grains():
    artifacts = MemoryArtifacts()
    context = AgentToolContext(
        run_id="run",
        session_id="session",
        actor_id="admin",
        emit=lambda *_: None,
        extras={
            "artifacts": artifacts,
            "previous_report": None,
            "report_context": None,
            "query_tables": [table(), {"columns": ["gross_margin"], "rows": [[0.9]]}],
        },
    )
    result = asyncio.run(
        build_render_report_tool().executor(
            context,
            {
                "design": {
                    "dimension": "region",
                    "metrics": {"amount": "amount"},
                    "visible_columns": ["gross_margin"],
                }
            },
        )
    )
    assert result.ok is False
    assert "query_index" in result.output and "gross_margin" in result.output
    assert "禁止拼接" in result.output
    assert artifacts.saved == []


@pytest.mark.parametrize("new_report", [False, True])
def test_refreshing_data_keeps_the_edited_report_identity_unless_explicitly_new(new_report):
    artifacts = MemoryArtifacts()
    previous = make_report(table=table(), previous=None, design={"dimension": "region"})
    fresh = table()
    fresh["rows"][0][3] = 99
    context = AgentToolContext(
        run_id="run",
        session_id="session",
        actor_id="admin",
        emit=lambda *_: None,
        extras={
            "artifacts": artifacts,
            "previous_report": previous,
            "report_context": {"report_id": previous["id"]},
            "report_data_provenance": {},
            "query_tables": [fresh],
        },
    )
    result = asyncio.run(
        build_render_report_tool().executor(
            context,
            {
                "design": {"dimension": "region"},
                "reuse_previous": False,
                "new_report": new_report,
            },
        )
    )
    assert result.ok
    report = artifacts.saved[0]["payload"]
    assert (report["id"] == previous["id"]) is not new_report
    assert report["revision"] == (1 if new_report else 2)
    assert report["rows"][0]["amount"] == 99


def test_refresh_cannot_silently_discard_a_previous_brand_filter():
    original = table()
    original["columns"].append("brand")
    for row in original["rows"]:
        row.append("品牌A")
    previous = make_report(
        table=original,
        previous=None,
        design={
            "dimension": "region",
            "filter_fields": ["region", "brand"],
        },
    )
    artifacts = MemoryArtifacts()
    context = AgentToolContext(
        run_id="run",
        session_id="session",
        actor_id="admin",
        emit=lambda *_: None,
        extras={
            "artifacts": artifacts,
            "previous_report": previous,
            "report_context": {"report_id": previous["id"]},
            "query_tables": [table()],
        },
    )
    result = asyncio.run(
        build_render_report_tool().executor(
            context,
            {
                "design": {
                    "dimension": "region",
                    "filter_fields": ["region", "province"],
                }
            },
        )
    )
    assert result.ok is False and "brand" in result.output
    assert "missing_fields" in result.output
    assert artifacts.saved == []
