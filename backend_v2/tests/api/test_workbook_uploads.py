from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.api.test_chatbots import workbook_bytes
from xiaoying_quick.infrastructure.chatbots import ChatbotStore
from xiaoying_quick.shared.errors import NotFound, ValidationFailed


def test_async_upload_is_owner_scoped_and_repeated_requests_return_one_workbook(
    settings,
    client,
    seed_user,
    auth_headers,
    monkeypatch,
):
    settings.chatbot_mode = "xlsx"
    owner = seed_user("owner")
    seed_user("other")
    headers, other = auth_headers("owner"), auth_headers("other")
    path = "/api/v2/chatbots/xlsx/workbook-uploads"
    upload_id = "upload_lost_response_123"
    files = {"file": ("业务.xlsx", workbook_bytes())}
    process = ChatbotStore.process_workbook_uploads
    monkeypatch.setattr(ChatbotStore, "process_workbook_uploads", lambda self: None)
    assert client.post(path, files=files, data={"upload_id": upload_id}).status_code == 401
    accepted = client.post(path, files=files, data={"upload_id": upload_id}, headers=headers)
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["status"] == "queued"
    assert "content" not in accepted.json() and "owner_id" not in accepted.json()
    assert client.get(path, headers=headers).json()["items"] == [accepted.json()]
    assert client.get(path, headers=other).json()["items"] == []
    assert client.get(f"{path}/{upload_id}", headers=other).status_code == 404
    assert (
        client.post(path, files=files, data={"upload_id": upload_id}, headers=other).status_code
        == 404
    )
    assert client.get("/api/v2/chatbots/xlsx/workbooks", headers=headers).json()["items"] == []
    store = ChatbotStore(settings.secret_store_path.parent / "chatbots.sqlite3", xlsx_only=True)
    process(store)
    completed = client.get(f"{path}/{upload_id}", headers=headers).json()
    assert completed["status"] == "ready"
    assert completed["workbook"]["row_count"] == 2
    assert (
        client.post(path, files=files, data={"upload_id": upload_id}, headers=headers).json()
        == completed
    )
    assert len(store.personal_workbooks("xlsx", owner.id)) == 1
    assert client.get(path, headers=headers).json()["items"] == []
    book_id = completed["workbook"]["id"]
    assert (
        client.delete(f"/api/v2/chatbots/xlsx/workbooks/{book_id}", headers=headers).status_code
        == 204
    )
    assert client.get(f"{path}/{upload_id}", headers=headers).json()["status"] == "removed"


def test_pending_uploads_reserve_quota_and_concurrent_retries_share_the_reservation(tmp_path):
    store = ChatbotStore(tmp_path / "chatbots.sqlite3", xlsx_only=True)
    content = workbook_bytes()
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(
            pool.map(
                lambda _: store.begin_workbook_upload(
                    "xlsx", "owner", "same_request", "a.xlsx", content
                ),
                range(6),
            )
        )
    assert len({item["id"] for item in results}) == 1
    with pytest.raises(ValidationFailed, match="另一个文件"):
        store.begin_workbook_upload("xlsx", "owner", "same_request", "changed.xlsx", content)
    for index in range(9):
        store.begin_workbook_upload("xlsx", "owner", f"upload_{index}", "a.xlsx", content)
    with pytest.raises(ValidationFailed, match="10"):
        store.begin_workbook_upload("xlsx", "owner", "eleven", "a.xlsx", content)
    with pytest.raises(ValidationFailed, match="10"):
        store.upload_personal_workbook("xlsx", "owner", "legacy.xlsx", content)
    with pytest.raises(NotFound):
        store.workbook_upload("xlsx", "other", "same_request")
    store.process_workbook_uploads()
    assert len(store.personal_workbooks("xlsx", "owner")) == 10
    with store._connect() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM workbook_uploads WHERE content IS NOT NULL"
            ).fetchone()[0]
            == 0
        )


def test_invalid_upload_releases_reserved_slot_and_has_readable_error(tmp_path):
    store = ChatbotStore(tmp_path / "chatbots.sqlite3", xlsx_only=True)
    store.begin_workbook_upload("xlsx", "owner", "broken", "broken.xlsx", b"bad xlsx")
    store.process_workbook_uploads()
    failed = store.workbook_upload("xlsx", "owner", "broken")
    assert failed["status"] == "failed"
    assert "无法读取" in failed["error"]
    assert store.personal_workbooks("xlsx", "owner") == []
    assert store.pending_workbook_uploads("xlsx", "owner") == []
    assert (
        store.begin_workbook_upload("xlsx", "owner", "valid", "a.xlsx", workbook_bytes())["status"]
        == "queued"
    )


def test_restart_restores_interrupted_upload_without_losing_content_or_duplicating_file(tmp_path):
    path = tmp_path / "chatbots.sqlite3"
    store = ChatbotStore(path, xlsx_only=True)
    store.begin_workbook_upload("xlsx", "owner", "interrupted", "a.xlsx", workbook_bytes())
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE workbook_uploads SET status='processing', "
            "body=json_set(body, '$.status', 'processing')"
        )
    restarted = ChatbotStore(path, xlsx_only=True)
    restarted.recover_workbook_uploads()
    assert restarted.workbook_upload("xlsx", "owner", "interrupted")["status"] == "queued"
    restarted.process_workbook_uploads()
    restarted.recover_workbook_uploads()
    restarted.process_workbook_uploads()
    assert restarted.workbook_upload("xlsx", "owner", "interrupted")["status"] == "ready"
    assert len(restarted.personal_workbooks("xlsx", "owner")) == 1


def test_parser_is_serial_and_status_requests_can_finish_while_parsing(tmp_path, monkeypatch):
    store = ChatbotStore(tmp_path / "chatbots.sqlite3", xlsx_only=True)
    content = workbook_bytes()
    store.begin_workbook_upload("xlsx", "owner", "one", "a.xlsx", content)
    store.begin_workbook_upload("xlsx", "other", "two", "b.xlsx", content)
    entered, release = threading.Event(), threading.Event()
    original = ChatbotStore._parse_workbook
    calls = []

    def parse(filename, data):
        calls.append(filename)
        entered.set()
        assert release.wait(5)
        return original(filename, data)

    monkeypatch.setattr(ChatbotStore, "_parse_workbook", staticmethod(parse))
    with ThreadPoolExecutor(max_workers=2) as pool:
        worker = pool.submit(store.process_workbook_uploads)
        try:
            assert entered.wait(5)
            pool.submit(store.process_workbook_uploads).result(timeout=1)
            assert calls == ["a.xlsx"]
            assert store.workbook_upload("xlsx", "owner", "one")["status"] == "processing"
            assert store.workbook_upload("xlsx", "other", "two")["status"] == "queued"
        finally:
            release.set()
        worker.result(timeout=5)
    assert calls == ["a.xlsx", "b.xlsx"]
    assert store.workbook_upload("xlsx", "other", "two")["status"] == "ready"


def test_upload_status_never_becomes_ready_if_workbook_commit_fails(tmp_path):
    store = ChatbotStore(tmp_path / "chatbots.sqlite3", xlsx_only=True)
    store.begin_workbook_upload("xlsx", "owner", "transaction", "a.xlsx", workbook_bytes())
    with store._connect() as db:
        db.execute(
            "CREATE TRIGGER reject_personal BEFORE INSERT ON personal_workbooks "
            "BEGIN SELECT RAISE(FAIL, 'test'); END"
        )
    store.process_workbook_uploads()
    assert store.workbook_upload("xlsx", "owner", "transaction")["status"] == "failed"
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM workbooks").fetchone()[0] == 0
