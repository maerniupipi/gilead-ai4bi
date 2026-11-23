from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from xiaoying_quick.modules.agent.catalog import AGENT_BY_ID
from xiaoying_quick.modules.identity.contracts import Role, UserRecord


def test_admin_can_list_tools_and_reconfigure_agents(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("admin", role=Role.ADMIN)
    headers = auth_headers("admin")

    tools = client.get("/api/v2/admin/tools", headers=headers)
    assert tools.status_code == 200
    names = [item["name"] for item in tools.json()["items"]]
    assert "ask_lab" in names
    assert "query_db" in names
    assert "inspect_schema" in names
    assert "field_recall" in names

    agents = client.get("/api/v2/admin/agents", headers=headers)
    assert agents.status_code == 200
    by_id = {item["id"]: item for item in agents.json()["items"]}
    assert by_id["main"]["required"] is True
    assert "query_db" in by_id["main"]["toolNames"]
    assert by_id["bailian"]["name"] == "召回智能体"
    assert "generate_sql" in by_id["lab_sql"]["toolNames"]
    for agent_id, spec in AGENT_BY_ID.items():
        assert by_id[agent_id]["systemPrompt"] == spec.system_prompt

    updated = client.patch(
        "/api/v2/admin/agents/main",
        headers=headers,
        json={
            "tool_names": ["query_db", "ask_user", "knowledge_search"],
            "agent_names": ["lab_sql"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["toolNames"] == ["query_db", "ask_user", "knowledge_search"]
    assert updated.json()["agentNames"] == ["lab_sql"]

    denied = client.patch(
        "/api/v2/admin/agents/main",
        headers=headers,
        json={"tool_names": ["nope"]},
    )
    assert denied.status_code == 422
    assert denied.json()["error"]["code"] == "VALIDATION_FAILED"

    locked = client.patch(
        "/api/v2/admin/agents/main",
        headers=headers,
        json={"system_prompt": "not allowed"},
    )
    assert locked.status_code == 422

    recalled = client.patch(
        "/api/v2/admin/agents/bailian",
        headers=headers,
        json={"extras": {"recall": {"probe_values": False, "max_values": 8}}},
    )
    assert recalled.status_code == 200, recalled.text
    assert recalled.json()["extras"]["recall"]["probe_values"] is False
    assert recalled.json()["extras"]["recall"]["max_values"] == 8


def test_non_admin_cannot_read_agent_catalog(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("ordinary")
    response = client.get("/api/v2/admin/agents", headers=auth_headers("ordinary"))
    assert response.status_code == 403
