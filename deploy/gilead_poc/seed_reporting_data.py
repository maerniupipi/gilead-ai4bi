"""Append a coherent, owned set of synthetic reporting records to the POC warehouse.

Only gilead_poc_owner@gilead_poc is accepted. Existing business records are never
deleted or overwritten. A transaction and seed marker make repeated runs safe.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import pymysql
from boost_volume_sql import connect

PREFIX = "BIRPT20261026"
TABLES = (
    "prod_master",
    "ddi_coverage",
    "teri_hierachy",
    "v_ai4bi_ddi_sales",
    "sales_target_ai4bi",
)


def normalize_owned_dimensions(cursor):
    """Use the warehouse's canonical region/province/city values for new rows."""
    cursor.execute(
        "SELECT DISTINCT province_name_cn,province_code,city_name_cn,city_code "
        "FROM sales_target_ai4bi WHERE hco_code NOT LIKE %s",
        (PREFIX + "%",),
    )
    codes = {
        (row["province_name_cn"], row["city_name_cn"]): (
            row["province_code"],
            row["city_code"],
        )
        for row in cursor.fetchall()
    }
    cursor.execute(
        "SELECT DISTINCT hco_code,region,province_name_cn,city_name_cn "
        "FROM sales_target_ai4bi WHERE hco_code LIKE %s",
        (PREFIX + "%",),
    )
    for row in cursor.fetchall():
        region = row["region"].replace("大区", "")
        province = row["province_name_cn"].removesuffix("省").removesuffix("市")
        city = row["city_name_cn"].removesuffix("市")
        index = ["华东", "华南", "华北", "华中", "西南", "西北"].index(region)
        province_code, city_code = codes.get(
            (province, city), (f"S{index}P", f"S{index}C")
        )
        cursor.execute(
            "UPDATE sales_target_ai4bi SET region=%s,province_name_cn=%s,city_name_cn=%s,"
            "province_code=%s,city_code=%s,teri_code=%s,sam_teri_code=%s,rd_teri_code=%s,"
            "ts_name=%s,ts_adid=%s,sam_name=%s,sam_adid=%s,rd_name=%s,rd_adid=%s "
            "WHERE hco_code=%s AND brand_code LIKE %s",
            (
                region,
                province,
                city,
                province_code,
                city_code,
                f"{PREFIX}TS{index}",
                f"{PREFIX}ASM{index}",
                f"{PREFIX}RSM{index}",
                f"样例代表{index + 1}",
                f"sample-ts-{index}",
                f"样例区域经理{index + 1}",
                f"sample-asm-{index}",
                f"样例大区经理{index + 1}",
                f"sample-rsm-{index}",
                row["hco_code"],
                PREFIX + "%",
            ),
        )
        cursor.execute(
            "UPDATE teri_hierachy SET province_name_cn=%s,city_name_cn=%s,province_code=%s,"
            "city_code=%s,ts_teri_name=%s,asm_lvl_teri_name=%s,rsm_lvl_teri_name=%s "
            "WHERE hco_code=%s",
            (
                province,
                city,
                province_code,
                city_code,
                region,
                region,
                region,
                row["hco_code"],
            ),
        )


def insert_rows(cursor, table, rows):
    if not rows:
        return
    columns = list(rows[0])
    sql = (
        f"INSERT INTO `{table}` ("
        + ",".join(f"`{key}`" for key in columns)
        + ") VALUES ("
        + ",".join(["%s"] * len(columns))
        + ")"
    )
    for offset in range(0, len(rows), 500):
        cursor.executemany(
            sql, [[row[key] for key in columns] for row in rows[offset : offset + 500]]
        )


def load_samples(path: Path):
    raw = path.read_bytes()
    report = json.loads(raw)
    if report.get("id") != "sample-ddi-202609" or len(report["rows"]) != 1638:
        raise ValueError("Unexpected reporting sample dataset")
    return report["rows"], hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    source, fingerprint = load_samples(args.data)
    with connect() as connection:
        connection.cursorclass = pymysql.cursors.DictCursor
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE() AS db, CURRENT_USER() AS actor")
            identity = cursor.fetchone()
            if identity["db"] != "gilead_poc" or not identity["actor"].startswith(
                "gilead_poc_owner@"
            ):
                raise RuntimeError("Refusing unexpected database/account")
            cursor.execute("SELECT GET_LOCK(%s, 3) AS acquired", (PREFIX,))
            if cursor.fetchone()["acquired"] != 1:
                raise RuntimeError("Another reporting loader is active")
            cursor.execute(
                "SELECT * FROM _poc_seed_runs WHERE table_name=%s", (PREFIX,)
            )
            if cursor.fetchone():
                normalize_owned_dimensions(cursor)
                connection.commit()
                print(json.dumps({"status": "already_loaded", "batch": PREFIX}))
                return
            templates = {}
            for table in TABLES:
                cursor.execute(f"SELECT * FROM `{table}` LIMIT 1")
                templates[table] = cursor.fetchone()
                if templates[table] is None:
                    raise RuntimeError(
                        "Six-table warehouse must already be initialized"
                    )
            cursor.execute(
                "SELECT COUNT(*) AS n FROM v_ai4bi_ddi_sales WHERE sales_id LIKE %s",
                (PREFIX + "%",),
            )
            if cursor.fetchone()["n"]:
                raise RuntimeError(
                    "Unmarked sample rows exist; refusing duplicate data"
                )
            payloads = {table: [] for table in TABLES}
            products = {}
            for index, brand in enumerate(["品牌A", "品牌B", "品牌C"], 1):
                product = dict(templates["prod_master"])
                product.update(
                    prod_code=f"{PREFIX}P{index}",
                    prod_code_codi=f"{PREFIX}C{index}",
                    prod_name_cn=f"样例产品{index}",
                    prod_name_en=f"Sample product {index}",
                    prod_alias=f"样例产品{index}",
                    brand_code=f"{PREFIX}B{index}",
                    brand_name_cn=f"样例{brand}",
                    brand_name_en=f"Sample brand {index}",
                    ta_code="SAMPLE_TA",
                    ta_name_cn="样例治疗领域",
                    ta_name_en="Sample TA",
                )
                products[brand] = product
                payloads["prod_master"].append(product)
            hcos, monthly = (
                {},
                defaultdict(
                    lambda: {
                        "qty": 0,
                        "amt": 0,
                        "usd": 0,
                        "tqty": 0,
                        "tamt": 0,
                        "tusd": 0,
                    }
                ),
            )
            row_id = 9_000_000_000
            for record in source:
                hco_key = (record["region"], record["province"], record["hco"])
                if hco_key not in hcos:
                    hcos[hco_key] = (f"{PREFIX}H{len(hcos) + 1:03d}", record)
                hco_code, _ = hcos[hco_key]
                product = products[record["brand"]]
                for year, qty, tqty in (
                    (2026, record["sales_qty"], record["target_qty"]),
                    (2025, record["prior_qty"], round(record["target_qty"] / 1.1)),
                ):
                    row_id += 1
                    original = date.fromisoformat(record["date"])
                    day = date(
                        year,
                        original.month,
                        min(original.day, calendar.monthrange(year, original.month)[1]),
                    )
                    ym = year * 100 + original.month
                    amount = qty * record["price_latest"]
                    usd = round(qty * record["asp_price"], 2)
                    row = dict(templates["v_ai4bi_ddi_sales"])
                    row.update(
                        id=row_id,
                        sales_id=f"{PREFIX}-{row_id}",
                        sales_date=day,
                        year_month=ym,
                        upstream_code=f"{PREFIX}UP",
                        upstream_extr_code=f"{PREFIX}UP",
                        downstream_code=hco_code,
                        downstream_extr_code=hco_code,
                        affiliate_hco_code=hco_code,
                        prod_code_codi=product["prod_code_codi"],
                        prod_code=product["prod_code"],
                        sales_qty=qty,
                        price_hist=record["price_latest"],
                        special_price_hist=record["price_latest"],
                        standard_price_hist=record["price_latest"],
                        price_latest=record["price_latest"],
                        asp_price=record["asp_price"],
                        daily_date_version=date(2026, 9, 30),
                        data_type="Daily",
                        sales_type="纯销",
                        brand_name_cn=product["brand_name_cn"],
                        market_type="DDI",
                        market_type_latest="DDI",
                        terminal_channel=record["channel"],
                        terminal_channel_latest=record["channel"],
                        terminal_type={
                            "医院": "医院准入",
                            "零售药房": "药房",
                            "电商平台": "电商",
                        }[record["channel"]],
                        terminal_type_latest={
                            "医院": "医院准入",
                            "零售药房": "药房",
                            "电商平台": "电商",
                        }[record["channel"]],
                        codi_rec_id=row_id,
                        data_channel="样例数据",
                    )
                    payloads["v_ai4bi_ddi_sales"].append(row)
                    key = (ym, hco_code, record["brand"], record["channel"])
                    aggregate = monthly[key]
                    for field, value in (
                        ("qty", qty),
                        ("amt", amount),
                        ("usd", usd),
                        ("tqty", tqty),
                        ("tamt", tqty * record["price_latest"]),
                        ("tusd", round(tqty * record["asp_price"], 2)),
                    ):
                        aggregate[field] += value
            geo = {code: record for code, record in hcos.values()}
            months = sorted({key[0] for key in monthly})
            for code, record in hcos.values():
                for ym in months:
                    row = dict(templates["teri_hierachy"])
                    index = ["华东", "华南", "华北", "华中", "西南", "西北"].index(
                        record["region"].replace("大区", "")
                    )
                    row.update(
                        year_month=ym,
                        hco_code=code,
                        hco_name_cn=record["hco"],
                        province_name_cn=record["province"],
                        province_code=f"S{index}P",
                        city_name_cn=record["city"],
                        city_code=f"S{index}C",
                        ta="样例治疗领域",
                        teri_ta="样例治疗领域",
                        bu="COMM",
                        ts_teri_code=f"{PREFIX}TS{index}",
                        ts_teri_name=record["region"],
                        ts_empl_name=f"样例代表{index + 1}",
                        ts_empl_adid=f"sample-ts-{index}",
                        asm_lvl_teri_code=f"{PREFIX}ASM{index}",
                        asm_lvl_teri_name=record["region"],
                        asm_lvl_empl_name=f"样例区域经理{index + 1}",
                        asm_lvl_empl_adid=f"sample-asm-{index}",
                        rsm_lvl_teri_code=f"{PREFIX}RSM{index}",
                        rsm_lvl_teri_name=record["region"],
                        rsm_lvl_empl_name=f"样例大区经理{index + 1}",
                        rsm_lvl_empl_adid=f"sample-rsm-{index}",
                    )
                    payloads["teri_hierachy"].append(row)
            for (ym, code, brand, channel), aggregate in monthly.items():
                record, product = geo[code], products[brand]
                row = dict(templates["sales_target_ai4bi"])
                row.update(
                    year_month=ym,
                    hco_code=code,
                    hco_name=record["hco"],
                    brand_code=product["brand_code"],
                    brand_name_cn=product["brand_name_cn"],
                    brand_name_en=product["brand_name_en"],
                    region=record["region"],
                    province_name_cn=record["province"],
                    city_name_cn=record["city"],
                    ta="样例治疗领域",
                    bu="COMM",
                    teri_code=code,
                    sales_qty=aggregate["qty"],
                    sales_amt=aggregate["amt"],
                    sales_amt_asp=aggregate["usd"],
                    target_qty=aggregate["tqty"],
                    target_amt=aggregate["tamt"],
                    target_amt_asp=aggregate["tusd"],
                    data_type="Monthly",
                    market_type_latest="DDI",
                    terminal_channel_latest=channel,
                    terminal_type_latest={
                        "医院": "医院准入",
                        "零售药房": "药房",
                        "电商平台": "电商",
                    }[channel],
                )
                payloads["sales_target_ai4bi"].append(row)
            for brand, product in products.items():
                qty = sum(
                    record["sales_qty"]
                    for record in source
                    if record["brand"] == brand and record["date"].startswith("2026-09")
                )
                row = dict(templates["ddi_coverage"])
                row.update(
                    brand_code=product["brand_code"],
                    sales_qty_daily=qty,
                    sales_qty_monthly=qty,
                    coverage=1,
                )
                payloads["ddi_coverage"].append(row)
            for table in TABLES:
                insert_rows(cursor, table, payloads[table])
            normalize_owned_dimensions(cursor)
            cursor.execute("SELECT COUNT(*) AS n FROM data_range_config")
            if cursor.fetchone()["n"] != 1:
                raise RuntimeError("Expected one report range configuration row")
            cursor.execute(
                "UPDATE data_range_config SET max_daily_yearmonth=202609,max_ddi_version='2026-09-30'"
            )
            cursor.execute(
                "INSERT INTO _poc_seed_runs(table_name,seed_version,rows_loaded,completed) VALUES(%s,%s,%s,TRUE)",
                (PREFIX, "report-samples-v1", sum(map(len, payloads.values()))),
            )
            connection.commit()
            print(
                json.dumps(
                    {
                        "status": "loaded",
                        "batch": PREFIX,
                        "sha256": fingerprint,
                        "rows": {
                            table: len(values) for table, values in payloads.items()
                        },
                        "hcos": len(hcos),
                        "date_range": ["2025-01-01", "2026-09-30"],
                    },
                    ensure_ascii=False,
                )
            )


if __name__ == "__main__":
    main()
