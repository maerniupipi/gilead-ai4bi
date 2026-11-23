"""把本机 AgentLoop 导出成 AnalyticDB 可执行的 SQL。

只导出控制面库 AgentLoop（全表结构 + 账号/模型/知识/数据源）。
跳过运行时大表：run_artifacts、run_events、chat、jobs 等。
不导出 AI_CVRM。

用法（在 backend_v2 目录）：

  .venv/bin/python tools/dump_sae_sql.py

导入到 SAE：

  curl -X POST https://<SAE域名>/api/v2/system/import-sql \\
    -H "X-Provision-Token: ${PROVISION_TOKEN}" \\
    -F "file=@dist/sae-sql/02_AgentLoop.sql"
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "dist" / "sae-sql"

SKIP_DATA = frozenset(
    {
        "run_artifacts",
        "run_events",
        "runs",
        "facts",
        "dataset_evidence",
        "chat_sessions",
        "chat_messages",
        "clarification_cases",
        "session_domain_patches",
        "quick_jobs",
        "audit_events",
    }
)

ADB_SOURCE_URL = "mysql+pymysql://amv-uf63v21774ve76d4400000889.ads.aliyuncs.com:3306"
ADB_SOURCE_USER = "adbmysqladmin"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export local MySQL as AnalyticDB SQL")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default=os.environ.get("MYSQL_PASSWORD"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--all-data",
        action="store_true",
        help="Also dump AgentLoop runtime tables (still skips run_artifacts)",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    conn = pymysql.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        charset="utf8mb4",
        cursorclass=DictCursor,
    )
    try:
        agent_path = args.out / "02_AgentLoop.sql"
        skip = set() if args.all_data else set(SKIP_DATA)
        skip.add("run_artifacts")
        agent_sql = dump_database(conn, "AgentLoop", skip_data=skip)
        agent_sql += _rewire_source_sql()
        agent_path.write_text(agent_sql, encoding="utf-8")
        stale = args.out / "01_AI_CVRM.sql"
        if stale.exists():
            stale.unlink()
        print("wrote", agent_path, agent_path.stat().st_size, "bytes")
        print("导入接口 POST /api/v2/system/import-sql ，form 字段 file")
    finally:
        conn.close()


def dump_database(
    conn: pymysql.connections.Connection, schema: str, *, skip_data: frozenset[str] | set[str]
) -> str:
    lines = [
        f"-- {schema} dump for Aliyun AnalyticDB MySQL",
        "SET NAMES utf8mb4;",
        "SET FOREIGN_KEY_CHECKS=0;",
        f"CREATE DATABASE IF NOT EXISTS `{schema}` "
        "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
        f"USE `{schema}`;",
        "",
    ]
    with conn.cursor() as cursor:
        cursor.execute(f"SHOW TABLES FROM `{schema}`")
        tables = [str(next(iter(row.values()))) for row in cursor.fetchall()]
        for table in tables:
            cursor.execute(f"SHOW CREATE TABLE `{schema}`.`{table}`")
            created = cursor.fetchone()
            ddl = str(created.get("Create Table") or next(iter(created.values())))
            lines.append(sanitize_create(ddl) + ";")
            lines.append("")
            if table in skip_data:
                lines.append(f"-- skip data: {table}")
                lines.append("")
                continue
            lines.append(f"DELETE FROM `{table}`;")
            lines.extend(dump_rows(cursor, schema, table))
            lines.append("")
    lines.append("SET FOREIGN_KEY_CHECKS=1;")
    return "\n".join(lines) + "\n"


def dump_rows(cursor: DictCursor, schema: str, table: str) -> list[str]:
    cursor.execute(f"SELECT * FROM `{schema}`.`{table}`")
    rows = cursor.fetchall()
    if not rows:
        return [f"-- {table}: 0 rows"]
    columns = list(rows[0].keys())
    col_sql = ", ".join(f"`{name}`" for name in columns)
    lines = [f"-- {table}: {len(rows)} rows"]
    batch: list[str] = []
    for row in rows:
        values = ", ".join(sql_literal(row[name]) for name in columns)
        batch.append(f"({values})")
        if len(batch) >= 80:
            lines.append(f"INSERT INTO `{table}` ({col_sql}) VALUES")
            lines.append(",\n".join(batch) + ";")
            batch = []
    if batch:
        lines.append(f"INSERT INTO `{table}` ({col_sql}) VALUES")
        lines.append(",\n".join(batch) + ";")
    return lines


_FK_ACTION = r"(?:SET NULL|SET DEFAULT|NO ACTION|CASCADE|RESTRICT)"


def sanitize_create(ddl: str) -> str:
    ddl = re.sub(
        r",\s*CONSTRAINT `[^`]+` FOREIGN KEY \([^)]+\) REFERENCES `[^`]+` \([^)]+\)"
        rf"(?:\s+ON DELETE {_FK_ACTION})?(?:\s+ON UPDATE {_FK_ACTION})?",
        "",
        ddl,
        flags=re.IGNORECASE,
    )
    ddl = re.sub(r"\s*ENGINE=\w+", "", ddl, flags=re.IGNORECASE)
    ddl = re.sub(r"\s*ROW_FORMAT=\w+", "", ddl, flags=re.IGNORECASE)
    ddl = re.sub(r"\s*AUTO_INCREMENT=\d+", "", ddl, flags=re.IGNORECASE)
    ddl = re.sub(r"\bMEDIUMTEXT\b", "TEXT", ddl, flags=re.IGNORECASE)
    ddl = re.sub(r"\bLONGTEXT\b", "TEXT", ddl, flags=re.IGNORECASE)
    ddl = ddl.replace("utf8mb4_0900_ai_ci", "utf8mb4_unicode_ci")
    ddl = ddl.replace("utf8mb4_0900_bin", "utf8mb4_bin")
    ddl = re.sub(r"COLLATE=utf8mb4_unicode_ci", "COLLATE utf8mb4_unicode_ci", ddl)
    if "IF NOT EXISTS" not in ddl.upper():
        ddl = ddl.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
    return ddl.rstrip().rstrip(";")


def sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return "'" + value.strftime("%Y-%m-%d %H:%M:%S") + "'"
    if isinstance(value, date):
        return "'" + value.isoformat() + "'"
    if isinstance(value, (bytes, bytearray, memoryview)):
        blob = bytes(value)
        return "0x" + blob.hex() if blob else "''"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    escaped = text.replace("\\", "\\\\").replace("'", "''")
    return "'" + escaped + "'"


def _rewire_source_sql() -> str:
    return f"""
-- 把本机 127.0.0.1 数据源改成 SAE AnalyticDB。
-- 密码不在这张表里，在 SAE 的 secrets.json / 数据源页里保存 ADB 密码。
UPDATE `data_sources`
SET `connection_url` = '{ADB_SOURCE_URL}',
    `username` = '{ADB_SOURCE_USER}'
WHERE `selected_database` = 'AI_CVRM';
"""


if __name__ == "__main__":
    main()
