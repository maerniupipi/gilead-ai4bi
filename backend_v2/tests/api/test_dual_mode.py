from __future__ import annotations

import pytest

from tests.api.test_chatbots import workbook_bytes
from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.chatbots import ChatbotStore
from xiaoying_quick.modules.identity.contracts import Role
from xiaoying_quick.shared.errors import NotFound


def test_delivery_defaults_to_both_database_and_personal_xlsx():
    assert Settings(_env_file=None).chatbot_mode == "dual"


def test_dual_catalog_keeps_private_uploads_and_admin_configuration_separate(
    settings, client, seed_user, auth_headers,
):
    settings.chatbot_mode = "dual"
    seed_user("owner")
    seed_user("other")
    seed_user("admin", role=Role.ADMIN)
    owner, other, admin = (auth_headers(name) for name in ("owner", "other", "admin"))
    public = client.get("/api/v2/chatbots/entrances").json()
    assert {item["id"] for item in public} == {"ddi", "xlsx"}
    assert all("workbooks" not in item for item in public)
    uploaded = client.post(
        "/api/v2/chatbots/xlsx/workbooks", headers=owner,
        files={"file": ("private.xlsx", workbook_bytes())},
    )
    assert uploaded.status_code == 201
    book = uploaded.json()
    catalogs = {}
    for name, headers in (("owner", owner), ("other", other), ("admin", admin)):
        catalogs[name] = {
            bot["id"]: bot for bot in client.get("/api/v2/chatbots", headers=headers).json()
        }
        assert set(catalogs[name]) == {"ddi", "xlsx"}
        assert catalogs[name]["ddi"]["lab_ids"] == ["actual"]
        assert catalogs[name]["ddi"]["workbooks"] == []
    assert catalogs["owner"]["xlsx"]["workbook_ids"] == [book["id"]]
    assert catalogs["other"]["xlsx"]["workbooks"] == []
    assert catalogs["admin"]["xlsx"]["workbooks"] == []
    assert client.put(
        "/api/v2/admin/chatbots/xlsx", headers=admin,
        json={"name": "share", "lab_ids": ["actual"]},
    ).status_code == 422
    assert client.get("/api/v2/chatbots", headers=owner).json()[1]["personal_uploads"]


def test_switching_between_single_dual_and_legacy_modes_preserves_workbooks(tmp_path):
    path = tmp_path / "chatbots.sqlite3"
    single = ChatbotStore(path, xlsx_only=True)
    book = single.upload_personal_workbook("xlsx", "owner", "private.xlsx", workbook_bytes())
    dual = ChatbotStore(path, mode="dual")
    assert {bot["id"] for bot in dual.list()} == {"ddi", "xlsx"}
    assert [item["id"] for item in dual.personal_workbooks("xlsx", "owner")] == [book["id"]]
    legacy = ChatbotStore(path, mode="full")
    assert legacy.get("behavior")["workbook_ids"] == ["workbook_behavior_sample"]
    dual = ChatbotStore(path, mode="dual")
    assert {bot["id"] for bot in dual.list()} == {"ddi", "xlsx"}
    with pytest.raises(NotFound):
        dual.get("behavior")
    single = ChatbotStore(path, mode="xlsx")
    assert [bot["id"] for bot in single.list()] == ["xlsx"]
    assert single.workbook(book["id"])["owner_id"] == "owner"
