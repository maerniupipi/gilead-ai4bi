from __future__ import annotations

import io

from openpyxl import Workbook

from xiaoying_quick.modules.identity.contracts import Role


def bot_body(**overrides):
    return {
        "name": "区域经营分析",
        "description": "分析区域表现",
        "category": "general",
        "lab_ids": ["actual"],
        **overrides,
    }


def workbook_bytes(headers=("区域", "活跃用户")):
    book = Workbook()
    sheet = book.active
    sheet.title = "行为数据"
    sheet.append(list(headers))
    sheet.append(["华东", 120])
    sheet.append(["华南", 80])
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def test_public_entries_do_not_expose_custom_chatbots_or_file_previews(
    client,
    seed_user,
    auth_headers,
):
    seed_user("admin", role=Role.ADMIN)
    admin = auth_headers("admin")
    created = client.post("/api/v2/admin/chatbots", headers=admin, json=bot_body())
    assert created.status_code == 201
    entries = client.get("/api/v2/chatbots/entrances").json()
    assert {bot["id"] for bot in entries} == {"ddi", "behavior"}
    assert all("workbooks" not in bot and "user_ids" not in bot for bot in entries)
    assert client.get("/api/v2/admin/chatbots").status_code == 401


def test_access_rules_are_enforced_on_catalog_and_new_questions(
    client,
    seed_user,
    auth_headers,
):
    seed_user("admin", role=Role.ADMIN)
    selected = seed_user("selected")
    seed_user("other")
    admin = auth_headers("admin")
    bot = client.post(
        "/api/v2/admin/chatbots",
        headers=admin,
        json=bot_body(
            access="users",
            user_ids=[selected.id],
        ),
    ).json()
    selected_headers, other_headers = auth_headers("selected"), auth_headers("other")
    assert bot["id"] in {
        item["id"]
        for item in client.get(
            "/api/v2/chatbots",
            headers=selected_headers,
        ).json()
    }
    assert bot["id"] not in {
        item["id"]
        for item in client.get(
            "/api/v2/chatbots",
            headers=other_headers,
        ).json()
    }
    assert (
        client.post(
            "/api/v2/chat",
            headers=other_headers,
            json={
                "question": "查询数据",
                "chatbot_id": bot["id"],
            },
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v2/chat/sessions", headers=other_headers, params={"chatbot_id": bot["id"]}
        ).status_code
        == 403
    )
    assert (
        client.post("/api/v2/admin/chatbots", headers=selected_headers, json=bot_body()).status_code
        == 403
    )
    updated = client.put(
        f"/api/v2/admin/chatbots/{bot['id']}", headers=admin, json=bot_body(enabled=False)
    ).json()
    assert updated["enabled"] is False
    assert bot["id"] not in {
        item["id"]
        for item in client.get(
            "/api/v2/chatbots",
            headers=admin,
        ).json()
    }


def test_role_access_and_required_configuration(client, seed_user, auth_headers):
    seed_user("admin", role=Role.ADMIN)
    seed_user("reviewer", role=Role.KNOWLEDGE_REVIEWER)
    seed_user("user")
    admin = auth_headers("admin")
    bot = client.post(
        "/api/v2/admin/chatbots",
        headers=admin,
        json=bot_body(
            access="roles",
            roles=["knowledge_reviewer"],
        ),
    ).json()
    assert bot["id"] in {
        item["id"]
        for item in client.get(
            "/api/v2/chatbots",
            headers=auth_headers("reviewer"),
        ).json()
    }
    assert bot["id"] not in {
        item["id"]
        for item in client.get(
            "/api/v2/chatbots",
            headers=auth_headers("user"),
        ).json()
    }
    for invalid in (bot_body(access="users"), bot_body(access="roles"), bot_body(lab_ids=[])):
        assert client.post("/api/v2/admin/chatbots", headers=admin, json=invalid).status_code == 422


def test_workbook_upload_preview_and_binding_survive_reload(client, seed_user, auth_headers):
    seed_user("admin", role=Role.ADMIN)
    admin = auth_headers("admin")
    response = client.post(
        "/api/v2/admin/chatbot-workbooks",
        headers=admin,
        files={"file": ("业务数据.xlsx", workbook_bytes())},
    )
    assert response.status_code == 201, response.text
    book = response.json()
    assert book["row_count"] == 2
    assert book["sheets"][0]["columns"] == ["区域", "活跃用户"]
    assert book["sheets"][0]["preview"] == [["华东", 120], ["华南", 80]]
    bot = client.post(
        "/api/v2/admin/chatbots",
        headers=admin,
        json=bot_body(
            lab_ids=[],
            workbook_ids=[book["id"]],
        ),
    ).json()
    reloaded = next(
        item
        for item in client.get("/api/v2/admin/chatbots", headers=admin).json()
        if item["id"] == bot["id"]
    )
    assert reloaded["workbooks"][0]["row_count"] == 2
    public = next(
        item
        for item in client.get("/api/v2/chatbots", headers=admin).json()
        if item["id"] == bot["id"]
    )
    assert "sheets" not in public["workbooks"][0]


def test_invalid_workbooks_are_rejected(client, seed_user, auth_headers):
    seed_user("admin", role=Role.ADMIN)
    admin = auth_headers("admin")
    for filename, content in (
        ("data.csv", b"a,b"),
        ("data.xlsx", b"broken"),
        ("data.xlsx", workbook_bytes(("区域", "区域"))),
    ):
        response = client.post(
            "/api/v2/admin/chatbot-workbooks", headers=admin, files={"file": (filename, content)}
        )
        assert response.status_code == 422


def test_session_and_question_history_belong_to_one_chatbot(
    app,
    client,
    seed_user,
    auth_headers,
):
    from tests.api.test_chat import FakeModelRegistry

    app.state.model_registry = FakeModelRegistry()
    seed_user("admin", role=Role.ADMIN)
    admin = auth_headers("admin")
    first = client.post("/api/v2/chat", headers=admin, json={"question": "DDI 问题"}).json()
    second = client.post(
        "/api/v2/chat",
        headers=admin,
        json={
            "question": "行为数据问题",
            "chatbot_id": "behavior",
        },
    ).json()
    assert "session_id" in first and "session_id" in second
    default = client.get("/api/v2/chat/sessions", headers=admin).json()
    behavior = client.get(
        "/api/v2/chat/sessions", headers=admin, params={"chatbot_id": "behavior"}
    ).json()
    assert [item["id"] for item in default] == [first["session_id"]]
    assert [item["id"] for item in behavior] == [second["session_id"]]
    questions = client.get(
        "/api/v2/chat/questions", headers=admin, params={"chatbot_id": "behavior", "limit": 1}
    ).json()
    assert questions["total"] == 1 and questions["items"][0]["content"] == "行为数据问题"
    wrong = client.post(
        "/api/v2/chat",
        headers=admin,
        json={
            "question": "追问",
            "session_id": first["session_id"],
            "chatbot_id": "behavior",
        },
    )
    assert wrong.status_code == 409
