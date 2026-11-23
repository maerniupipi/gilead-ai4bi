"""Build the six-table POC DDL from the supplied Chinese data dictionary."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
EXPECTED = {
    "sales_target_ai4bi": 34,
    "v_ai4bi_ddi_sales": 38,
    "prod_master": 28,
    "teri_hierachy": 27,
    "ddi_coverage": 4,
    "data_range_config": 2,
}


def build(source: Path) -> dict:
    tables, current = {}, None
    for line in source.read_text().splitlines():
        heading = re.match(r"## \d+\. `public\.([^`]+)`", line)
        if heading:
            current = heading.group(1)
            tables[current] = []
        if current is None or not line.startswith("| `"):
            continue
        cells = [x.strip() for x in line.strip("|").split("|")]
        names = re.findall(r"`([^`]+)`", cells[0])
        types = re.findall(r"`([^`]+)`", cells[1])
        if not types:
            types = ["integer" if names == ["max_daily_yearmonth"] else "text"]
        if len(types) == 1:
            types *= len(names)
        assert len(names) == len(types), names
        for name, datatype in zip(names, types):
            assert re.fullmatch(r"[a-z_][a-z0-9_]*", name)
            assert re.fullmatch(
                r"(?:integer|bigint|date|timestamp|text|varchar\(\d+\)|numeric\(\d+,\d+\))",
                datatype,
            ), datatype
            tables[current].append(
                {
                    "name": name,
                    "type": datatype,
                    "nullable": not (
                        current == "sales_target_ai4bi" and name == "data_type"
                    ),
                    "comment": re.sub(r"`([^`]+)`", r"\1", cells[-1]),
                }
            )
    assert {k: len(v) for k, v in tables.items()} == EXPECTED
    statements = [
        "-- 吉利德 POC 六张 MySQL 业务物理表；模拟数据，不是客户真实明细。",
        "-- 原字典 public schema 映射为当前数据库；numeric 映射 DECIMAL；时间戳字段显式可空。",
        "CREATE TABLE IF NOT EXISTS `_poc_seed_runs` (table_name varchar(128) PRIMARY KEY, seed_version varchar(128) NOT NULL, rows_loaded bigint NOT NULL, completed BOOLEAN NOT NULL DEFAULT TRUE, completed_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB;",
    ]
    indexes = {
        "sales_target_ai4bi": [
            "KEY ix_gilead_sales_month (`year_month`,`data_type`,`brand_code`)",
            "KEY ix_gilead_sales_hco (`hco_code`,`year_month`)",
        ],
        "v_ai4bi_ddi_sales": [
            "KEY ix_gilead_ddi_date (`sales_date`,`prod_code_codi`)",
            "KEY ix_gilead_ddi_hco (`affiliate_hco_code`,`sales_date`)",
        ],
        "teri_hierachy": [
            "KEY ix_gilead_hierarchy (`year_month`,`hco_code`,`ta`,`bu`)"
        ],
        "prod_master": ["KEY ix_gilead_product (`prod_code_codi`)"],
    }
    for table, columns in tables.items():
        defs = []
        for c in columns:
            comment = c["comment"].replace("'", "''")
            datatype = c["type"].replace("numeric", "decimal")
            if datatype == "text" and c["name"] == "max_ddi_version":
                datatype = "varchar(32)"
            null = " NULL DEFAULT NULL" if c["nullable"] else " NOT NULL"
            defs.append(f"  `{c['name']}` {datatype}{null} COMMENT '{comment}'")
        defs.extend("  " + x for x in indexes.get(table, []))
        statements.append(
            f"CREATE TABLE IF NOT EXISTS `{table}` (\n"
            + ",\n".join(defs)
            + "\n) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COMMENT='吉利德 POC 合成模拟数据';"
        )
    HERE.joinpath("schema.json").write_text(
        json.dumps(tables, ensure_ascii=False, indent=2) + "\n"
    )
    HERE.joinpath("001_schema.sql").write_text("\n\n".join(statements) + "\n")
    return tables


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("source", type=Path)
    print({k: len(v) for k, v in build(p.parse_args().source).items()})
