from __future__ import annotations

import pytest

from xiaoying_quick.infrastructure.persistence.repositories.artifacts import (
    SqlAlchemyArtifactRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.runs import SqlAlchemyRunRepository
from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal
from xiaoying_quick.modules.runs.service import RunService

URL = "/api/v2/workspace/boards"


@pytest.fixture
def case(app, seed_user, auth_headers):
    records = {name: seed_user(name) for name in ("owner", "viewer", "editor", "outside")}
    headers = {name: auth_headers(name) for name in records}
    owner = records["owner"]
    principal = AuthenticatedPrincipal(owner.id, owner.username, owner.display_name, owner.role)
    report = {
        "id": "report-owned",
        "revision": 3,
        "title": "季度经营分析",
        "kind": "ddi",
        "date_field": "month",
        "dimension": "region",
        "period": "month",
        "window": "qtd",
        "current_period": "2026-09",
        "metric": "amount",
        "chart_type": "line",
        "filters": {},
        "columns": [{"key": key, "label": key} for key in ("month", "region", "sales", "target")],
        "metrics": {"amount": "sales", "target": "target"},
        "filter_fields": ["region"],
        "visible_columns": ["region", "sales", "target"],
        "rows": [
            {"month": "202607", "region": "华南", "sales": 30, "target": 50},
            {"month": "202608", "region": "华南", "sales": 50, "target": 50},
            {"month": "202609", "region": "华南", "sales": 70, "target": 100},
            {"month": "202609", "region": "华东", "sales": 500, "target": 100},
        ],
        "findings": [{"title": "华东情况", "body": "不能泄漏到只看华南的快照"}],
        "source": {"sql": "PRIVATE SQL", "label": "样例业务数仓", "sample": True},
    }
    with app.state.session_factory() as db:
        runs = RunService(SqlAlchemyRunRepository(db))
        run = runs.create_run(
            principal=principal, question="季度销售分析", session_id=None, idempotency_key=None
        ).run
        SqlAlchemyArtifactRepository(db).append(run_id=run.id, kind="bi_report", payload=report)
        runs.append_event(
            run_id=run.id,
            event_type="chart.ready",
            payload={
                "charts": [
                    {
                        "type": "bar",
                        "label": "区域销售",
                        "option": {
                            "xAxis": {"data": ["华南", "华东"]},
                            "yAxis": {"type": "value"},
                            "series": [{"type": "bar", "data": [150, 500]}],
                        },
                    }
                ],
                "default_type": "bar",
            },
        )
        db.commit()
    return {
        "users": records,
        "headers": headers,
        "run_id": run.id,
        "source": {
            "kind": "report",
            "run_id": run.id,
            "report_id": "report-owned",
            "report_revision": 3,
            "section": "trend",
            "state": {"filters": {"region": "华南"}, "window": "qtd"},
        },
    }


def create(client, case, **overrides):
    response = client.post(
        URL,
        headers=case["headers"]["owner"],
        json={
            "name": "区域经营工作台",
            "description": "季度经营",
            "pin": case["source"],
            **overrides,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_source_snapshot_and_atomic_create(client, case):
    board = create(client, case)
    assert board["my_role"] == "owner" and board["card_count"] == 1
    chart = board["items"][0]["snapshot"]["charts"][0]
    assert chart["option"]["series"][0]["data"] == [30, 50, 70]
    bad = client.post(
        URL,
        headers=case["headers"]["owner"],
        json={
            "name": "不能残留的空看板",
            "pin": {**case["source"], "report_revision": 999},
        },
    )
    assert bad.status_code == 404
    assert len(client.get(URL, headers=case["headers"]["owner"]).json()["items"]) == 1


def test_duplicate_and_normal_answer_chart(client, case):
    board = create(client, case)
    headers = case["headers"]["owner"]
    duplicate = client.post(f"{URL}/{board['id']}/items", headers=headers, json=case["source"])
    assert duplicate.json()["already_added"] is True
    assert duplicate.json()["board"]["card_count"] == 1
    source = {"kind": "answer_chart", "run_id": case["run_id"], "chart_type": "bar"}
    normal = client.post(f"{URL}/{board['id']}/items", headers=headers, json=source).json()
    assert normal["board"]["card_count"] == 2
    assert normal["board"]["items"][1]["snapshot"]["charts"][0]["option"]["series"][0]["data"] == [
        150,
        500,
    ]
    assert (
        client.post(
            f"{URL}/{board['id']}/items",
            headers=headers,
            json={
                **source,
                "chart": {"fake": "client-supplied"},
            },
        ).status_code
        == 422
    )


def test_compound_chart_pin_preserves_kpis_and_both_data_views(client, case, app):
    from xiaoying_quick.application.charts.analysis import build_analysis_bundle

    table = {
        "columns": ["月份", "销售金额", "目标金额", "达成率"],
        "rows": [["2026-09", 100, 200, 0.5], ["2026-10", 300, 400, 0.75]],
    }
    payload = build_analysis_bundle(table, title="医药月度经营", scope="2026年9—10月，元")
    with app.state.session_factory() as db:
        runs = RunService(SqlAlchemyRunRepository(db))
        event = runs.append_event(run_id=case["run_id"], event_type="chart.ready", payload=payload)
        other = build_analysis_bundle(
            {**table, "rows": [["2026-11", 99, 100, 0.99]]}, title="其他范围"
        )
        later = runs.append_event(run_id=case["run_id"], event_type="chart.ready", payload=other)
        db.commit()
    source = {
        "kind": "answer_chart",
        "run_id": case["run_id"],
        "chart_type": "combo",
        "chart_cursor": event.cursor,
    }
    board = create(client, case, pin=source)
    reloaded = client.get(f"{URL}/{board['id']}", headers=case["headers"]["owner"]).json()
    saved = reloaded["items"][0]["snapshot"]
    assert saved["version"] == 2
    assert saved["kpis"] == payload["kpis"]
    assert saved["data"] == payload["data"]
    assert saved["details"] == payload["details"]
    assert saved["scope"] == payload["scope"]
    assert saved["charts"][0]["option"]["series"] == payload["charts"][0]["option"]["series"]
    assert reloaded["items"][0]["source"]["scope"]["label"] == payload["scope"]
    added = client.post(
        f"{URL}/{board['id']}/items",
        headers=case["headers"]["owner"],
        json={**source, "chart_cursor": later.cursor},
    ).json()
    assert added["board"]["card_count"] == 2
    assert added["board"]["items"][1]["snapshot"]["kpis"][0]["value"] == 99
    missing = client.post(
        f"{URL}/{board['id']}/items",
        headers=case["headers"]["owner"],
        json={**source, "chart_cursor": 9999},
    )
    assert missing.status_code == 404


def test_whole_report_shares_only_selected_rows_and_no_sql(client, case):
    board = create(client, case, pin={**case["source"], "section": "report"})
    saved = board["items"][0]["snapshot"]
    assert len(saved["rows"]) == 3
    assert all(row["region"] == "华南" for row in saved["rows"])
    assert saved["findings"] == [] and "sql" not in saved["source"]
    assert saved["read_only"] is True


def test_whole_analysis_preserves_views_and_can_be_pinned_beside_one_chart(client, case, app):
    from xiaoying_quick.application.charts.analysis import build_analysis_bundle

    payload = build_analysis_bundle(
        {"columns": ["城市", "销售金额", "目标金额"],
         "rows": [["北京", 100, 200], ["上海", 300, 400]]},
        title="城市经营分析", scope="2026年10月",
    )
    with app.state.session_factory() as db:
        runs = RunService(SqlAlchemyRunRepository(db))
        event = runs.append_event(run_id=case["run_id"], event_type="chart.ready", payload=payload)
        later = build_analysis_bundle(
            {"columns": ["城市", "销售金额"], "rows": [["北京", 999]]}, title="其他分析",
        )
        runs.append_event(run_id=case["run_id"], event_type="chart.ready", payload=later)
        db.commit()
    source = {
        "kind": "answer_analysis", "run_id": case["run_id"],
        "chart_cursor": event.cursor, "chart_type": "horizontal_bar",
    }
    board = create(client, case, pin=source)
    tile = board["items"][0]
    saved = tile["snapshot"]
    assert tile["kind"] == "analysis" and tile["width"] == "full"
    assert tile["title"] == payload["title"]
    assert saved["default_type"] == "horizontal_bar"
    assert [chart["type"] for chart in saved["charts"]] == [
        chart["type"] for chart in payload["charts"]
    ]
    assert len(saved["charts"]) > 1
    for key in ("title", "scope", "kpis", "metrics", "data", "details", "warnings"):
        assert saved[key] == payload[key]
    assert tile["source"]["chart_cursor"] == event.cursor
    headers = case["headers"]["owner"]
    added = client.post(
        f"{URL}/{board['id']}/items", headers=headers,
        json={**source, "kind": "answer_chart"},
    ).json()
    assert added["board"]["card_count"] == 2
    assert added["board"]["items"][1]["kind"] == "chart"
    assert len(added["board"]["items"][1]["snapshot"]["charts"]) == 1
    duplicate = client.post(f"{URL}/{board['id']}/items", headers=headers, json=source).json()
    assert duplicate["already_added"] is True
    reloaded = client.get(f"{URL}/{board['id']}", headers=headers).json()
    assert reloaded["items"][0]["snapshot"] == saved
    assert client.post(
        URL, headers=case["headers"]["outside"], json={"name": "越权", "pin": source},
    ).status_code in (403, 404)
    assert client.post(
        f"{URL}/{board['id']}/items", headers=headers,
        json={**source, "charts": [{"fake": "client-supplied"}]},
    ).status_code == 422


def test_answer_tables_can_be_pinned_independently_with_server_owned_data(client, case, app):
    from xiaoying_quick.infrastructure.persistence.models.chat import (
        ChatMessageModel,
        ChatSessionModel,
    )

    answer = (
        "## 核心指标\n\n| 指标 | 数值 |\n|---|---|\n| 销售金额 | 100 元 |\n| 达成率 | 50% |"
        "\n\n## 城市\n\n| 城市 | 金额 |\n|---|---|\n| 北京 | 100 |"
    )
    with app.state.session_factory() as db:
        db.add(
            ChatSessionModel(
                id="session-tables", owner_id=case["users"]["owner"].id, title="问答表格", version=1
            )
        )
        db.flush()
        db.add(
            ChatMessageModel(
                id="message-tables",
                session_id="session-tables",
                run_id=case["run_id"],
                role="assistant",
                content=answer,
                fact_ids=[],
            )
        )
        db.commit()
    source = {"kind": "answer_table", "run_id": case["run_id"], "table_index": 0}
    board = create(client, case, pin=source)
    item = board["items"][0]
    assert item["kind"] == "table" and item["width"] == "full"
    assert item["title"] == "核心指标"
    assert item["snapshot"]["data"]["rows"] == [["销售金额", "100 元"], ["达成率", "50%"]]
    path = f"{URL}/{board['id']}/items"
    headers = case["headers"]["owner"]
    assert client.post(path, headers=headers, json=source).json()["already_added"] is True
    second = client.post(path, headers=headers, json={**source, "table_index": 1}).json()
    assert second["board"]["card_count"] == 2
    assert second["board"]["items"][1]["snapshot"]["data"]["rows"] == [["北京", "100"]]
    assert client.post(path, headers=headers, json={**source, "table_index": 99}).status_code == 404
    assert (
        client.post(path, headers=headers, json={**source, "rows": [["fake", 999]]}).status_code
        == 422
    )
    outside = client.post(
        URL, headers=case["headers"]["outside"], json={"name": "越权", "pin": source}
    )
    assert outside.status_code == 403


def test_chart_and_query_tables_are_distinct_pinnable_snapshots(client, case, app):
    from xiaoying_quick.application.charts.analysis import build_analysis_bundle

    table = {
        "columns": ["月份", "城市", "销售金额"],
        "rows": [
            ["2026-09", "北京", 100],
            ["2026-09", "上海", 200],
            ["2026-10", "北京", 300],
            ["2026-10", "上海", 400],
        ],
    }
    payload = build_analysis_bundle(table, dimension="月份")
    with app.state.session_factory() as db:
        runs = RunService(SqlAlchemyRunRepository(db))
        event = runs.append_event(run_id=case["run_id"], event_type="chart.ready", payload=payload)
        db.commit()
    source = {
        "kind": "chart_table",
        "run_id": case["run_id"],
        "chart_type": "combo",
        "chart_cursor": event.cursor,
    }
    board = create(client, case, pin=source)
    assert board["items"][0]["kind"] == "table"
    assert board["items"][0]["snapshot"]["data"] == payload["data"]
    pinned = client.post(
        f"{URL}/{board['id']}/items",
        headers=case["headers"]["owner"],
        json={**source, "table_view": "details"},
    ).json()["board"]
    assert pinned["card_count"] == 2
    assert pinned["items"][1]["snapshot"]["data"] == payload["details"]
    reloaded = client.get(f"{URL}/{board['id']}", headers=case["headers"]["owner"]).json()
    assert reloaded["items"][0]["snapshot"]["data"]["rows"] == [["2026-09", 300], ["2026-10", 700]]


def test_historical_chart_table_can_be_pinned_without_saved_data(client, case):
    source = {"kind": "chart_table", "run_id": case["run_id"], "chart_type": "bar"}
    board = create(client, case, pin=source)
    assert board["items"][0]["snapshot"]["data"]["rows"] == [["华南", 150], ["华东", 500]]


def test_viewer_editor_and_revocation_are_enforced(client, case):
    board = create(client, case)
    path = f"{URL}/{board['id']}"
    headers = case["headers"]
    assert client.get(path, headers=headers["outside"]).status_code == 404
    assert client.get(URL, headers=headers["viewer"]).json()["items"] == []
    shared = client.put(
        path + "/access",
        headers=headers["owner"],
        json={
            "version": board["version"],
            "members": [
                {"user_id": case["users"]["viewer"].id, "role": "viewer"},
                {"user_id": case["users"]["editor"].id, "role": "editor"},
            ],
        },
    ).json()
    assert client.get(path, headers=headers["viewer"]).json()["my_role"] == "viewer"
    assert client.get(URL, headers=headers["viewer"]).json()["items"][0]["id"] == board["id"]
    assert (
        client.post(path + "/items", headers=headers["viewer"], json=case["source"]).status_code
        == 403
    )
    layout = {
        "version": shared["version"],
        "items": [
            {
                "id": shared["items"][0]["id"],
                "title": "编辑者改名",
                "width": "full",
            }
        ],
    }
    assert client.put(path + "/layout", headers=headers["viewer"], json=layout).status_code == 403
    edited = client.put(path + "/layout", headers=headers["editor"], json=layout)
    assert edited.status_code == 200 and edited.json()["items"][0]["title"] == "编辑者改名"
    assert client.get(path + "/access", headers=headers["editor"]).status_code == 403
    assert client.delete(path, headers=headers["editor"]).status_code == 403
    assert (
        client.put(
            path + "/access",
            headers=headers["editor"],
            json={
                "version": edited.json()["version"],
                "members": [],
            },
        ).status_code
        == 403
    )
    revoked = client.put(
        path + "/access",
        headers=headers["owner"],
        json={
            "version": edited.json()["version"],
            "members": [],
        },
    )
    assert revoked.status_code == 200
    assert client.get(path, headers=headers["viewer"]).status_code == 404
    assert client.get(path, headers=headers["editor"]).status_code == 404


def test_source_ownership_and_version_conflicts(client, case):
    headers = case["headers"]
    assert (
        client.post(
            URL,
            headers=headers["outside"],
            json={
                "name": "越权收藏",
                "pin": case["source"],
            },
        ).status_code
        == 403
    )
    board = create(client, case)
    path = f"{URL}/{board['id']}"
    edited = client.put(
        path,
        headers=headers["owner"],
        json={
            "name": "新名称",
            "description": "已修改",
            "version": board["version"],
        },
    )
    assert edited.status_code == 200
    assert (
        client.put(
            path + "/layout",
            headers=headers["owner"],
            json={
                "items": [],
                "version": board["version"],
            },
        ).status_code
        == 409
    )
    assert client.get(path, headers=headers["owner"]).json()["card_count"] == 1


def test_bad_filters_and_unknown_members_are_rejected(client, case):
    headers = case["headers"]["owner"]
    for state in (
        {"filters": {"unknown": "华南"}},
        {"filters": {"region": "无此区域"}},
        {"window": "invalid"},
        {"filters": []},
        {"dimension": []},
        {"window": {}},
        {"visible_columns": [{}]},
    ):
        assert (
            client.post(
                URL,
                headers=headers,
                json={
                    "name": "错误",
                    "pin": {
                        **case["source"],
                        "state": state,
                    },
                },
            ).status_code
            == 422
        )
    board = create(client, case)
    assert (
        client.put(
            f"{URL}/{board['id']}/access",
            headers=headers,
            json={
                "version": board["version"],
                "members": [{"user_id": "unknown", "role": "viewer"}],
            },
        ).status_code
        == 422
    )
    assert client.get(URL).status_code == 401


def test_editor_can_add_own_answer_but_cannot_repin_someone_elses_run(app, client, case):
    board = create(client, case)
    headers = case["headers"]
    path = f"{URL}/{board['id']}"
    assert (
        client.put(
            path + "/access",
            headers=headers["owner"],
            json={
                "version": board["version"],
                "members": [
                    {"user_id": case["users"]["editor"].id, "role": "editor"},
                ],
            },
        ).status_code
        == 200
    )
    response = client.post(
        "/api/v2/runs", headers=headers["editor"], json={"question": "编辑者的问答"}
    )
    run_id = response.json()["run"]["id"]
    with app.state.session_factory() as db:
        RunService(SqlAlchemyRunRepository(db)).append_event(
            run_id=run_id,
            event_type="chart.ready",
            payload={
                "charts": [
                    {
                        "type": "bar",
                        "label": "编辑者图表",
                        "option": {
                            "series": [{"type": "bar", "data": [10, 20]}],
                        },
                    },
                ]
            },
        )
        db.commit()
    result = client.post(
        path + "/items",
        headers=headers["editor"],
        json={
            "kind": "answer_chart",
            "run_id": run_id,
            "chart_type": "bar",
        },
    )
    assert result.status_code == 200 and result.json()["board"]["card_count"] == 2
    assert (
        client.post(path + "/items", headers=headers["editor"], json=case["source"]).status_code
        == 403
    )


def test_owner_can_delete_board_and_revoke_all_saved_content(client, case):
    board = create(client, case)
    path = f"{URL}/{board['id']}"
    assert (
        client.put(
            path + "/access",
            headers=case["headers"]["owner"],
            json={
                "version": board["version"],
                "members": [
                    {"user_id": case["users"]["viewer"].id, "role": "viewer"},
                ],
            },
        ).status_code
        == 200
    )
    assert client.delete(path, headers=case["headers"]["owner"]).status_code == 204
    assert client.get(path, headers=case["headers"]["owner"]).status_code == 404
    assert client.get(path, headers=case["headers"]["viewer"]).status_code == 404
    assert client.get(URL, headers=case["headers"]["viewer"]).json()["items"] == []
