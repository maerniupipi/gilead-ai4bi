"""Durable, explicitly shared dashboard snapshots for the single-host workspace."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from xiaoying_quick.infrastructure.auxiliary_db import AuxiliaryDatabase
from xiaoying_quick.shared.errors import Conflict, Forbidden, NotFound, ValidationFailed
from xiaoying_quick.shared.ids import new_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkspaceStore:
    def __init__(self, path: Path, *, database_url: str | None = None) -> None:
        self.path = path
        self.database = AuxiliaryDatabase(path, database_url, lock_id=2)
        with self._db(write=True) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS boards (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL,
                    description TEXT NOT NULL, theme TEXT NOT NULL, version INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS board_members (
                    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('viewer','editor')),
                    PRIMARY KEY(board_id,user_id)
                );
                CREATE TABLE IF NOT EXISTS board_items (
                    id TEXT PRIMARY KEY,
                    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
                    fingerprint TEXT NOT NULL, title TEXT NOT NULL, kind TEXT NOT NULL,
                    width TEXT NOT NULL, position INTEGER NOT NULL,
                    source TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(board_id,fingerprint)
                );
                CREATE INDEX IF NOT EXISTS ix_board_member_user ON board_members(user_id);
                CREATE INDEX IF NOT EXISTS ix_board_item_position ON board_items(board_id,position);
            """)

    def _db(self, *, write: bool = False):
        return self.database.connect(write=write, named=True)

    @staticmethod
    def _authorized(db, board_id: str, user_id: str, action: str = "view"):
        board = db.execute("SELECT * FROM boards WHERE id=?", (board_id,)).fetchone()
        if board is None:
            raise NotFound("看板不存在或你没有访问权限")
        if board["owner_id"] == user_id:
            role = "owner"
        else:
            member = db.execute(
                "SELECT role FROM board_members WHERE board_id=? AND user_id=?", (board_id, user_id)
            ).fetchone()
            role = member[0] if member else None
        if role is None:
            raise NotFound("看板不存在或你没有访问权限")
        if action == "edit" and role not in ("owner", "editor"):
            raise Forbidden("此看板为只读，请联系创建者授予编辑权限")
        if action == "manage" and role != "owner":
            raise Forbidden("只有看板创建者可以管理成员或删除看板")
        return board, role

    @staticmethod
    def _summary(db, board, role: str) -> dict[str, Any]:
        count = db.execute("SELECT COUNT(*) FROM board_items WHERE board_id=?", (board["id"],))
        members = db.execute(
            "SELECT COUNT(*) FROM board_members WHERE board_id=?", (board["id"],)
        ).fetchone()[0]
        previews = db.execute(
            "SELECT title,kind FROM board_items WHERE board_id=? ORDER BY position LIMIT 3",
            (board["id"],),
        ).fetchall()
        return {
            **dict(board),
            "my_role": role,
            "card_count": count.fetchone()[0],
            "member_count": members,
            "previews": [dict(item) for item in previews],
        }

    @staticmethod
    def _touch(db, board_id: str) -> None:
        db.execute(
            "UPDATE boards SET version=version+1,updated_at=? WHERE id=?", (_now(), board_id)
        )

    @staticmethod
    def _version(board, expected: int) -> None:
        if board["version"] != expected:
            raise Conflict("看板已被其他操作更新，请刷新后重新编辑")

    def list(self, user_id: str) -> list[dict[str, Any]]:
        with self._db() as db:
            boards = db.execute(
                "SELECT b.*,m.role AS member_role FROM boards b LEFT JOIN board_members m "
                "ON m.board_id=b.id AND m.user_id=? WHERE b.owner_id=? OR m.user_id=? "
                "ORDER BY b.updated_at DESC,b.id",
                (user_id, user_id, user_id),
            ).fetchall()
            return [
                self._summary(
                    db,
                    {key: row[key] for key in row.keys() if key != "member_role"},
                    "owner" if row["owner_id"] == user_id else row["member_role"],
                )
                for row in boards
            ]

    def get(self, board_id: str, user_id: str) -> dict[str, Any]:
        with self._db() as db:
            board, role = self._authorized(db, board_id, user_id)
            items = db.execute(
                "SELECT * FROM board_items WHERE board_id=? ORDER BY position,id", (board_id,)
            ).fetchall()
            return {
                **self._summary(db, board, role),
                "items": [
                    {
                        **{key: row[key] for key in ("id", "title", "kind", "width", "created_at")},
                        "source": json.loads(row["source"]),
                        "snapshot": json.loads(row["snapshot"]),
                    }
                    for row in items
                ],
            }

    def create(self, user_id: str, fields: dict, asset: dict | None = None) -> dict:
        board_id = new_id("board")
        with self._db(write=True) as db:
            self._create_record(db, board_id, user_id, fields)
            if asset:
                self._attach(db, board_id, asset)
        return self.get(board_id, user_id)

    @staticmethod
    def _create_record(db, board_id: str, user_id: str, fields: dict) -> None:
        now = _now()
        db.execute(
            "INSERT INTO boards VALUES (?,?,?,?,?,?,?,?)",
            (
                board_id,
                user_id,
                fields["name"],
                fields["description"],
                fields["theme"],
                1,
                now,
                now,
            ),
        )

    def seed_default(self, user_id: str, template: dict) -> dict:
        """Create an independent template copy once, preserving subsequent user edits."""
        digest = hashlib.sha256(f"{user_id}:{template['id']}".encode()).hexdigest()[:32]
        board_id = f"board_{digest}"
        with self._db(write=True) as db:
            existing = db.execute("SELECT owner_id FROM boards WHERE id=?", (board_id,)).fetchone()
            if existing is not None and existing[0] != user_id:
                raise Conflict("默认看板归属不匹配")
            if existing is None:
                self._create_record(db, board_id, user_id, template)
                for item in template["items"]:
                    width = item.get("width", "full")
                    if width not in {"half", "full"}:
                        raise ValidationFailed("默认看板内容宽度无效")
                    source = {**item["source"], "owner_id": user_id}
                    asset = {**item, "source": source}
                    self._attach(db, board_id, asset)
                    db.execute(
                        "UPDATE board_items SET width=? WHERE board_id=? AND fingerprint=?",
                        (width, board_id, asset["fingerprint"]),
                    )
        return self.get(board_id, user_id)

    def update(self, board_id: str, user_id: str, fields: dict, version: int) -> dict:
        with self._db(write=True) as db:
            board, _ = self._authorized(db, board_id, user_id, "edit")
            self._version(board, version)
            db.execute(
                "UPDATE boards SET name=?,description=?,theme=? WHERE id=?",
                (
                    fields["name"],
                    fields["description"],
                    fields["theme"],
                    board_id,
                ),
            )
            self._touch(db, board_id)
        return self.get(board_id, user_id)

    def delete(self, board_id: str, user_id: str) -> None:
        with self._db(write=True) as db:
            self._authorized(db, board_id, user_id, "manage")
            db.execute("DELETE FROM boards WHERE id=?", (board_id,))

    @staticmethod
    def _attach(db, board_id: str, asset: dict) -> bool:
        if db.execute(
            "SELECT id FROM board_items WHERE board_id=? AND fingerprint=?",
            (
                board_id,
                asset["fingerprint"],
            ),
        ).fetchone():
            return True
        count = db.execute(
            "SELECT COUNT(*) FROM board_items WHERE board_id=?", (board_id,)
        ).fetchone()[0]
        if count >= 40:
            raise ValidationFailed("每个看板最多保存 40 张图表，请新建主题看板")
        snapshot = json.dumps(asset["snapshot"], ensure_ascii=False, allow_nan=False)
        if len(snapshot.encode()) > 1_600_000:
            raise ValidationFailed("图表快照过大，请缩小筛选范围后重试")
        position = db.execute(
            "SELECT COALESCE(MAX(position),-1)+1 FROM board_items WHERE board_id=?", (board_id,)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO board_items VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                new_id("tile"),
                board_id,
                asset["fingerprint"],
                asset["title"],
                asset["kind"],
                "full" if asset["kind"] in ("analysis", "report", "kpi", "table") else "half",
                position,
                json.dumps(asset["source"], ensure_ascii=False),
                snapshot,
                _now(),
            ),
        )
        return False

    def add(self, board_id: str, user_id: str, asset: dict) -> dict:
        with self._db(write=True) as db:
            self._authorized(db, board_id, user_id, "edit")
            duplicate = self._attach(db, board_id, asset)
            if not duplicate:
                self._touch(db, board_id)
        return {"board": self.get(board_id, user_id), "already_added": duplicate}

    def layout(self, board_id: str, user_id: str, items: list[dict], version: int) -> dict:
        with self._db(write=True) as db:
            board, _ = self._authorized(db, board_id, user_id, "edit")
            self._version(board, version)
            existing = {
                row[0]
                for row in db.execute("SELECT id FROM board_items WHERE board_id=?", (board_id,))
            }
            requested = [item["id"] for item in items]
            if len(set(requested)) != len(requested) or not set(requested) <= existing:
                raise ValidationFailed("图表列表已变化，请刷新看板后重试")
            for removed in existing - set(requested):
                db.execute("DELETE FROM board_items WHERE id=? AND board_id=?", (removed, board_id))
            for index, item in enumerate(items):
                db.execute(
                    "UPDATE board_items SET position=?,title=?,width=? WHERE id=? AND board_id=?",
                    (index, item["title"], item["width"], item["id"], board_id),
                )
            self._touch(db, board_id)
        return self.get(board_id, user_id)

    def access(self, board_id: str, user_id: str) -> dict:
        with self._db() as db:
            board, _ = self._authorized(db, board_id, user_id, "manage")
            members = db.execute(
                "SELECT user_id,role FROM board_members WHERE board_id=? ORDER BY user_id",
                (board_id,),
            ).fetchall()
            return {
                "owner_id": board["owner_id"],
                "version": board["version"],
                "members": [dict(row) for row in members],
            }

    def set_access(self, board_id: str, user_id: str, members: list[dict], version: int) -> dict:
        with self._db(write=True) as db:
            board, _ = self._authorized(db, board_id, user_id, "manage")
            self._version(board, version)
            if any(member["user_id"] == board["owner_id"] for member in members):
                raise ValidationFailed("创建者始终拥有管理权限，无需再次添加")
            if len({m["user_id"] for m in members}) != len(members):
                raise ValidationFailed("同一账号只能配置一次权限")
            db.execute("DELETE FROM board_members WHERE board_id=?", (board_id,))
            db.executemany(
                "INSERT INTO board_members VALUES (?,?,?)",
                [(board_id, member["user_id"], member["role"]) for member in members],
            )
            self._touch(db, board_id)
        return self.get(board_id, user_id)
