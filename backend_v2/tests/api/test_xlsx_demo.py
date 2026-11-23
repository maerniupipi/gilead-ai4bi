from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor

import pytest
from openpyxl import Workbook

from tests.api.test_chatbots import workbook_bytes
from xiaoying_quick.infrastructure.chatbots import MAX_UPLOAD_BYTES, ChatbotStore
from xiaoying_quick.infrastructure.workbook_lab import WorkbookLab
from xiaoying_quick.shared.errors import ValidationFailed


def xlsx_with_sheets(count):
    book = Workbook()
    book.active.append(["区域", "金额"])
    book.active.append(["华东", 120])
    for index in range(count - 1):
        book.create_sheet(f"空白{index}")
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def test_single_xlsx_bot_hides_previous_sources_and_allows_empty_upload_state(
    settings, client, seed_user, auth_headers,
):
    seed_user("demo")
    ChatbotStore(settings.secret_store_path.parent / "chatbots.sqlite3")
    settings.chatbot_mode = "xlsx"
    entries = client.get("/api/v2/chatbots/entrances").json()
    assert [bot["id"] for bot in entries] == ["xlsx"]
    assert entries[0]["personal_uploads"] is True
    assert "workbooks" not in entries[0]
    headers = auth_headers("demo")
    bots = client.get("/api/v2/chatbots", headers=headers).json()
    assert [bot["id"] for bot in bots] == ["xlsx"]
    assert bots[0]["workbooks"] == []
    assert bots[0]["upload_limits"] == {"files": 10, "bytes": MAX_UPLOAD_BYTES, "sheets": 5}
    rejected = client.post(
        "/api/v2/chat", headers=headers, json={"question": "统计数据", "chatbot_id": "xlsx"},
    )
    assert rejected.status_code == 422
    assert "上传" in rejected.text
    assert client.post(
        "/api/v2/chat", headers=headers, json={"question": "统计数据", "chatbot_id": "ddi"},
    ).status_code == 404


def test_personal_upload_preview_persistence_and_ownership(
    settings, client, seed_user, auth_headers,
):
    settings.chatbot_mode = "xlsx"
    owner = seed_user("owner")
    seed_user("other")
    headers = auth_headers("owner")
    other = auth_headers("other")
    path = "/api/v2/chatbots/xlsx/workbooks"
    assert client.get(path).status_code == 401
    assert client.post(path, files={"file": ("data.xlsx", workbook_bytes())}).status_code == 401
    response = client.post(path, headers=headers, files={"file": ("业务.xlsx", workbook_bytes())})
    assert response.status_code == 201, response.text
    book = response.json()
    assert book["sheets"][0]["preview"] == [["华东", 120], ["华南", 80]]
    assert "owner_id" not in book
    assert client.get(path, headers=headers).json()["items"] == [book]
    assert client.get(path, headers=other).json()["items"] == []
    assert client.get("/api/v2/chatbots", headers=other).json()[0]["workbook_ids"] == []
    assert client.delete(f"{path}/{book['id']}", headers=other).status_code == 404
    assert client.delete(f"{path}/{book['id']}").status_code == 401
    store = ChatbotStore(settings.secret_store_path.parent / "chatbots.sqlite3", xlsx_only=True)
    assert [item["id"] for item in store.personal_workbooks("xlsx", owner.id)] == [book["id"]]
    lab = WorkbookLab(
        store.personal_workbooks("xlsx", owner.id), lambda: None, None,
        lambda *_: pytest.fail("external source"),
    )
    table = book["sheets"][0]["table"]
    assert lab.execute(f'SELECT SUM("活跃用户") FROM "{table}"', 10)[1] == [[200.0]]
    assert client.delete(f"{path}/{book['id']}", headers=headers).status_code == 204
    assert client.get(path, headers=headers).json()["items"] == []


def test_upload_limits_include_blank_sheets_and_oversized_files(
    settings, client, seed_user, auth_headers,
):
    settings.chatbot_mode = "xlsx"
    seed_user("demo")
    headers = auth_headers("demo")
    path = "/api/v2/chatbots/xlsx/workbooks"
    assert client.post(
        path, headers=headers, files={"file": ("five.xlsx", xlsx_with_sheets(5))},
    ).status_code == 201
    for filename, data, message in (
        ("six.xlsx", xlsx_with_sheets(6), "5 个 sheet"),
        ("large.xlsx", b"0" * (MAX_UPLOAD_BYTES + 1), "10 MB"),
        ("data.csv", b"a,b", ".xlsx"),
        ("invalid.xlsx", b"not an xlsx", "无法读取"),
    ):
        response = client.post(path, headers=headers, files={"file": (filename, data)})
        assert response.status_code == 422, response.text
        assert message in response.text
    assert len(client.get(path, headers=headers).json()["items"]) == 1


def test_ten_file_quota_and_removal_frees_a_slot(settings, client, seed_user, auth_headers):
    settings.chatbot_mode = "xlsx"
    seed_user("demo")
    headers = auth_headers("demo")
    path = "/api/v2/chatbots/xlsx/workbooks"
    content = workbook_bytes()
    books = []
    for index in range(10):
        response = client.post(path, headers=headers, files={"file": (f"{index}.xlsx", content)})
        assert response.status_code == 201
        books.append(response.json())
    assert client.post(
        path, headers=headers, files={"file": ("eleven.xlsx", content)},
    ).status_code == 422
    assert client.delete(f"{path}/{books[0]['id']}", headers=headers).status_code == 204
    assert client.post(
        path, headers=headers, files={"file": ("replacement.xlsx", content)},
    ).status_code == 201
    assert len(client.get(path, headers=headers).json()["items"]) == 10


def test_concurrent_uploads_cannot_exceed_quota(tmp_path):
    store = ChatbotStore(tmp_path / "chatbots.sqlite3", xlsx_only=True)
    content = workbook_bytes()

    def upload(index):
        try:
            store.upload_personal_workbook("xlsx", "owner", f"{index}.xlsx", content)
            return True
        except ValidationFailed:
            return False

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(upload, range(13)))
    assert sum(results) == 10
    assert len(store.personal_workbooks("xlsx", "owner")) == 10
    assert store.personal_workbooks("xlsx", "other") == []


def test_workbooks_over_old_row_and_column_limits_remain_queryable(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = '明细'
    sheet.append(['序号', '金额'])
    for index in range(21001):
        sheet.append([index, 1])
    wide = book.create_sheet('宽表')
    wide.append([f'字段{index}' for index in range(101)])
    wide.append(list(range(101)))
    output = io.BytesIO()
    book.save(output)
    store = ChatbotStore(tmp_path / 'chatbots.sqlite3', xlsx_only=True)
    parsed = store.upload_personal_workbook('xlsx', 'owner', 'larger.xlsx', output.getvalue())
    assert parsed['row_count'] == 21002
    lab = WorkbookLab(
        store.personal_workbooks('xlsx', 'owner'), lambda: None, None,
        lambda *_: pytest.fail('external source'),
    )
    table = parsed['sheets'][0]['table']
    assert lab.execute(f'SELECT SUM("金额") FROM "{table}"', 10)[1] == [[21001.0]]


def test_query_context_uses_only_owner_files_and_freezes_selected_sources(
    settings, app, seed_user,
):
    from xiaoying_quick.bootstrap.container import build_agent_service
    from xiaoying_quick.infrastructure.persistence.repositories.runs import SqlAlchemyRunRepository
    from xiaoying_quick.infrastructure.persistence.session import session_scope
    from xiaoying_quick.modules.identity.service import IdentityService
    from xiaoying_quick.modules.runs.service import RunService

    settings.chatbot_mode = 'xlsx'
    owner, other = seed_user('owner'), seed_user('other')
    store = ChatbotStore(settings.secret_store_path.parent / 'chatbots.sqlite3', xlsx_only=True)
    own = store.upload_personal_workbook('xlsx', owner.id, 'mine.xlsx', workbook_bytes())
    foreign = store.upload_personal_workbook('xlsx', other.id, 'other.xlsx', workbook_bytes())
    with session_scope(app.state.session_factory) as database:
        run = RunService(SqlAlchemyRunRepository(database)).create_run(
            principal=IdentityService.principal_from_user(owner),
            question='汇总活跃用户', session_id=None, idempotency_key=None,
            insight_meta={'chatbot_id': 'xlsx', 'workbook_ids': [own['id']]},
        ).run
        later = store.upload_personal_workbook('xlsx', owner.id, 'later.xlsx', workbook_bytes())
        service = build_agent_service(database, app, run_id=run.id)
        assert set(service._tools.names()) == {
            "inspect_workbook", "query_db", "export_xlsx", "ask_user",
            "present_chart",
        }
        prompt = service._system_prompt()
        assert "实验室" not in prompt
        assert "医药经营" in prompt
        query = service._tool_dependencies['query_db']
        assert service._tool_dependencies['lab_provider'] == 'xlsx'
        table = own['sheets'][0]['table']
        assert query(f'SELECT SUM("活跃用户") FROM "{table}"', 10)[1] == [[200.0]]
        for unavailable in (foreign, later):
            with pytest.raises(ValidationFailed):
                query(f'SELECT * FROM "{unavailable["sheets"][0]["table"]}"', 10)
        store.remove_personal_workbook('xlsx', owner.id, own['id'])
        with pytest.raises(ValidationFailed, match='已移除'):
            build_agent_service(database, app, run_id=run.id)
