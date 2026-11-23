from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from xiaoying_quick.infrastructure.source_db.local_catalog import (
    LocalSourceGateway,
    format_field_recall,
    format_value_recall,
    load_schema_catalog,
    query_terms,
    referenced_tables,
    validate_sql_against_schema,
)
from xiaoying_quick.infrastructure.source_db.sqlalchemy_adapter import SqlAlchemyReadOnlyRunner
from xiaoying_quick.modules.data_sources.contracts import (
    DataSourceDialect,
    DataSourceRecord,
    DataSourceRevision,
    DataSourceSslMode,
    DataSourceState,
)


def _revision(path, objects=("sales",)) -> DataSourceRevision:
    return DataSourceRevision(
        id="rev-1",
        data_source_id="ds-1",
        revision=1,
        connection_url="sqlite://",
        username=None,
        selected_database=str(path),
        schema=None,
        dialect=DataSourceDialect.SQLITE,
        ssl_mode=DataSourceSslMode.DISABLE,
        secret_ref=None,
        allowed_objects=objects,
        allowed_schemas=(),
        query_timeout_seconds=3,
        max_rows=50,
        allow_private_network=True,
        schema_snapshot_id=None,
        created_by="admin",
        created_at=datetime.now(timezone.utc),
    )


def _seed(path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "create table sales (brand text, channel text, sales_val integer)"
    )
    connection.executemany(
        "insert into sales values (?, ?, ?)",
        [("倍择瑞", "院外", 10), ("倍择瑞", "院内", 7), ("其他", "院外", 1)],
    )
    connection.commit()
    connection.close()


def test_query_terms_keeps_chinese_and_identifiers() -> None:
    terms = query_terms("倍择瑞院外今年销量")
    assert "院外" in terms
    assert "倍择瑞" in terms
    assert "brand" in query_terms("filter brand")


def test_referenced_tables_ignores_cte() -> None:
    sql = "WITH x AS (SELECT 1 AS a) SELECT a FROM x JOIN sales ON 1=1"
    assert referenced_tables(sql, "sqlite") == {"sales"}


def test_inspect_and_field_value_recall(tmp_path) -> None:
    db = tmp_path / "source.db"
    _seed(db)
    revision = _revision(db)
    catalog = load_schema_catalog(revision, None)
    assert [table.name for table in catalog.tables] == ["sales"]
    assert {column.name for column in catalog.tables[0].columns} >= {"brand", "channel"}

    class Repo:
        def list(self):
            return [
                DataSourceRecord(
                    id="ds-1",
                    name="智能体查询库",
                    connection_url="sqlite://",
                    username=None,
                    selected_database=str(db),
                    schema=None,
                    dialect=DataSourceDialect.SQLITE,
                    ssl_mode=DataSourceSslMode.DISABLE,
                    state=DataSourceState.ACTIVE,
                    current_revision=1,
                    secret_ref=None,
                    allowed_objects=("sales",),
                    allowed_schemas=(),
                    query_timeout_seconds=3,
                    max_rows=50,
                    allow_private_network=True,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            ]

        def list_revisions(self, data_source_id):
            del data_source_id
            return [revision]

        def get(self, data_source_id):
            return self.list()[0]

    class Secrets:
        def get(self, secret_ref):
            del secret_ref
            return None

    gateway = LocalSourceGateway(repository=Repo(), secrets=Secrets(), runner=SqlAlchemyReadOnlyRunner())
    hits = gateway.recall_fields("brand 院外")
    assert any(item["column"] == "brand" for item in hits)
    rendered = format_field_recall(hits, query="brand")
    assert "brand" in rendered

    groups = gateway.recall_values("院外", table="sales", column="channel")
    assert groups
    assert "院外" in groups[0]["values"]
    assert "候选值" in format_value_recall(groups, query="院外")

    columns, rows, truncated, _ = gateway.execute(
        "select brand, channel from sales where channel = '院外' order by brand", 10
    )
    assert "brand" in columns
    assert truncated is False
    assert len(rows) == 2


def test_validate_sql_rejects_unknown_table(tmp_path) -> None:
    db = tmp_path / "source.db"
    _seed(db)
    catalog = load_schema_catalog(_revision(db), None)
    ok, errors = validate_sql_against_schema(
        "select * from missing", schema=catalog, dialect="sqlite"
    )
    assert ok is False
    assert any("表" in item or "missing" in item.casefold() for item in errors)


def test_validate_sql_accepts_selected_table(tmp_path) -> None:
    db = tmp_path / "source.db"
    _seed(db)
    catalog = load_schema_catalog(_revision(db), None)
    ok, errors = validate_sql_against_schema(
        "select brand from sales", schema=catalog, dialect="sqlite"
    )
    assert ok is True, errors
