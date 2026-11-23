from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from xiaoying_quick.infrastructure.workspace import WorkspaceStore
from xiaoying_quick.shared.errors import NotFound, ValidationFailed


def template():
    return {
        "id": "pharma-moc-2026-demo-v1",
        "name": "医药 MOC 经营看板",
        "description": "内置模拟数据",
        "theme": "commercial",
        "items": [
            {
                "fingerprint": f"demo-item-{index}",
                "title": f"经营指标{index}",
                "kind": "table",
                "width": "full",
                "source": {"kind": "template", "sample": True, "chatbot_id": "xlsx"},
                "snapshot": {"data": {"columns": ["城市", "销售额"], "rows": [["北京", 100]]}},
            }
            for index in range(4)
        ],
    }


def test_default_boards_are_private_independent_and_retry_preserves_edits(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.sqlite3")
    original = template()
    boards = [store.seed_default(f"user-{index}", original) for index in range(5)]
    assert len({board["id"] for board in boards}) == 5
    for index, board in enumerate(boards):
        assert len(store.list(f"user-{index}")) == 1
        assert board["my_role"] == "owner" and board["card_count"] == 4
        assert all(item["width"] == "full" for item in board["items"])
        assert all(item["source"]["owner_id"] == f"user-{index}" for item in board["items"])
        with pytest.raises(NotFound):
            store.get(board["id"], "outside")
    first = boards[0]
    edited = store.update(
        first["id"], "user-0", {**original, "name": "个人修改的看板"}, first["version"]
    )
    assert store.seed_default("user-0", original)["name"] == "个人修改的看板"
    assert store.get(boards[1]["id"], "user-1")["name"] == original["name"]
    shared = store.set_access(
        first["id"], "user-0", [{"user_id": "user-1", "role": "viewer"}], edited["version"]
    )
    assert store.get(shared["id"], "user-1")["my_role"] == "viewer"
    assert len(store.list("user-1")) == 2


def test_default_board_is_atomic_and_concurrent_retries_do_not_duplicate_it(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.sqlite3")
    invalid = template()
    invalid["items"][1]["width"] = "invalid"
    with pytest.raises(ValidationFailed):
        store.seed_default("user", invalid)
    assert store.list("user") == []
    with ThreadPoolExecutor(max_workers=4) as pool:
        boards = list(pool.map(lambda _: store.seed_default("user", template()), range(4)))
    assert len({board["id"] for board in boards}) == 1
    assert all(board["card_count"] == 4 for board in boards)
    assert len(store.list("user")) == 1
