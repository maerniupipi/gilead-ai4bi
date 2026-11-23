"""A completed answer can become an editable, reusable skill, under admin permissions."""

import json
from types import SimpleNamespace

from xiaoying_quick.infrastructure.persistence.base import utc_now
from xiaoying_quick.infrastructure.persistence.models.runs import RunModel
from xiaoying_quick.infrastructure.persistence.repositories.artifacts import (
    SqlAlchemyArtifactRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.runs import SqlAlchemyRunRepository
from xiaoying_quick.infrastructure.persistence.session import session_scope
from xiaoying_quick.modules.identity.contracts import Role


class DraftClient:
    def __init__(self):
        self.request = None
        self.closed = False

    async def complete_json(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(
            payload={
                "name": "区域目标缺口分析",
                "blurb": "按区域、渠道与品牌验证目标缺口，并生成交互报告。",
                "prompt": "# 区域目标缺口分析\n"
                "时间、区域、品牌参数从本次问题获取。先核验总体，再下钻渠道和品牌。"
                "缺口贡献用实际减目标。调用render_report呈现KPI、对比与明细；"
                "继承当前筛选。数值重新查询，不能复制历史结论。",
            }
        )

    async def aclose(self):
        self.closed = True


def completed_run(client, app, headers):
    response = client.post(
        "/api/v2/runs", json={"question": "分析最新月份区域缺口"}, headers=headers
    )
    run_id = response.json()["run"]["id"]
    with session_scope(app.state.session_factory) as db:
        db.get(RunModel, run_id).status = "completed"
        SqlAlchemyRunRepository(db).append_event(
            run_id,
            event_type="agent.done",
            payload={"answer": "华南缺口集中，渠道差额已复核。"},
            now=utc_now(),
        )
        SqlAlchemyArtifactRepository(db).append(
            run_id=run_id,
            kind="bi_report",
            payload={
                "kind": "insight",
                "metrics": {"amount": "actual", "target": "target"},
                "columns": [{"key": "region", "label": "大区"}],
                "dimension": "region",
                "rows": [{"region": "华南", "private_row_marker": 12345}],
            },
        )
    return run_id


def test_draft_is_reviewable_and_saving_makes_it_mountable(client, app, seed_user, auth_headers):
    seed_user("editor", role=Role.ADMIN)
    headers = auth_headers("editor")
    run_id = completed_run(client, app, headers)
    llm = DraftClient()
    app.state.model_registry = SimpleNamespace(active_client=lambda: llm)
    before = client.get("/api/v2/admin/skill-packs", headers=headers).json()["items"]
    response = client.post(f"/api/v2/admin/skill-packs/from-run/{run_id}/draft", headers=headers)
    assert response.status_code == 200, response.text
    assert llm.closed
    assert "private_row_marker" not in llm.request["user_prompt"]
    context = json.loads(llm.request["user_prompt"])
    assert context["report_design"]["metrics"]["amount"] == "actual"
    assert len(client.get("/api/v2/admin/skill-packs", headers=headers).json()["items"]) == len(
        before
    )
    draft = response.json()["draft"]
    draft["name"] = "区域缺口与渠道归因"
    saved = client.post(
        "/api/v2/admin/skill-packs", json={**draft, "type": "data_insight"}, headers=headers
    )
    assert saved.status_code == 201
    mounted = client.get("/api/v2/skill-packs/mountable", headers=headers).json()["items"]
    assert any(
        item["id"] == saved.json()["item"]["id"] and item["name"] == draft["name"]
        for item in mounted
    )


def test_draft_rejects_unfinished_answers_and_non_admins(client, app, seed_user, auth_headers):
    seed_user("editor", role=Role.ADMIN)
    seed_user("viewer")
    headers = auth_headers("editor")
    response = client.post("/api/v2/runs", json={"question": "待完成分析"}, headers=headers)
    run_id = response.json()["run"]["id"]
    path = f"/api/v2/admin/skill-packs/from-run/{run_id}/draft"
    assert client.post(path, headers=headers).status_code == 409
    assert client.post(path, headers=auth_headers("viewer")).status_code == 403
    assert client.post(path).status_code == 401
