"""Read-only reconciliation and a current warehouse golden manifest."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from boost_volume_sql import connect
from seed_reporting_data import PREFIX


def main():
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT DATABASE(),CURRENT_USER()")
        database, actor = cursor.fetchone()
        if database != "gilead_poc" or not actor.startswith("gilead_poc_owner@"):
            raise RuntimeError("Unexpected project database")
        cursor.execute(
            "SELECT DISTINCT region FROM sales_target_ai4bi WHERE brand_code LIKE %s",
            (PREFIX + "%",),
        )
        regions = sorted(row[0] for row in cursor.fetchall())
        assert set(regions) == {"华东", "华南", "华北", "华中", "西南", "西北"}
        cursor.execute(
            "SELECT `year_month`,SUM(sales_qty),SUM(sales_qty*price_latest) "
            "FROM v_ai4bi_ddi_sales WHERE sales_id LIKE %s GROUP BY `year_month`",
            (PREFIX + "%",),
        )
        daily = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
        cursor.execute(
            "SELECT `year_month`,SUM(sales_qty),SUM(sales_amt) FROM sales_target_ai4bi "
            "WHERE brand_code LIKE %s AND data_type='Monthly' GROUP BY `year_month`",
            (PREFIX + "%",),
        )
        monthly = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
        assert daily == monthly
        cursor.execute(
            "SELECT COUNT(*) FROM (SELECT `year_month`,hco_code,ta,bu,COUNT(*) AS n "
            "FROM teri_hierachy WHERE hco_code LIKE %s "
            "GROUP BY `year_month`,hco_code,ta,bu HAVING COUNT(*)>1) AS duplicates",
            (PREFIX + "%",),
        )
        assert cursor.fetchone()[0] == 0
        totals = []
        for month in (202608, 202508):
            cursor.execute(
                "SELECT SUM(sales_qty),SUM(sales_amt),SUM(sales_amt_asp),SUM(target_qty),"
                "SUM(target_amt),SUM(target_amt_asp) FROM sales_target_ai4bi "
                "WHERE data_type='Monthly' AND `year_month`=%s", (month,),
            )
            totals.append([str(value or Decimal(0)) for value in cursor.fetchone()])
        cursor.execute("SELECT * FROM data_range_config")
        month, latest = cursor.fetchone()
        manifest = {
            "seed_version": "report-samples-v1", "synthetic": True,
            "as_of": str(latest), "last_closed_month": month,
            "regions": regions, "monthly_daily_reconciliation": "passed",
            "territory_join_uniqueness": "passed", "sample_months": len(monthly),
            "september_sample_totals": [str(value) for value in monthly[202609]],
            "golden_cases": [{"name": "month_yoy", "current_months": [202608, 202608],
                              "baseline_months": [202508, 202508],
                              "current_totals": totals[0], "baseline_totals": totals[1]}],
        }
        path = Path(__file__).with_name("report-sample-manifest.json")
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(manifest, ensure_ascii=False))

if __name__ == "__main__":
    main()
