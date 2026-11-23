"""Run a workbook SELECT in a private PostgreSQL session using a temp-only role."""
from __future__ import annotations

import hashlib
from decimal import Decimal

import psycopg
from psycopg import sql
from sqlglot import exp

from xiaoying_quick.shared.errors import ValidationFailed


_FUNCTIONS = frozenset("""
    ABS AVG CAST CEIL CEILING COALESCE CONCAT CONCAT_WS COUNT CURRENT_DATE
    CURRENT_TIMESTAMP DATE DATE_ADD DATE_DIFF DATE_SUB DATE_TRUNC DENSE_RANK
    EXTRACT FIRST_VALUE FLOOR GREATEST IF IIF IFNULL INSTR LAG LAST_VALUE LEAD
    LEAST LENGTH LOWER LTRIM MAX MIN MOD NULLIF NTILE PERCENT_RANK POWER RANK
    REPLACE ROUND ROW_NUMBER RTRIM SIGN SQRT STRFTIME STR_POSITION STR_TO_DATE
    STR_TO_TIME SUBSTRING SUBSTR SUM TIME_TO_STR TIME_STR_TO_TIME TIMESTAMP_TRUNC
    TRIM TRUNC UPPER GROUP_CONCAT CASE AND OR
""".split())


def _identifier(name):
    # PostgreSQL limits identifiers to 63 bytes. Long Excel headers can share a prefix.
    return name if len(name.encode()) <= 63 else "col_" + hashlib.sha256(name.encode()).hexdigest()[:48]


def query_workbook(dsn, sheets, statement, max_rows):
    for node in statement.walk():
        if isinstance(node, (exp.DDL, exp.DML, exp.Into, exp.Lock, exp.Command, exp.Dot)):
            raise ValidationFailed("工作簿仅支持只读分析表达式")
        if isinstance(node, exp.Table) and (node.db or node.catalog):
            raise ValidationFailed("只能查询当前工作簿的临时表")
        if isinstance(node, exp.Func):
            name = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
            if name.upper() not in _FUNCTIONS:
                raise ValidationFailed(f"工作簿不支持此分析函数：{name}")
    def shorten(node):
        if isinstance(node, exp.Identifier) and len(node.name.encode()) > 63:
            return exp.to_identifier(_identifier(node.name), quoted=True)
        return node
    query = statement.transform(shorten).sql(dialect="postgres")
    originals = {_identifier(c): c for sheet in sheets for c in sheet["columns"]}
    with psycopg.connect(dsn, connect_timeout=5) as db:
        for sheet in sheets:
            names = sheet["columns"]
            table = sql.Identifier(_identifier(sheet["table"]))
            definitions = []
            numeric = []
            for idx, name in enumerate(names):
                values = (row[idx] for row in sheet["rows"] if row[idx] is not None)
                first = next(values, None)
                is_numeric = isinstance(first, (int, float)) and all(isinstance(v, (int, float)) for v in values)
                numeric.append(is_numeric)
                kind = sql.SQL("DOUBLE PRECISION" if is_numeric else "TEXT")
                definitions.append(sql.SQL("{} {}").format(sql.Identifier(_identifier(name)), kind))
            db.execute(sql.SQL("CREATE TEMP TABLE {} ({})").format(table, sql.SQL(", ").join(definitions)))
            with db.cursor() as cursor, cursor.copy(sql.SQL("COPY {} FROM STDIN").format(table)) as writer:
                for row in sheet["rows"]:
                    writer.write_row([None if v is None else float(v) if n else str(v) for v, n in zip(row, numeric)])
        db.commit()
        db.execute("SET TRANSACTION READ ONLY")
        db.execute("SET LOCAL search_path = pg_temp, pg_catalog")
        db.execute("SET LOCAL statement_timeout = '8s'")
        with db.cursor(name="workbook_result") as cursor:
            cursor.execute(query)
            fetched = cursor.fetchmany(max_rows + 1)
            columns = [originals.get(item.name, item.name) for item in cursor.description]
            rows = [[float(v) if isinstance(v, Decimal) else v for v in row] for row in fetched[:max_rows]]
        return columns, rows, len(fetched) > max_rows
