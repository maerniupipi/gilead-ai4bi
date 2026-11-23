"""Apply a dumped SQL script against the application database."""

from __future__ import annotations

import re

from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, ProgrammingError

_SKIP_PREFIXES = (
    "SET ",
    "CREATE DATABASE",
    "USE ",
    "START TRANSACTION",
    "COMMIT",
    "ROLLBACK",
    "LOCK ",
    "UNLOCK ",
)


def split_sql_statements(script: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    in_string = False
    quote = ""
    index = 0
    length = len(script)
    while index < length:
        char = script[index]
        if not in_string and script.startswith("--", index):
            newline = script.find("\n", index)
            index = length if newline < 0 else newline + 1
            continue
        if not in_string and char in {"'", '"', "`"}:
            in_string = True
            quote = char
            buf.append(char)
        elif in_string and char == "\\" and index + 1 < length:
            buf.append(char)
            buf.append(script[index + 1])
            index += 2
            continue
        elif in_string and char == quote:
            if index + 1 < length and script[index + 1] == quote:
                buf.append(char)
                buf.append(char)
                index += 2
                continue
            in_string = False
            quote = ""
            buf.append(char)
        elif not in_string and char == ";":
            text = "".join(buf).strip()
            if text:
                statements.append(text)
            buf = []
        else:
            buf.append(char)
        index += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def should_skip_statement(statement: str) -> bool:
    upper = statement.lstrip().upper()
    return any(upper.startswith(prefix) for prefix in _SKIP_PREFIXES)


def apply_sql_script(engine: Engine, script: str) -> dict[str, object]:
    statements = split_sql_statements(script)
    executed = 0
    skipped = 0
    with engine.begin() as connection:
        for statement in statements:
            if should_skip_statement(statement):
                skipped += 1
                continue
            try:
                connection.exec_driver_sql(statement)
            except (DBAPIError, ProgrammingError) as exc:
                preview = re.sub(r"\s+", " ", statement)[:180]
                orig = getattr(exc, "orig", None)
                detail = str(orig or exc)
                raise RuntimeError(
                    f"SQL 执行失败（已成功 {executed} 条）：{detail} | {preview}"
                ) from exc
            executed += 1
    return {
        "statements": len(statements),
        "executed": executed,
        "skipped": skipped,
    }
