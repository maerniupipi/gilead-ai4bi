"""Explicit, deterministic demo labs backed by an isolated read-only query database."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from xiaoying_quick.infrastructure.source_db.local_catalog import (
    ColumnInfo,
    LocalSourceGateway,
    SchemaCatalog,
    TableInfo,
    load_schema_catalog,
)
from xiaoying_quick.infrastructure.source_db.sqlalchemy_adapter import SqlAlchemyReadOnlyRunner
from xiaoying_quick.modules.data_sources.contracts import (
    DataSourceDialect,
    DataSourceRevision,
    DataSourceSslMode,
)
from xiaoying_quick.modules.labs import CandidateSQL, LabRequest

DEMO_TABLES = {
    "actual": "demo_actual",
    "demand": "demo_demand",
    "ext_simple": "demo_market_simple",
    "ext_complex": "demo_market_complex",
}
_CATALOG = json.loads(Path(__file__).with_name("demo_catalog.json").read_text(encoding="utf-8"))
DEMO_REGIONS: tuple[str, ...] = tuple(_CATALOG["regions"])
DEMO_ITEMS: tuple[str, ...] = tuple(_CATALOG["products"])
DEMO_CHANNELS: tuple[str, ...] = tuple(_CATALOG["channels"])
DEMO_ROW_COUNT = 92_160
DEMO_NOTICE = (
    "当前为演示模式，所有数字来自模拟数据，回答中必须标明“演示数据”。"
    "演示库覆盖2024-10至2026-09，最新月2026-09，4张表共92160行。"
    "实际销售用demo_actual，需求用demo_demand，外部市场用demo_market_simple或"
    "demo_market_complex；amount为销售额（元）、units为销量、target_amount为目标、"
    "market_amount为市场总额。维度有sales_month、region、product、hospital、channel。"
    "演示SQL生成支持按地区/产品/月份/渠道/医院汇总、年月筛选、排名、达成率和市场份额。"
    "未写时间的演示查询默认2026年1–9月；不要将其他业务文档的真实表名用于演示库。"
)
_LOCK = threading.Lock()
_COMMENTS = {
    "sales_month": "月份 YYYY-MM，最新月2026-09",
    "region": "地区：华东、华南、华北、华中、西南、西北",
    "product": "产品名称",
    "hospital": "模拟医院名称",
    "channel": "渠道：院内、院外、零售",
    "units": "销量",
    "amount": "销售额，元；demand表表示需求金额",
    "target_amount": "销售目标金额，元",
    "market_amount": "市场总额，元",
}


def ensure_demo_data(path: Path | None = None) -> Path:
    """Create our versioned dataset once; never touches a configured business source."""
    path = (path or Path("var/demo-labs-v1.sqlite")).resolve()
    with _LOCK:
        if path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        try:
            with sqlite3.connect(temporary) as connection:
                for domain, table in enumerate(DEMO_TABLES.values(), start=1):
                    connection.execute(
                        f"CREATE TABLE {table} (sales_month TEXT, region TEXT, product TEXT, "
                        "hospital TEXT, channel TEXT, units INTEGER, amount REAL, "
                        "target_amount REAL, market_amount REAL)"
                    )
                    rows: list[tuple[Any, ...]] = []
                    for month in range(24):
                        year, month_index = divmod(2024 * 12 + 9 + month, 12)
                        for region_index, region in enumerate(DEMO_REGIONS):
                            for product_index, product in enumerate(DEMO_ITEMS):
                                for hospital in range(20):
                                    units = (
                                        40
                                        + month * 7
                                        + region_index * 13
                                        + product_index * 17
                                        + hospital * 3
                                        + domain * 19
                                    )
                                    amount = round(units * (31.5 + product_index * 11.2), 2)
                                    rows.append(
                                        (
                                            f"{year}-{month_index + 1:02d}",
                                            region,
                                            product,
                                            f"{region}模拟医院{hospital + 1:02d}",
                                            DEMO_CHANNELS[hospital % 3],
                                            units,
                                            amount,
                                            round(amount * (0.85 + hospital % 7 * 0.05), 2),
                                            round(amount * (2.4 + region_index * 0.3), 2),
                                        )
                                    )
                    connection.executemany(f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?,?)", rows)
                    connection.execute(f"CREATE INDEX {table}_month ON {table}(sales_month)")
                connection.execute("PRAGMA user_version = 1")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return path


class DemoSourceGateway(LocalSourceGateway):
    """Reuse the real schema, recall, SQL validation and read-only execution tools."""

    def __init__(self, path: Path) -> None:
        self._runner = SqlAlchemyReadOnlyRunner()
        self._revision = DataSourceRevision(
            id="demo-labs-v1",
            data_source_id="demo-labs-v1",
            revision=1,
            connection_url="sqlite://",
            username=None,
            selected_database=str(ensure_demo_data(path)),
            schema=None,
            dialect=DataSourceDialect.SQLITE,
            ssl_mode=DataSourceSslMode.DISABLE,
            secret_ref=None,
            allowed_objects=tuple(DEMO_TABLES.values()),
            allowed_schemas=(),
            query_timeout_seconds=15,
            max_rows=100_000,
            allow_private_network=False,
            schema_snapshot_id=None,
            created_by="demo",
            created_at=datetime.now(timezone.utc),
        )

    def bound(self) -> tuple[DataSourceRevision, None]:
        return self._revision, None

    def inspect(self, tables: Any = None) -> SchemaCatalog:
        catalog = load_schema_catalog(self._revision, None, tables=tables)
        return SchemaCatalog(
            database="演示数据（隔离模拟库）",
            dialect="sqlite",
            tables=tuple(
                TableInfo(
                    name=table.name,
                    comment="演示数据，非真实业务结果",
                    columns=tuple(
                        ColumnInfo(
                            column.table,
                            column.name,
                            column.data_type,
                            _COMMENTS.get(column.name, ""),
                        )
                        for column in table.columns
                    ),
                )
                for table in catalog.tables
            ),
        )


def get_demo_gateway(path: Path | None = None) -> DemoSourceGateway:
    return DemoSourceGateway(path or Path("var/demo-labs-v1.sqlite"))


class DemoLabPort:
    """An explicit local mock, never a fallback for a failed real provider."""

    supports_controlled_prompt = False

    def __init__(self, provider: str = "bootcamp") -> None:
        self.provider = provider

    async def generate_sql(self, request: LabRequest) -> tuple[CandidateSQL, ...]:
        table = DEMO_TABLES.get(request.lab_id)
        if table is None:
            raise ValueError("演示模式不支持此实验室")
        question = request.query
        if any(word in question for word in ("同比", "环比", "中位数", "预测")):
            raise ValueError("此演示生成器不支持该计算，请使用真实实验室或查询简单汇总")
        filters = []
        date_match = re.search(r"(20\d{2})\s*(?:年|[-/])\s*(\d{1,2})\s*月?", question)
        if date_match:
            year, month = map(int, date_match.groups())
            if not 1 <= month <= 12:
                raise ValueError("月份应在1至12之间")
            filters.append(f"sales_month = '{year}-{month:02d}'")
        elif "最新" in question or "最近一个月" in question:
            filters.append("sales_month = '2026-09'")
        else:
            year_match = re.search(r"20\d{2}", question)
            selected_year = year_match.group() if year_match else "2026"
            filters.append(f"sales_month LIKE '{selected_year}-%'")
        for column, values in (
            ("region", DEMO_REGIONS),
            ("product", DEMO_ITEMS),
            ("channel", DEMO_CHANNELS),
        ):
            matches = [value for value in values if value in question]
            if matches:
                quoted = ", ".join(f"'{value}'" for value in matches)
                filters.append(f"{column} IN ({quoted})")
        dimensions = []
        for hints, column in (
            (("各地区", "各区域", "按地区", "按区域", "地区排名", "区域排名"), "region"),
            (("各产品", "各品牌", "按产品", "按品牌", "产品排名"), "product"),
            (("各月", "每月", "按月", "月度", "趋势"), "sales_month"),
            (("各渠道", "按渠道"), "channel"),
            (("各医院", "按医院", "医院排名"), "hospital"),
        ):
            if any(hint in question for hint in hints):
                dimensions.append(column)
        if "明细" in question:
            select = "sales_month, region, product, hospital, channel, units, amount"
            sql = f"SELECT {select} FROM {table} WHERE {' AND '.join(filters)} ORDER BY amount DESC"
        else:
            metric = "SUM(units)" if "销量" in question or "数量" in question else "SUM(amount)"
            if "达成" in question:
                metric = "100.0 * SUM(amount) / NULLIF(SUM(target_amount), 0)"
            elif "份额" in question or "占有率" in question:
                metric = "100.0 * SUM(amount) / NULLIF(SUM(market_amount), 0)"
            select = ", ".join([*dimensions, f"ROUND({metric}, 2) AS value"])
            sql = f"SELECT {select} FROM {table} WHERE {' AND '.join(filters)}"
            if dimensions:
                sql += " GROUP BY " + ", ".join(dimensions)
                sql += (
                    " ORDER BY sales_month"
                    if "sales_month" in dimensions
                    else " ORDER BY value DESC"
                )
        top = re.search(r"(?:前|top\s*)(\d+)", question, flags=re.IGNORECASE)
        if top:
            sql += f" LIMIT {max(1, min(int(top.group(1)), 1000))}"
        return (
            CandidateSQL(
                atom_id=request.atom_id,
                lab_id=request.lab_id,
                query=question,
                sql=sql,
                candidate_no=0,
                narrative=f"演示数据 · {self.provider} · {table}；金额单位元。",
                session_id=f"demo-{self.provider}-{request.atom_id}",
            ),
        )
