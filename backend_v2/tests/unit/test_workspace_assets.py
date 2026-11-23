from copy import deepcopy

import pytest

from xiaoying_quick.application.workspace_assets import report_widget, scoped_report


def sample():
    return {
        "id": "report",
        "revision": 1,
        "title": "经营",
        "date_field": "month",
        "dimension": "region",
        "period": "month",
        "window": "period",
        "current_period": "2026-09",
        "metric": "amount",
        "chart_type": "bar",
        "columns": [{"key": k} for k in ["month", "region", "sales", "target"]],
        "metrics": {"amount": "sales", "target": "target"},
        "filters": {},
        "source": {"sql": "private"},
        "findings": [],
        "rows": [
            {"month": "2026-01-01", "region": "华南", "sales": 10, "target": 100},
            {"month": "2026-07-01", "region": "华南", "sales": 20, "target": 100},
            {"month": "2026-09-01", "region": "华南", "sales": 100, "target": 1000},
            {"month": "2026-09-01", "region": "华东", "sales": 80, "target": 100},
            {"month": "2025-09-01", "region": "华南", "sales": 99, "target": 100},
        ],
    }


def test_snapshot_scope_cannot_expand_outside_selected_period_and_filters():
    report = sample()
    original = deepcopy(report)
    for window, expected in [("period", 100), ("qtd", 120), ("ytd", 130)]:
        snapshot = scoped_report(report, {"window": window, "filters": {"region": "华南"}})
        assert sum(row["sales"] for row in snapshot["rows"]) == expected
        assert "sql" not in snapshot["source"]
    assert report == original


def test_kpis_use_ratio_of_sums_and_expose_real_targets_and_gaps():
    report = scoped_report(sample(), {"window": "ytd"})
    kind, snapshot, _ = report_widget(report, "kpis")
    values = snapshot["metrics"]
    assert kind == "kpi" and values[0]["value"] == 210
    assert values[1]["value"] == pytest.approx(210 / 1300 * 100)
    assert values[2]["value"] == 1300
    assert values[3]["value"] == -1090


def test_trend_and_signed_contribution_reconcile_to_the_same_filtered_total():
    report = scoped_report(sample(), {"window": "ytd"})
    _, trend, _ = report_widget(report, "trend")
    assert sum(trend["charts"][0]["option"]["series"][0]["data"]) == 210
    _, contribution, _ = report_widget(report, "contribution")
    points = contribution["charts"][0]["option"]["series"][0]["data"]
    assert sum(point["value"] for point in points) == -1090
