"""Local schema, field recall and read-only query against a configured data source.

This is the VPN-free path: inspect selected tables, match a user query to
columns/comments, probe distinct values, and run SELECT against SQLAlchemy.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.pool import NullPool
from sqlglot.errors import ParseError
from sqlglot.expressions import CTE, Table
from sqlglot.optimizer import optimize as sqlglot_optimize
from sqlglot.schema import MappingSchema

from xiaoying_quick.modules.data_sources.contracts import (
    DataSourceDialect,
    DataSourceRecord,
    DataSourceRevision,
    DataSourceState,
)
from xiaoying_quick.modules.data_sources.ports import DataSourceRepository, SecretStore

from .sqlalchemy_adapter import (
    SqlAlchemyConnectionProbe,
    SqlAlchemyReadOnlyRunner,
    build_runtime_url,
)

_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "for",
        "in",
        "on",
        "to",
        "and",
        "or",
        "的",
        "了",
        "是",
        "和",
        "与",
        "在",
        "有",
        "为",
        "及",
        "等",
        "个",
        "吗",
        "呢",
        "啊",
        "多少",
        "什么",
        "怎么",
        "请问",
        "一下",
    }
)
_METRIC_NAME_HINTS = (
    "sales_val",
    "sales_vol",
    "amount",
    "target_val",
    "_qty",
    "_cnt",
    "_count",
    "ratio",
    "rate",
)
_OUTPUT_LIMIT = 12_000


class LocalSourceError(RuntimeError):
    """Safe failure shown to the model when the local catalog cannot run."""


@dataclass(frozen=True)
class ColumnInfo:
    table: str
    name: str
    data_type: str
    comment: str


@dataclass(frozen=True)
class TableInfo:
    name: str
    comment: str
    columns: tuple[ColumnInfo, ...]


@dataclass(frozen=True)
class SchemaCatalog:
    database: str
    dialect: str
    tables: tuple[TableInfo, ...]

    def sqlglot_mapping(self) -> dict[str, dict[str, str]]:
        return {
            table.name: {
                column.name: (column.data_type or "UNKNOWN") for column in table.columns
            }
            for table in self.tables
        }

    def format_ddl(self) -> str:
        if not self.tables:
            return "（当前没有已勾选的表）"
        blocks = [f"数据库：{self.database}  方言：{self.dialect}"]
        for table in self.tables:
            title = f"-- {table.name}"
            if table.comment:
                title += f"  {table.comment}"
            lines = [title, f"CREATE TABLE {table.name} ("]
            width = max((len(column.name) for column in table.columns), default=1)
            for index, column in enumerate(table.columns):
                comma = "," if index < len(table.columns) - 1 else ""
                comment = f"  -- {column.comment}" if column.comment else ""
                lines.append(
                    f"  {column.name.ljust(width)} {column.data_type or 'UNKNOWN'}{comma}{comment}"
                )
            lines.append(");")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)[:_OUTPUT_LIMIT]


def sqlglot_dialect(dialect: str) -> str:
    if dialect in {"postgresql", "postgres"}:
        return "postgres"
    if dialect in {"mysql", "sqlite"}:
        return dialect
    return "mysql"


def referenced_tables(sql: str, dialect: str) -> set[str]:
    parsed = sqlglot.parse_one(sql, read=sqlglot_dialect(dialect))
    cte_names = {cte.alias_or_name.casefold() for cte in parsed.find_all(CTE) if cte.alias_or_name}
    names: set[str] = set()
    for table in parsed.find_all(Table):
        name = table.name
        if name and name.casefold() not in cte_names:
            names.add(name.casefold())
    return names


def validate_sql_against_schema(
    sql: str,
    *,
    schema: SchemaCatalog,
    dialect: str,
) -> tuple[bool, tuple[str, ...]]:
    """SQLGlot syntax + column qualify, matching the text-to-sql-agent loop."""

    if not sql.strip():
        return False, ("缺少 SQL。",)
    read = sqlglot_dialect(dialect)
    try:
        expression = sqlglot.parse_one(sql, read=read)
    except (ParseError, ValueError) as exc:
        return False, (f"语法错误：{exc}",)
    kind = (expression.key or "").casefold()
    if kind != "select":
        return False, ("只允许只读的 SELECT 语句。",)
    mapping = schema.sqlglot_mapping()
    allowed = {name.casefold() for name in mapping}
    try:
        used = referenced_tables(sql, dialect)
    except (ParseError, ValueError) as exc:
        return False, (f"无法解析表名：{exc}",)
    unknown = sorted(used - allowed)
    if unknown:
        return False, (f"SQL 引用了未勾选或不存在的表：{', '.join(unknown)}。",)
    if mapping:
        try:
            sqlglot_optimize(
                expression,
                schema=MappingSchema(mapping, dialect=read),
                dialect=read,
                validate_qualify_columns=True,
            )
        except Exception as exc:  # noqa: BLE001 — validation is the product
            return False, (str(exc)[:400],)
    return True, ()


def query_terms(query: str) -> tuple[str, ...]:
    seen: list[str] = []

    def add(term: str) -> None:
        value = term.strip()
        if not value or value.casefold() in _STOPWORDS:
            return
        if value not in seen:
            seen.append(value)

    text = query or ""
    add(text)
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9_]*|[0-9]{4}", text):
        add(match.group())
    for match in re.finditer(r"[\u4e00-\u9fff]+", text):
        run = match.group()
        add(run)
        for size in (2, 3, 4):
            if len(run) < size:
                continue
            for index in range(0, len(run) - size + 1):
                add(run[index : index + size])
    return tuple(seen[:40])


def is_dimension_column(column: ColumnInfo) -> bool:
    type_l = (column.data_type or "").casefold()
    name = column.name.casefold()
    if any(token in type_l for token in ("decimal", "numeric", "float", "double", "real")):
        return False
    if any(token in type_l for token in ("date", "time", "bool")):
        return False
    if name.endswith("_id") or name in {"id", "pk"}:
        return False
    if any(hint in name for hint in _METRIC_NAME_HINTS):
        return False
    return True


def score_column(term: str, table: TableInfo, column: ColumnInfo) -> int:
    needle = term.casefold()
    column_name = column.name.casefold()
    table_name = table.name.casefold()
    comment = (column.comment or "").casefold()
    table_comment = (table.comment or "").casefold()
    if needle == column_name:
        return 100
    if needle in column_name or column_name in needle:
        return 80
    if comment and needle in comment:
        return 70
    if needle in table_name or (table_comment and needle in table_comment):
        return 40
    return 0


def format_field_recall(hits: Sequence[dict[str, Any]], *, query: str) -> str:
    if not hits:
        return f"未根据「{query}」匹配到字段。先 inspect_schema 核对表结构，或换一个更短的词。"
    lines = [f"字段召回（query={query}）：", "知识词条："]
    for hit in hits:
        meaning = hit.get("comment") or hit.get("table_comment") or hit.get("data_type") or ""
        suffix = f"（{meaning}）" if meaning else ""
        lines.append(f"- {hit['term']}：{hit['table']}.{hit['column']}{suffix}")
    lines.append("")
    lines.append("字段：")
    for hit in hits:
        comment = f"  {hit['comment']}" if hit.get("comment") else ""
        lines.append(
            f"- {hit['table']}.{hit['column']}：{hit.get('data_type') or 'UNKNOWN'}{comment}"
        )
    return "\n".join(lines)[:_OUTPUT_LIMIT]


def format_value_recall(groups: Sequence[dict[str, Any]], *, query: str) -> str:
    if not groups:
        return f"未根据「{query}」召回到字段取值。不要猜枚举；需要口径时 ask_user。"
    lines = [f"取值召回（query={query}）：", "候选值："]
    for group in groups:
        values = group.get("values") or []
        shown = "、".join(str(item) for item in values[:8])
        extra = f" 等{len(values)}个" if len(values) > 8 else ""
        lines.append(f"- {group['table']}.{group['column']}：{shown}{extra}")
    return "\n".join(lines)[:_OUTPUT_LIMIT]


class LocalSourceGateway:
    """Resolve the active data source and run inspect / recall / SELECT locally."""

    def __init__(
        self,
        *,
        repository: DataSourceRepository,
        secrets: SecretStore,
        runner: SqlAlchemyReadOnlyRunner | None = None,
    ) -> None:
        self._repository = repository
        self._secrets = secrets
        self._runner = runner or SqlAlchemyReadOnlyRunner()

    def available(self) -> bool:
        return self.bound() is not None

    def bound(self) -> tuple[DataSourceRevision, str | None] | None:
        record = self._active_record()
        if record is None:
            return None
        revision = self._current_revision(record)
        if revision is None:
            return None
        password = self._secrets.get(record.secret_ref) if record.secret_ref else None
        return revision, password

    def inspect(self, tables: Sequence[str] | None = None) -> SchemaCatalog:
        bound = self.bound()
        if bound is None:
            raise LocalSourceError("请先在工具目录配置「数据库查询」连接并勾选表。")
        revision, password = bound
        return load_schema_catalog(revision, password, tables=tables)

    def execute(
        self, sql: str, max_rows: int
    ) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...], bool, int]:
        bound = self.bound()
        if bound is None:
            raise LocalSourceError("请先在工具目录配置「数据库查询」连接并勾选表。")
        revision, password = bound
        allowed = {item.casefold() for item in revision.allowed_objects}
        if allowed:
            try:
                used = referenced_tables(sql, revision.dialect.value)
            except (ParseError, ValueError) as exc:
                raise LocalSourceError(f"SQL 无法解析：{exc}") from exc
            unknown = sorted(used - allowed)
            if unknown:
                raise LocalSourceError(
                    "SQL 引用了未勾选的表："
                    + "、".join(unknown)
                    + "。请只查询配置里勾选的表，或到工具目录补选。"
                )
        return self._runner.execute(
            revision=revision, password=password, sql=sql, max_rows=max_rows
        )

    def recall_fields(self, query: str, *, limit: int = 16) -> list[dict[str, Any]]:
        catalog = self.inspect()
        terms = query_terms(query)
        if not terms and query.strip():
            terms = (query.strip()[:40],)
        best: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
        for term in terms:
            for table in catalog.tables:
                for column in table.columns:
                    points = score_column(term, table, column)
                    if points <= 0:
                        continue
                    key = (table.name, column.name)
                    current = best.get(key)
                    if current is not None and current[0] >= points:
                        continue
                    best[key] = (
                        points,
                        {
                            "term": term,
                            "table": table.name,
                            "column": column.name,
                            "data_type": column.data_type,
                            "comment": column.comment,
                            "table_comment": table.comment,
                            "score": points,
                        },
                    )
        scored = sorted(
            best.values(),
            key=lambda item: (-item[0], item[1]["table"], item[1]["column"]),
        )
        return [item[1] for item in scored[:limit]]

    def recall_values(
        self,
        query: str,
        *,
        table: str | None = None,
        column: str | None = None,
        max_values: int = 24,
    ) -> list[dict[str, Any]]:
        catalog = self.inspect()
        terms = query_terms(query)
        if not terms and query.strip():
            terms = (query.strip()[:40],)
        terms = tuple(sorted(terms, key=lambda item: (len(item) > 6, len(item))))[:12]
        targets = _value_targets(catalog, table=table, column=column, field_hits=None)
        if table is None and column is None:
            hits = self.recall_fields(query, limit=8)
            targets = _value_targets(catalog, table=None, column=None, field_hits=hits)
            if not targets:
                targets = [
                    (item, col)
                    for item in catalog.tables
                    for col in item.columns
                    if is_dimension_column(col)
                ][:6]
        bound = self.bound()
        assert bound is not None
        revision, password = bound
        groups: list[dict[str, Any]] = []
        for table_info, column_info in targets[:8]:
            values = _probe_values(
                revision,
                password,
                table=table_info.name,
                column=column_info.name,
                terms=terms,
                max_values=max(1, min(max_values, 100)),
            )
            if values:
                groups.append(
                    {
                        "table": table_info.name,
                        "column": column_info.name,
                        "comment": column_info.comment,
                        "values": values,
                    }
                )
        return groups

    def _active_record(self) -> DataSourceRecord | None:
        records = self._repository.list()
        active = [item for item in records if item.state is DataSourceState.ACTIVE]
        if active:
            named = [item for item in active if item.name == "智能体查询库"]
            return named[0] if named else active[0]
        return records[0] if records else None

    def _current_revision(self, record: DataSourceRecord) -> DataSourceRevision | None:
        if record.current_revision <= 0:
            return None
        for revision in self._repository.list_revisions(record.id):
            if revision.revision == record.current_revision:
                return revision
        return None


def load_schema_catalog(
    revision: DataSourceRevision,
    password: str | None,
    tables: Sequence[str] | None = None,
) -> SchemaCatalog:
    url = build_runtime_url(revision, password)
    engine = create_engine(
        url,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args=SqlAlchemyConnectionProbe._connect_args(revision),
    )
    wanted = {item.casefold() for item in tables} if tables else None
    allowed = {item.casefold() for item in revision.allowed_objects}
    try:
        with engine.connect() as connection:
            SqlAlchemyConnectionProbe._enforce_read_only(
                connection, revision.dialect, revision.query_timeout_seconds
            )
            inspector = inspect(connection)
            schema = revision.schema or None
            try:
                names = sorted(
                    set(inspector.get_table_names(schema=schema))
                    | set(inspector.get_view_names(schema=schema))
                )
            except (OperationalError, ProgrammingError):
                names = list(_show_tables(connection, revision))
            selected = []
            for name in names:
                key = name.casefold()
                if allowed and key not in allowed:
                    continue
                if wanted is not None and key not in wanted:
                    continue
                selected.append(name)
            catalog_tables: list[TableInfo] = []
            for name in selected:
                comment = _table_comment(inspector, name, schema)
                columns = tuple(_columns_for(inspector, connection, revision, name, schema))
                catalog_tables.append(TableInfo(name=name, comment=comment, columns=columns))
            return SchemaCatalog(
                database=revision.selected_database,
                dialect=revision.dialect.value,
                tables=tuple(catalog_tables),
            )
    finally:
        engine.dispose()


def _columns_for(
    inspector: Any,
    connection: Any,
    revision: DataSourceRevision,
    table: str,
    schema: str | None,
) -> list[ColumnInfo]:
    try:
        raw = inspector.get_columns(table, schema=schema)
        return [
            ColumnInfo(
                table=table,
                name=str(item.get("name") or ""),
                data_type=str(item.get("type") or ""),
                comment=str(item.get("comment") or ""),
            )
            for item in raw
            if item.get("name")
        ]
    except (OperationalError, ProgrammingError):
        quoted = table.replace("`", "")
        rows = connection.exec_driver_sql(f"SHOW FULL COLUMNS FROM `{quoted}`").fetchall()
        return [
            ColumnInfo(
                table=table,
                name=str(row[0]),
                data_type=str(row[1]) if len(row) > 1 else "",
                comment=str(row[8]) if len(row) > 8 else "",
            )
            for row in rows
        ]


def _table_comment(inspector: Any, table: str, schema: str | None) -> str:
    try:
        info = inspector.get_table_comment(table, schema=schema)
    except Exception:
        return ""
    if isinstance(info, dict):
        return str(info.get("text") or "")
    return str(info or "")


def _show_tables(connection: Any, revision: DataSourceRevision) -> tuple[str, ...]:
    schema = revision.selected_database or revision.schema
    if schema:
        rows = connection.exec_driver_sql(f"SHOW TABLES FROM `{schema}`").fetchall()
    else:
        rows = connection.exec_driver_sql("SHOW TABLES").fetchall()
    return tuple(sorted({str(row[0]) for row in rows}))


def _value_targets(
    catalog: SchemaCatalog,
    *,
    table: str | None,
    column: str | None,
    field_hits: Sequence[dict[str, Any]] | None,
) -> list[tuple[TableInfo, ColumnInfo]]:
    by_name = {item.name.casefold(): item for item in catalog.tables}
    if table and column:
        found = by_name.get(table.casefold())
        if found is None:
            raise LocalSourceError(f"表 {table} 不在已勾选范围内。")
        col = next(
            (item for item in found.columns if item.name.casefold() == column.casefold()),
            None,
        )
        if col is None:
            raise LocalSourceError(f"字段 {table}.{column} 不存在。")
        return [(found, col)]
    if field_hits:
        targets: list[tuple[TableInfo, ColumnInfo]] = []
        for hit in field_hits:
            found = by_name.get(str(hit.get("table") or "").casefold())
            if found is None:
                continue
            col = next(
                (
                    item
                    for item in found.columns
                    if item.name.casefold() == str(hit.get("column") or "").casefold()
                ),
                None,
            )
            if col is not None and is_dimension_column(col):
                targets.append((found, col))
        return targets
    return []


def _probe_values(
    revision: DataSourceRevision,
    password: str | None,
    *,
    table: str,
    column: str,
    terms: Sequence[str],
    max_values: int,
) -> list[str]:
    dialect = revision.dialect
    qtable = _quote(table, dialect)
    qcolumn = _quote(column, dialect)
    casted = _cast_text(qcolumn, dialect)
    clauses = []
    params: dict[str, Any] = {}
    for index, term in enumerate(terms[:6]):
        key = f"p{index}"
        clauses.append(f"{casted} LIKE :{key}")
        params[key] = _like_pattern(term)
    where = f" WHERE ({' OR '.join(clauses)})" if clauses else ""
    sql = f"SELECT DISTINCT {qcolumn} AS v FROM {qtable}{where} LIMIT {int(max_values)}"
    url = build_runtime_url(revision, password)
    engine = create_engine(
        url,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args=SqlAlchemyConnectionProbe._connect_args(revision),
    )
    try:
        with engine.connect() as connection:
            SqlAlchemyConnectionProbe._enforce_read_only(
                connection, revision.dialect, revision.query_timeout_seconds
            )
            rows = connection.execute(text(sql), params).fetchall()
        values: list[str] = []
        for row in rows:
            cell = row[0]
            if cell is None:
                continue
            text_value = str(cell).strip()
            if text_value and text_value not in values:
                values.append(text_value)
        return values[:max_values]
    except Exception as exc:
        raise LocalSourceError(f"取值探测失败：{type(exc).__name__}") from exc
    finally:
        engine.dispose()


def _quote(name: str, dialect: DataSourceDialect) -> str:
    cleaned = re.sub(r"[^\w.\u4e00-\u9fff]", "", name)
    if not cleaned:
        raise LocalSourceError("非法标识符")
    if dialect is DataSourceDialect.MYSQL:
        return f"`{cleaned}`"
    return f'"{cleaned}"'


def _cast_text(quoted: str, dialect: DataSourceDialect) -> str:
    if dialect is DataSourceDialect.POSTGRESQL:
        return f"{quoted}::text"
    if dialect is DataSourceDialect.SQLITE:
        return f"CAST({quoted} AS TEXT)"
    return f"CAST({quoted} AS CHAR)"


def _like_pattern(term: str) -> str:
    cleaned = re.sub(r"[%_\\]", "", term)
    return f"%{cleaned}%"
