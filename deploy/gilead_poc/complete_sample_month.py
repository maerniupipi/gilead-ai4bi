"""Complete September's original synthetic brands for full-month reporting.

This loader only appends a missing Monthly slice in the owned POC warehouse.
Daily remains the independently supplied daily snapshot; it is never mixed
with Monthly. Values are synthetic scenarios based on August, not actuals.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pymysql
from boost_volume_sql import connect
from seed_reporting_data import insert_rows

BATCH = "BIMONTH202609"
FACTORS = {
    "华东": "1.12",
    "华南": "0.82",
    "华北": "1.07",
    "华中": "0.99",
    "西南": "1.13",
    "西北": "0.94",
}


def main():
    with connect() as connection:
        connection.cursorclass = pymysql.cursors.DictCursor
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE() AS db,CURRENT_USER() AS actor")
            identity = cursor.fetchone()
            if identity["db"] != "gilead_poc" or not identity["actor"].startswith(
                "gilead_poc_owner@"
            ):
                raise RuntimeError("Unexpected database/account")
            cursor.execute("SELECT GET_LOCK(%s,3) AS acquired", (BATCH,))
            if cursor.fetchone()["acquired"] != 1:
                raise RuntimeError("Sample completion is already active")
            try:
                cursor.execute(
                    "SELECT rows_loaded FROM _poc_seed_runs WHERE table_name=%s", (BATCH,)
                )
                if cursor.fetchone():
                    print(json.dumps({"status": "already_loaded", "batch": BATCH}))
                    return
                cursor.execute(
                    "SELECT COUNT(*) AS n FROM sales_target_ai4bi WHERE `year_month`=202609 "
                    "AND data_type='Monthly' AND brand_code LIKE 'MOCKBRAND%'"
                )
                if cursor.fetchone()["n"]:
                    raise RuntimeError("Unmarked September records already exist")
                cursor.execute(
                    "SELECT * FROM sales_target_ai4bi WHERE `year_month`=202608 AND "
                    "data_type='Monthly' AND brand_code LIKE 'MOCKBRAND%'"
                )
                baseline = cursor.fetchall()
                if len(baseline) != 6240 or len({r["brand_code"] for r in baseline}) != 13:
                    raise RuntimeError("Unexpected original synthetic brand baseline")
                rows = []
                for source in baseline:
                    row = dict(source)
                    factor = Decimal(FACTORS[source["region"]])
                    row["year_month"] = 202609
                    for actual, target in (
                        ("sales_qty", "target_qty"),
                        ("sales_amt", "target_amt"),
                        ("sales_amt_asp", "target_amt_asp"),
                    ):
                        amount = Decimal(str(source[actual] or 0))
                        row[actual] = (amount * factor).quantize(Decimal("0.01"))
                        row[target] = (amount * Decimal("1.06")).quantize(Decimal("0.01"))
                    rows.append(row)
                insert_rows(cursor, "sales_target_ai4bi", rows)
                cursor.execute(
                    "INSERT INTO "
                    "_poc_seed_runs(table_name,seed_version,rows_loaded,completed) "
                    "VALUES(%s,%s,%s,TRUE)",
                    (BATCH, "full-month-synthetic-v1", len(rows)),
                )
                connection.commit()
                manifest = {
                    "synthetic": True,
                    "batch": BATCH,
                    "month": 202609,
                    "rows_added": len(rows),
                    "brands": 13,
                    "basis": "August Monthly synthetic records with regional growth and 1.06 target factors",
                    "regional_factors": FACTORS,
                }
                Path(__file__).with_name("monthly-completion-manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
                )
                print(json.dumps(manifest, ensure_ascii=False))
            finally:
                cursor.execute("SELECT RELEASE_LOCK(%s)", (BATCH,))


if __name__ == "__main__":
    main()
