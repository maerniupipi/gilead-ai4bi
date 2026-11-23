"""Single-host Chatbot configuration and value-only workbook storage."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import sqlite3
import threading
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from xiaoying_quick.infrastructure.auxiliary_db import AuxiliaryDatabase
from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal, Role
from xiaoying_quick.shared.errors import Forbidden, NotFound, ValidationFailed
from xiaoying_quick.shared.ids import new_id

DEFAULT_CHATBOT = "ddi"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_WORKBOOKS = 10
MAX_WORKBOOK_SHEETS = 5
_IMPORT_LOCK = threading.Lock()
_LOGGER = logging.getLogger(__name__)


def can_use_chatbot(bot: dict[str, Any], principal: AuthenticatedPrincipal) -> bool:
    if not bot.get("enabled", True):
        return False
    return (
        principal.role is Role.ADMIN
        or bot.get("access", "all") == "all"
        or (bot.get("access") == "roles" and principal.role.value in bot.get("roles", []))
        or (bot.get("access") == "users" and principal.user_id in bot.get("user_ids", []))
    )


class ChatbotStore:
    def __init__(
        self, path: Path, *, xlsx_only: bool = False,
        mode: Literal["dual", "full", "xlsx"] | None = None,
        database_url: str | None = None,
    ) -> None:
        self.path = path
        self.mode = mode or ("xlsx" if xlsx_only else "full")
        self.xlsx_only = self.mode == "xlsx"
        self.database = AuxiliaryDatabase(path, database_url, lock_id=1)
        order_column = ", rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE" if self.database.postgres else ""
        binary_type = "BYTEA" if self.database.postgres else "BLOB"
        with self._connect(write=True) as db:
            db.execute(
                f"CREATE TABLE IF NOT EXISTS chatbots (id TEXT PRIMARY KEY, body TEXT NOT NULL{order_column})"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS workbooks (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS personal_workbooks ("
                f"workbook_id TEXT PRIMARY KEY, chatbot_id TEXT NOT NULL, owner_id TEXT NOT NULL{order_column})"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS ix_personal_workbooks_owner "
                "ON personal_workbooks(chatbot_id, owner_id)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS workbook_uploads ("
                "id TEXT PRIMARY KEY, chatbot_id TEXT NOT NULL, owner_id TEXT NOT NULL, "
                "fingerprint TEXT NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL, "
                f"content {binary_type}{order_column})"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS ix_workbook_uploads_owner "
                "ON workbook_uploads(chatbot_id, owner_id, status)"
            )
            seeds = (
                [self._xlsx_seed()] if self.xlsx_only
                else [self._database_seed(), self._xlsx_seed()] if self.mode == "dual"
                else self._seeds()
            )
            for bot in seeds:
                db.execute("INSERT INTO chatbots(id,body) VALUES (?, ?) ON CONFLICT(id) DO NOTHING", (bot["id"], _json(bot)))
            if self.xlsx_only:
                return
            original = json.loads(
                db.execute("SELECT body FROM chatbots WHERE id='ddi'").fetchone()[0]
            )
            if original.get("lab_ids") == ["ddi"]:
                original["lab_ids"] = ["actual"]
                db.execute("UPDATE chatbots SET body=? WHERE id='ddi'", (_json(original),))
            if self.mode == "full":
                sample = _behavior_workbook()
                db.execute(
                    "INSERT INTO workbooks VALUES (?, ?) ON CONFLICT(id) DO NOTHING", (sample["id"], _json(sample))
                )

    def _connect(self, *, write: bool = False):
        return self.database.connect(write=write)

    @staticmethod
    def _xlsx_seed() -> dict[str, Any]:
        return {
            "id": "xlsx",
            "name": "XLSX 问数助手",
            "description": "上传自己的 Excel，用自然语言问数，将分析图表加入专属看板。",
            "category": "general",
            "access": "all",
            "roles": [],
            "user_ids": [],
            "enabled": True,
            "personal_uploads": True,
            "lab_ids": [],
            "workbook_ids": [],
            "sample": False,
            "created_at": "2026-11-10T00:00:00+00:00",
            "updated_at": "2026-11-10T00:00:00+00:00",
        }

    @classmethod
    def _database_seed(cls) -> dict[str, Any]:
        return cls._seeds()[0] | {
            "name": "数据库问数助手",
            "description": "连接已授权的业务数据库，查询经营指标、分析变化并生成图表与看板。",
            "sample": False,
        }

    @staticmethod
    def _seeds() -> list[dict[str, Any]]:
        common = {
            "access": "all",
            "roles": [],
            "user_ids": [],
            "enabled": True,
            "created_at": "2026-10-27T00:00:00+00:00",
            "updated_at": "2026-10-27T00:00:00+00:00",
        }
        return [
            {
                **common,
                "id": "ddi",
                "name": "DDI 商业分析",
                "category": "ddi",
                "description": (
                    "连接销售与目标数据，从业务问数到主动归因，生成可交互的商业洞察报告。"
                ),
                "lab_ids": ["actual"],
                "workbook_ids": [],
                "sample": True,
            },
            {
                **common,
                "id": "behavior",
                "name": "行为数据分析",
                "category": "behavior",
                "description": "看清访问、活跃与转化表现，按区域和渠道拆解用户行为，发现增长机会。",
                "lab_ids": [],
                "workbook_ids": ["workbook_behavior_sample"],
                "sample": True,
            },
        ]

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            bots = [
                json.loads(row[0]) for row in db.execute("SELECT body FROM chatbots ORDER BY rowid")
            ]
        if self.xlsx_only:
            return [bot for bot in bots if bot["id"] == "xlsx"]
        if self.mode == "dual":
            return [bot for bot in bots if bot["id"] != "behavior"]
        return bots

    def get(self, bot_id: str) -> dict[str, Any]:
        if self.xlsx_only and bot_id != "xlsx":
            raise NotFound("当前环境只提供 XLSX 问数助手")
        if self.mode == "dual" and bot_id == "behavior":
            raise NotFound("当前环境开放数据库问数与 XLSX 问数")
        with self._connect() as db:
            row = db.execute("SELECT body FROM chatbots WHERE id=?", (bot_id,)).fetchone()
        if row is None:
            raise NotFound("Chatbot 不存在")
        return json.loads(row[0])

    def require(self, bot_id: str, principal: AuthenticatedPrincipal) -> dict[str, Any]:
        bot = self.get(bot_id)
        if not can_use_chatbot(bot, principal):
            raise Forbidden("当前账号尚未获准使用此 Chatbot，或该助手已停用")
        return bot

    def save(self, values: dict[str, Any], bot_id: str | None = None) -> dict[str, Any]:
        if self.xlsx_only:
            raise ValidationFailed("当前环境只提供一个 XLSX 问数助手，请在对话页管理自己的文件")
        previous = self.get(bot_id) if bot_id else {}
        if previous.get("personal_uploads"):
            raise ValidationFailed("个人 XLSX 助手的文件请在对话页管理，不能改为共享数据源")
        if len(values.get("workbook_ids", [])) > MAX_WORKBOOKS:
            raise ValidationFailed("最多支持 10 个 XLSX 工作簿")
        for workbook_id in values.get("workbook_ids", []):
            if self.workbook(workbook_id).get("owner_id"):
                raise ValidationFailed("个人上传的文件不能绑定为共享数据源")
        now = datetime.now(timezone.utc).isoformat()
        bot = {
            **values,
            "id": bot_id or new_id("chatbot"),
            "created_at": previous.get("created_at", now),
            "updated_at": now,
        }
        with self._connect() as db:
            db.execute("INSERT INTO chatbots(id,body) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body", (bot["id"], _json(bot)))
        return bot

    def workbook(self, workbook_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT body FROM workbooks WHERE id=?", (workbook_id,)).fetchone()
        if row is None:
            raise ValidationFailed("工作簿不存在，请重新上传后保存")
        return json.loads(row[0])

    def save_workbook(self, filename: str, content: bytes) -> dict[str, Any]:
        record = self._parse_workbook(filename, content)
        with self._connect() as db:
            db.execute("INSERT INTO workbooks VALUES (?, ?)", (record["id"], _json(record)))
        return self.workbook_summary(record)

    def personal_workbooks(self, bot_id: str, owner_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT w.body FROM workbooks w JOIN personal_workbooks p "
                "ON w.id=p.workbook_id WHERE p.chatbot_id=? AND p.owner_id=? ORDER BY p.rowid",
                (bot_id, owner_id),
            )]

    def upload_personal_workbook(
        self, bot_id: str, owner_id: str, filename: str, content: bytes,
    ) -> dict[str, Any]:
        if not self.get(bot_id).get("personal_uploads"):
            raise ValidationFailed("此助手不支持个人文件上传")
        record = self._parse_workbook(filename, content)
        record["owner_id"] = owner_id
        with self._connect() as db:
            # Serialize count + insertion so concurrent requests cannot exceed the quota.
            db.execute("BEGIN IMMEDIATE")
            count = db.execute(
                "SELECT COUNT(*) FROM personal_workbooks WHERE chatbot_id=? AND owner_id=?",
                (bot_id, owner_id),
            ).fetchone()[0]
            if count + self._pending_upload_count(db, bot_id, owner_id) >= MAX_WORKBOOKS:
                raise ValidationFailed("最多支持 10 个 XLSX 文件，请先移除不再需要的文件")
            db.execute("INSERT INTO workbooks VALUES (?, ?)", (record["id"], _json(record)))
            db.execute(
                "INSERT INTO personal_workbooks(workbook_id,chatbot_id,owner_id) VALUES (?, ?, ?)",
                (record["id"], bot_id, owner_id),
            )
        return self.workbook_summary(record)

    @staticmethod
    def _pending_upload_count(db: sqlite3.Connection, bot_id: str, owner_id: str) -> int:
        return db.execute(
            "SELECT COUNT(*) FROM workbook_uploads WHERE chatbot_id=? AND owner_id=? "
            "AND status IN ('queued', 'processing')", (bot_id, owner_id),
        ).fetchone()[0]

    def begin_workbook_upload(
        self, bot_id: str, owner_id: str, upload_id: str, filename: str, content: bytes,
    ) -> dict[str, Any]:
        if not self.get(bot_id).get("personal_uploads"):
            raise ValidationFailed("此助手不支持个人文件上传")
        self._validate_upload(filename, content)
        filename = Path(filename).name[:180]
        fingerprint = hashlib.sha256(filename.encode() + b"\0" + content).hexdigest()
        with self._connect(write=True) as db:
            previous = db.execute(
                "SELECT chatbot_id, owner_id, fingerprint, body FROM workbook_uploads WHERE id=?",
                (upload_id,),
            ).fetchone()
            if previous:
                if previous[:2] != (bot_id, owner_id):
                    raise NotFound("上传任务不存在")
                if previous[2] != fingerprint:
                    raise ValidationFailed("上传标识已用于另一个文件，请重新选择文件")
                return json.loads(previous[3])
            count = db.execute(
                "SELECT COUNT(*) FROM personal_workbooks WHERE chatbot_id=? AND owner_id=?",
                (bot_id, owner_id),
            ).fetchone()[0]
            if count + self._pending_upload_count(db, bot_id, owner_id) >= MAX_WORKBOOKS:
                raise ValidationFailed(
                    "最多支持 10 个 XLSX 文件（包含正在处理的文件），请先移除文件"
                )
            upload = {
                "id": upload_id, "filename": filename, "bytes": len(content), "status": "queued",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            db.execute(
                "INSERT INTO workbook_uploads(id,chatbot_id,owner_id,fingerprint,status,body,content) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (upload_id, bot_id, owner_id, fingerprint, "queued", _json(upload), content),
            )
        return upload

    def workbook_upload(self, bot_id: str, owner_id: str, upload_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT body FROM workbook_uploads WHERE id=? AND chatbot_id=? AND owner_id=?",
                (upload_id, bot_id, owner_id),
            ).fetchone()
        if row is None:
            raise NotFound("上传任务不存在")
        return json.loads(row[0])

    def pending_workbook_uploads(self, bot_id: str, owner_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT body FROM workbook_uploads WHERE chatbot_id=? AND owner_id=? "
                "AND status IN ('queued', 'processing') ORDER BY rowid", (bot_id, owner_id),
            )]

    def recover_workbook_uploads(self) -> None:
        # The single-host process calls this once at startup, before accepting requests.
        with self._connect() as db:
            db.execute(
                ("UPDATE workbook_uploads SET status='queued', "
                 "body=(body::jsonb || jsonb_build_object('status','queued'))::text WHERE status='processing'")
                if self.database.postgres else
                ("UPDATE workbook_uploads SET status='queued', "
                 "body=json_set(body, '$.status', 'queued') WHERE status='processing'")
            )

    def process_workbook_uploads(self) -> None:
        # A single parser bounds memory use; other uploads remain durably queued.
        if not _IMPORT_LOCK.acquire(blocking=False):
            return
        try:
            while True:
                with self._connect(write=True) as db:
                    row = db.execute(
                        "SELECT id, chatbot_id, owner_id, body, content FROM workbook_uploads "
                        "WHERE status='queued' ORDER BY rowid LIMIT 1"
                    ).fetchone()
                    if row is None:
                        return
                    upload_id, bot_id, owner_id, body, content = row
                    upload = json.loads(body) | {"status": "processing"}
                    db.execute(
                        "UPDATE workbook_uploads SET status='processing', body=? WHERE id=?",
                        (_json(upload), upload_id),
                    )
                try:
                    record = self._parse_workbook(upload["filename"], content)
                    record["owner_id"] = owner_id
                    result = upload | {"status": "ready", "workbook": self.workbook_summary(record)}
                    with self._connect() as db:
                        # File visibility and ready status must be committed together.
                        db.execute(
                            "INSERT INTO workbooks VALUES (?, ?)", (record["id"], _json(record))
                        )
                        db.execute(
                            "INSERT INTO personal_workbooks(workbook_id,chatbot_id,owner_id) VALUES (?, ?, ?)",
                            (record["id"], bot_id, owner_id),
                        )
                        db.execute(
                            "UPDATE workbook_uploads SET status='ready', body=?, content=NULL "
                            "WHERE id=?",
                            (_json(result), upload_id),
                        )
                except Exception as error:
                    if isinstance(error, ValidationFailed):
                        message = error.message
                    else:
                        _LOGGER.exception("workbook import failed: %s", upload_id)
                        message = "文件处理失败，请稍后重新上传"
                    result = upload | {"status": "failed", "error": message}
                    with self._connect() as db:
                        db.execute(
                            "UPDATE workbook_uploads SET status='failed', body=?, content=NULL "
                            "WHERE id=?",
                            (_json(result), upload_id),
                        )
                finally:
                    # Do not keep the previous large workbook alive while parsing the next one.
                    content = None
                    row = None
                    record = None
        finally:
            _IMPORT_LOCK.release()

    def remove_personal_workbook(self, bot_id: str, owner_id: str, workbook_id: str) -> None:
        with self._connect() as db:
            deleted = db.execute(
                "DELETE FROM personal_workbooks "
                "WHERE workbook_id=? AND chatbot_id=? AND owner_id=?",
                (workbook_id, bot_id, owner_id),
            )
            if not deleted.rowcount:
                raise NotFound("文件不存在或不属于当前账号")
            db.execute("DELETE FROM workbooks WHERE id=?", (workbook_id,))
            db.execute(
                ("UPDATE workbook_uploads SET status='removed', "
                 "body=((body::jsonb - 'workbook') || jsonb_build_object('status','removed'))::text "
                 "WHERE chatbot_id=? AND owner_id=? AND body::jsonb #>> '{workbook,id}'=?")
                if self.database.postgres else
                ("UPDATE workbook_uploads SET status='removed', "
                 "body=json_remove(json_set(body, '$.status', 'removed'), '$.workbook') "
                 "WHERE chatbot_id=? AND owner_id=? AND json_extract(body, '$.workbook.id')=?"),
                (bot_id, owner_id, workbook_id),
            )

    @staticmethod
    def _validate_upload(filename: str, content: bytes) -> None:
        if not filename.lower().endswith(".xlsx"):
            raise ValidationFailed("请上传 .xlsx 格式的工作簿")
        if not content or len(content) > MAX_UPLOAD_BYTES:
            raise ValidationFailed("工作簿不能为空，且不能超过 10 MB")

    @staticmethod
    def _parse_workbook(filename: str, content: bytes) -> dict[str, Any]:
        ChatbotStore._validate_upload(filename, content)
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if sum(item.file_size for item in archive.infolist()) > 128 * 1024 * 1024:
                    raise ValidationFailed("工作簿解压后的内容过大，请缩小文件")
            from openpyxl import load_workbook

            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except ValidationFailed:
            raise
        except Exception as error:
            raise ValidationFailed("无法读取工作簿，请检查文件是否有效或受密码保护") from error
        record: dict[str, Any] = {
            "id": new_id("workbook"),
            "filename": Path(filename).name[:180],
            "bytes": len(content),
            "sample": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sheets": [],
        }
        try:
            if len(workbook.sheetnames) > MAX_WORKBOOK_SHEETS:
                raise ValidationFailed("每个 XLSX 最多支持 5 个 sheet（包含空白或隐藏工作表）")
            for index, sheet in enumerate(workbook.worksheets):
                iterator = sheet.iter_rows(values_only=False)
                header = tuple(cell.value for cell in next(iterator, ()))
                if not header:
                    continue
                while header and header[-1] is None:
                    header = header[:-1]
                if not header:
                    continue
                if len(header) > 2000:
                    raise ValidationFailed("工作表字段超过查询引擎的 2,000 列上限，请拆分工作表")
                columns = [
                    str(value).strip()[:100] if value is not None else "" for value in header
                ]
                if any(not column for column in columns) or (
                    len({column.casefold() for column in columns}) != len(columns)
                ):
                    raise ValidationFailed(f"「{sheet.title}」首行须为非空且不重复的字段名")
                rows = []
                formats: dict[str, list[str]] = {}
                for cells in iterator:
                    row = tuple(cell.value for cell in cells)
                    if not any(value is not None for value in row):
                        continue
                    if any(value is not None for value in row[len(columns):]):
                        raise ValidationFailed(f"「{sheet.title}」有数据列缺少字段名，请补齐首行")
                    if len(rows) < 200:
                        for column, cell in zip(columns, cells):
                            code = str(cell.number_format or "General")[:120]
                            if cell.value is not None and code != "General":
                                seen = formats.setdefault(column, [])
                                if code not in seen and len(seen) < 5:
                                    seen.append(code)
                    rows.append([_scalar(value) for value in row[: len(columns)]])
                if rows:
                    record["sheets"].append(
                        {
                            "name": sheet.title,
                            "table": f"wb_{record['id'][-12:]}_{index + 1}",
                            "columns": columns,
                            "column_formats": formats,
                            "rows": rows,
                        }
                    )
        except ValidationFailed:
            raise
        except Exception as error:
            raise ValidationFailed("无法读取工作表内容，请检查文件是否完整") from error
        finally:
            workbook.close()
        if not record["sheets"]:
            raise ValidationFailed("工作簿没有可读取的数据，请在首行填写字段名，后续行填写数据")
        return record

    @staticmethod
    def workbook_summary(record: dict[str, Any]) -> dict[str, Any]:
        result = {key: value for key, value in record.items() if key not in ("sheets", "owner_id")}
        return result | {
            "row_count": sum(len(sheet["rows"]) for sheet in record["sheets"]),
            "sheets": [
                {
                    "name": sheet["name"],
                    "table": sheet["table"],
                    "columns": sheet["columns"],
                    "row_count": len(sheet["rows"]),
                    "preview": sheet["rows"][:5],
                }
                for sheet in record["sheets"]
            ],
        }

    def payload(
        self, bot: dict[str, Any], *, admin: bool = False,
        principal: AuthenticatedPrincipal | None = None,
    ) -> dict[str, Any]:
        result = dict(bot)
        workbooks = [self.workbook(value) for value in bot.get("workbook_ids", [])]
        if bot.get("personal_uploads"):
            workbooks = self.personal_workbooks(bot["id"], principal.user_id) if principal else []
            result["workbook_ids"] = [book["id"] for book in workbooks]
            result["workbooks"] = [self.workbook_summary(value) for value in workbooks]
            result.pop("user_ids", None)
            result.pop("roles", None)
            result["upload_limits"] = {
                "files": MAX_WORKBOOKS, "bytes": MAX_UPLOAD_BYTES, "sheets": MAX_WORKBOOK_SHEETS,
            }
            return result
        if admin:
            result["workbooks"] = [self.workbook_summary(value) for value in workbooks]
        else:
            result.pop("user_ids", None)
            result.pop("roles", None)
            result["workbooks"] = [
                {
                    "id": value["id"],
                    "filename": value["filename"],
                    "row_count": sum(len(sheet["rows"]) for sheet in value["sheets"]),
                }
                for value in workbooks
            ]
        return result


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _scalar(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)[:2000]


def _behavior_workbook() -> dict[str, Any]:
    rows = []
    for month in range(1, 10):
        for ri, region in enumerate(("华东", "华南", "华北")):
            for ci, channel in enumerate(("企业微信", "官方网站", "线上活动")):
                visits = 9000 + month * 650 + ri * 1100 + ci * 1700
                active = round(visits * (0.56 + ci * 0.05 + month * 0.008))
                rate = 0.19 + ci * 0.025 + month * 0.002
                if region == "华南" and channel == "线上活动" and month >= 8:
                    rate *= 0.62
                rows.append(
                    [
                        f"2026-{month:02d}-01",
                        region,
                        channel,
                        visits,
                        active,
                        round(active * rate),
                        round(active * (0.38 + month * 0.006)),
                    ]
                )
    return {
        "id": "workbook_behavior_sample",
        "filename": "用户行为数据_样例.xlsx",
        "bytes": 0,
        "sample": True,
        "created_at": "2026-10-27T00:00:00+00:00",
        "sheets": [
            {
                "name": "用户行为",
                "table": "wb_behavior_sample",
                "columns": ["月份", "区域", "渠道", "访问人数", "活跃用户", "转化用户", "复访用户"],
                "rows": rows,
            }
        ],
    }
