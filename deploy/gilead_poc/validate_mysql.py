"""Read-only MySQL business, structure, privilege and KPI reconciliation."""

import argparse, json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from provision_mysql import connect
from seed import rows

HERE = Path(__file__).resolve().parent


def canonical(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (Decimal, int, float)) and not isinstance(value, bool):
        return Decimal(str(value)).normalize().to_eng_string()
    return value


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--env", required=True, type=Path)
    a = p.parse_args()
    expected = json.loads((HERE / "seed-manifest.json").read_text())
    checks = []
    schema = json.loads((HERE / "schema.json").read_text())

    def check(name, actual, wanted):
        ok = actual == wanted
        checks.append({"check": name, "ok": ok, "actual": actual, "expected": wanted})
        if not ok:
            raise AssertionError((name, actual, wanted))

    with connect(a.env) as c:
        with c.cursor() as s:

            def scalar(query, args=None):
                s.execute(query, args)
                return s.fetchone()[0]

            s.execute("SET TRANSACTION READ ONLY")
            s.execute("START TRANSACTION READ ONLY")
            check("database", scalar("SELECT DATABASE()"), "gilead_poc")
            check(
                "readonly_account",
                scalar("SELECT SUBSTRING_INDEX(CURRENT_USER(),'@',1)"),
                "gilead_lab_reader",
            )
            for table, count in expected["table_counts"].items():
                check(
                    "count_" + table, scalar(f"SELECT count(*) FROM `{table}`"), count
                )
                s.execute(
                    "SELECT column_name,is_nullable,column_type FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s ORDER BY ordinal_position",
                    (table,),
                )
                actual = s.fetchall()
                check(
                    "columns_" + table,
                    [r[0] for r in actual],
                    [col["name"] for col in schema[table]],
                )
                check(
                    "nullable_" + table,
                    [r[1] == "YES" for r in actual],
                    [col["nullable"] for col in schema[table]],
                )
                check(
                    "types_" + table,
                    [r[2].lower() for r in actual],
                    [
                        "varchar(32)"
                        if col["name"] == "max_ddi_version"
                        else col["type"]
                        .replace("numeric", "decimal")
                        .replace("integer", "int")
                        for col in schema[table]
                    ],
                )
            check(
                "product_bridge_orphans",
                scalar(
                    "SELECT count(*) FROM v_ai4bi_ddi_sales d LEFT JOIN prod_master p USING(prod_code_codi) WHERE p.prod_code_codi IS NULL"
                ),
                0,
            )
            check(
                "hierarchy_orphans",
                scalar(
                    "SELECT count(*) FROM sales_target_ai4bi s LEFT JOIN teri_hierachy h ON s.year_month=h.year_month AND s.hco_code=h.hco_code AND s.ta=h.ta AND s.bu=h.bu WHERE h.hco_code IS NULL"
                ),
                0,
            )
            check(
                "hierarchy_grain",
                scalar(
                    "SELECT count(*) FROM (SELECT `year_month`,hco_code,ta,bu FROM teri_hierachy GROUP BY 1,2,3,4 HAVING count(*)>1) t"
                ),
                0,
            )
            check(
                "zero_target_null",
                scalar(
                    "SELECT sum(sales_qty)/nullif(sum(target_qty),0) FROM sales_target_ai4bi WHERE hco_code='MOCKHCO0001' AND brand_code='MOCKBRAND013' AND data_type='Monthly'"
                ),
                None,
            )
            check(
                "zero_baseline_null",
                scalar(
                    "SELECT (SUM(CASE WHEN `year_month`=202501 THEN sales_qty ELSE 0 END)-SUM(CASE WHEN `year_month`=202401 THEN sales_qty ELSE 0 END))/NULLIF(SUM(CASE WHEN `year_month`=202401 THEN sales_qty ELSE 0 END),0) FROM sales_target_ai4bi WHERE brand_code='MOCKBRAND013' AND data_type='Monthly' AND `year_month` IN (202401,202501)"
                ),
                None,
            )
            check(
                "return_rows_exist",
                scalar("SELECT count(*)>0 FROM v_ai4bi_ddi_sales WHERE sales_qty<0"),
                1,
            )
            check(
                "latest_hierarchy_snapshot",
                scalar("SELECT max(`year_month`) FROM teri_hierachy"),
                203603,
            )
            check(
                "unmatched_coverage",
                scalar(
                    "SELECT count(DISTINCT p.brand_code) FROM prod_master p LEFT JOIN ddi_coverage d USING(brand_code) WHERE d.brand_code IS NULL"
                ),
                2,
            )
            check(
                "coverage_over_one",
                scalar("SELECT count(*) FROM ddi_coverage WHERE coverage>1"),
                1,
            )
            check(
                "nonunique_sales_id",
                scalar(
                    "SELECT count(DISTINCT sales_id)<count(*) FROM v_ai4bi_ddi_sales"
                ),
                1,
            )
            check(
                "closed_month",
                scalar("SELECT max_daily_yearmonth FROM data_range_config"),
                202608,
            )
            for case in expected["golden_cases"]:
                for label, period in [
                    ("current", case["current_months"]),
                    ("baseline", case["baseline_months"]),
                ]:
                    s.execute(
                        "SELECT sum(sales_qty),sum(sales_amt),sum(sales_amt_asp),sum(target_qty),sum(target_amt),sum(target_amt_asp) FROM sales_target_ai4bi WHERE data_type='Monthly' AND `year_month` BETWEEN %s AND %s",
                        period,
                    )
                    check(
                        case["name"] + "_" + label,
                        [str(x) for x in s.fetchone()],
                        [
                            str(Decimal(x).quantize(Decimal("0.000001")))
                            for x in case[label + "_totals"]
                        ],
                    )
            s.execute(
                "SELECT sum(sales_qty*price_latest),sum(sales_qty*asp_price) FROM v_ai4bi_ddi_sales"
            )
            ddi = s.fetchone()
            s.execute(
                "SELECT sum(sales_amt),sum(sales_amt_asp) FROM sales_target_ai4bi WHERE data_type='Daily'"
            )
            fact = s.fetchone()
            check(
                "daily_cny_usd",
                [str(x.normalize()) for x in ddi],
                [str(x.normalize()) for x in fact],
            )
            keys = {
                "sales_target_ai4bi": [
                    "year_month",
                    "hco_code",
                    "brand_code",
                    "data_type",
                ],
                "v_ai4bi_ddi_sales": ["id"],
                "prod_master": ["prod_code"],
                "teri_hierachy": ["year_month", "hco_code", "ta", "bu"],
                "ddi_coverage": ["brand_code"],
                "data_range_config": [],
            }
            for table, columns in schema.items():
                first = last = None
                for generated in rows(table):
                    if first is None:
                        first = generated
                    last = generated
                samples = (
                    [first] if expected["table_counts"][table] == 1 else [first, last]
                )
                names = [column["name"] for column in columns]
                for index, sample in enumerate(samples):
                    where = " AND ".join("`" + key + "`=%s" for key in keys[table])
                    query = (
                        "SELECT "
                        + ",".join("`" + n + "`" for n in names)
                        + f" FROM `{table}`"
                    )
                    if where:
                        query += " WHERE " + where
                    s.execute(
                        query + " LIMIT 2", tuple(sample[key] for key in keys[table])
                    )
                    found = s.fetchall()
                    check(
                        "full_row_sample_" + table + "_" + str(index),
                        [[canonical(value) for value in row] for row in found],
                        [[canonical(sample[name]) for name in names]],
                    )
            s.execute("SHOW GRANTS")
            grants = "\n".join(r[0] for r in s.fetchall()).upper()
            check(
                "no_write_privileges",
                not any(
                    x in grants
                    for x in [
                        "INSERT",
                        "UPDATE",
                        "DELETE",
                        "CREATE ",
                        "DROP ",
                        "ALL PRIVILEGES",
                    ]
                ),
                True,
            )
            for db in ["gilead_agent_loop", "app_uat"]:
                try:
                    s.execute(f"SELECT 1 FROM `{db}`.`identity_users` LIMIT 0")
                    denied = False
                except Exception as exc:
                    denied = getattr(exc, "args", [None])[0] in {1044, 1142}
                check("denied_other_database_" + db, denied, True)
            c.rollback()
    out = {
        "database": "gilead_poc",
        "dialect": "mysql",
        "synthetic": True,
        "status": "passed",
        "checks": checks,
    }
    (HERE / "verification.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n"
    )
    print("MySQL verification passed:", len(checks), "checks")


if __name__ == "__main__":
    main()
