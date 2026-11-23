from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal

from xiaoying_quick.infrastructure.source_db.sqlalchemy_adapter import (
    SqlAlchemyConnectionProbe,
    SqlAlchemyReadOnlyRunner,
    _json_cell,
)
from xiaoying_quick.modules.data_sources.contracts import (
    DataSourceDialect,
    DataSourceRevision,
    DataSourceSslMode,
)


def revision(path) -> DataSourceRevision:
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
        allowed_objects=("sales",),
        allowed_schemas=(),
        query_timeout_seconds=3,
        max_rows=2,
        allow_private_network=True,
        schema_snapshot_id=None,
        created_by="admin",
        created_at=datetime.now(timezone.utc),
    )


def test_sqlite_probe_and_read_only_runner(tmp_path) -> None:
    db = tmp_path / "source.db"
    connection = sqlite3.connect(db)
    connection.execute("create table sales (brand text, value integer)")
    connection.executemany("insert into sales values (?, ?)", [("A", 1), ("B", 2), ("C", 3)])
    connection.commit()
    connection.close()

    rev = revision(db)
    result = SqlAlchemyConnectionProbe().test(rev, None)
    assert result.ok is True
    assert result.read_only is True
    assert result.schema_snapshot is not None
    assert "sales" in result.schema_snapshot.objects

    columns, rows, truncated, _ = SqlAlchemyReadOnlyRunner().execute(
        revision=rev,
        password=None,
        sql="select brand, value from sales order by value",
        max_rows=2,
    )
    assert columns == ("brand", "value")
    assert rows == (("A", 1), ("B", 2))
    assert truncated is True


def test_json_cell_converts_decimal_and_date() -> None:
    assert _json_cell(Decimal("3960000.0000")) == 3960000
    assert _json_cell(Decimal("12.5")) == 12.5
    assert _json_cell(date(2026, 7, 1)) == "2026-07-01"
    assert _json_cell(None) is None
    assert _json_cell("上海") == "上海"
