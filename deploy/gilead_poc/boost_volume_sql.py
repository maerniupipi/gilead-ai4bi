"""Fast volume boost via server-side INSERT...SELECT clones + date/org shifts.

Creates >=1,000,000 additional fact rows without shipping every row from the client.
"""

from __future__ import annotations

import time
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent
BATCH = "BOOSTSQL20261025"


def connect() -> pymysql.Connection:
    env: dict[str, str] = {}
    for line in (ROOT / "business-owner.env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return pymysql.connect(
        host=env["MYSQL_HOST"],
        port=int(env.get("MYSQL_PORT", 3306)),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        ssl_disabled=True,
        charset="utf8mb4",
        autocommit=False,
        connect_timeout=60,
        read_timeout=600,
        write_timeout=600,
    )


def main() -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute("SET SESSION innodb_lock_wait_timeout=120")
    cur.execute("SET SESSION unique_checks=0")
    cur.execute("SET SESSION foreign_key_checks=0")
    cur.execute("SELECT DATABASE(), CURRENT_USER()")
    database, user = cur.fetchone()
    if database != "gilead_poc" or not str(user).startswith("gilead_poc_owner"):
        raise SystemExit(f"refusing: {database} {user}")

    cur.execute("SELECT COUNT(*) FROM v_ai4bi_ddi_sales")
    base_ddi = int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM sales_target_ai4bi WHERE data_type='Monthly'")
    base_monthly = int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM v_ai4bi_ddi_sales WHERE sales_id LIKE 'BOOST%'")
    boost_ddi = int(cur.fetchone()[0])
    cur.execute(
        "SELECT COUNT(*) FROM sales_target_ai4bi "
        "WHERE teri_code LIKE 'BOOST%' AND data_type='Monthly'"
    )
    boost_monthly = int(cur.fetchone()[0])
    print(
        "base",
        {
            "ddi": base_ddi,
            "monthly": base_monthly,
            "boost_ddi": boost_ddi,
            "boost_monthly": boost_monthly,
        },
        flush=True,
    )

    # Clean prior boost batches only when present (full-table DELETE scans lock hard).
    if boost_ddi > 0:
        t0 = time.time()
        cur.execute("DELETE FROM v_ai4bi_ddi_sales WHERE sales_id LIKE 'BOOST%'")
        conn.commit()
        print(f"cleanup ddi boost affected={cur.rowcount} in {time.time()-t0:.1f}s", flush=True)
    if boost_monthly > 0:
        t0 = time.time()
        cur.execute(
            "DELETE FROM sales_target_ai4bi "
            "WHERE teri_code LIKE 'BOOST%' AND data_type='Monthly'"
        )
        conn.commit()
        print(
            f"cleanup monthly boost affected={cur.rowcount} in {time.time()-t0:.1f}s",
            flush=True,
        )

    # Clone DDI daily rows with shifted ids/dates/sales_id so we get many distinct days
    # and roughly 4x volume. Offset days keep YYYY-MM-DD variety for By Date.
    # 4 clones → ~5x original if we keep base; we only insert clones.
    # 5 clones ≈ 1.17M new daily rows (~1.4M total with base); "多补一点"
    clones = [
        (1, 17),
        (2, 31),
        (3, 45),
        (4, 59),
        (5, 73),
    ]
    for idx, day_shift in clones:
        t0 = time.time()
        sql = f"""
        INSERT INTO v_ai4bi_ddi_sales (
          id, sales_id, sales_date, `year_month`, upstream_code, upstream_extr_code,
          downstream_code, downstream_extr_code, affiliate_hco_code, prod_code_codi, prod_code,
          sales_qty, data_channel, upstream_level, downstream_level, downstream_is_special_flag,
          price_hist, special_price_hist, standard_price_hist, price_latest, daily_date_version,
          market_type, terminal_type, terminal_channel, terminal_platform,
          market_type_latest, terminal_type_latest, terminal_channel_latest, terminal_platform_latest,
          channel_source, data_type, sales_type, from_cust_bizlevel, to_cust_bizlevel,
          from_cust_org_type1, codi_rec_id, asp_price, brand_name_cn
        )
        SELECT
          COALESCE(id,0) + {idx} * 1000000000,
          CONCAT('{BATCH}-', {idx}, '-', sales_id),
          DATE_ADD(sales_date, INTERVAL {day_shift} DAY),
          YEAR(DATE_ADD(sales_date, INTERVAL {day_shift} DAY))*100
            + MONTH(DATE_ADD(sales_date, INTERVAL {day_shift} DAY)),
          upstream_code, upstream_extr_code, downstream_code, downstream_extr_code,
          affiliate_hco_code, prod_code_codi, prod_code,
          sales_qty * (1 + ({idx} % 3) * 0.02),
          data_channel, upstream_level, downstream_level, downstream_is_special_flag,
          price_hist, special_price_hist, standard_price_hist, price_latest,
          daily_date_version, market_type, terminal_type, terminal_channel, terminal_platform,
          market_type_latest, terminal_type_latest, terminal_channel_latest, terminal_platform_latest,
          channel_source, data_type, sales_type, from_cust_bizlevel, to_cust_bizlevel,
          from_cust_org_type1, codi_rec_id, asp_price, brand_name_cn
        FROM v_ai4bi_ddi_sales
        WHERE sales_id NOT LIKE 'BOOST%'
        """
        cur.execute(sql)
        conn.commit()
        print(f"ddi clone {idx} rows={cur.rowcount} in {time.time()-t0:.1f}s", flush=True)

    # Clone monthly with region/manager preserved; stamp teri_code for cleanup.
    for idx in (1, 2, 3):
        t0 = time.time()
        sql = f"""
        INSERT INTO sales_target_ai4bi (
          `year_month`, hco_code, hco_name, teri_code, sam_teri_code, rd_teri_code,
          brand_code, brand_name_cn, brand_name_en, city_code, city_name_cn,
          province_code, province_name_cn, tier, sales_qty, sales_amt, sales_amt_asp,
          target_qty, target_amt, target_amt_asp, market_type_latest, terminal_type_latest,
          terminal_channel_latest, terminal_platform_latest, ts_name, ts_adid, sam_name,
          sam_adid, rd_name, rd_adid, region, data_type, ta, bu
        )
        SELECT
          `year_month`,
          CONCAT(hco_code, '_B{idx}'),
          CONCAT(hco_name, '-扩{idx}'),
          CONCAT('{BATCH}-', {idx}, '-', COALESCE(teri_code,'T')),
          sam_teri_code, rd_teri_code,
          brand_code, brand_name_cn, brand_name_en, city_code, city_name_cn,
          province_code, province_name_cn, tier,
          sales_qty * (1 + {idx} * 0.03),
          sales_amt * (1 + {idx} * 0.03),
          sales_amt_asp * (1 + {idx} * 0.03),
          target_qty * (1 + {idx} * 0.03),
          target_amt * (1 + {idx} * 0.03),
          target_amt_asp * (1 + {idx} * 0.03),
          market_type_latest, terminal_type_latest, terminal_channel_latest, terminal_platform_latest,
          CONCAT(COALESCE(ts_name,'代表'), {idx}),
          CONCAT(COALESCE(ts_adid,'ad'), {idx}),
          sam_name, sam_adid, rd_name, rd_adid, region, data_type, ta, bu
        FROM sales_target_ai4bi
        WHERE data_type='Monthly' AND teri_code NOT LIKE 'BOOST%'
        """
        cur.execute(sql)
        conn.commit()
        print(f"monthly clone {idx} rows={cur.rowcount} in {time.time()-t0:.1f}s", flush=True)

    cur.execute("SELECT COUNT(*) FROM v_ai4bi_ddi_sales")
    ddi = int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM sales_target_ai4bi WHERE data_type='Monthly'")
    monthly = int(cur.fetchone()[0])
    cur.execute(
        "SELECT COUNT(DISTINCT sales_date) FROM v_ai4bi_ddi_sales WHERE `year_month`=202608"
    )
    days = int(cur.fetchone()[0])
    cur.execute(
        "SELECT COUNT(DISTINCT region) FROM sales_target_ai4bi "
        "WHERE data_type='Monthly' AND `year_month`=202608"
    )
    regions = int(cur.fetchone()[0])
    cur.execute(
        "SELECT COUNT(DISTINCT ts_name) FROM sales_target_ai4bi "
        "WHERE data_type='Monthly' AND `year_month`=202608 "
        "AND ts_name IS NOT NULL AND ts_name<>''"
    )
    managers = int(cur.fetchone()[0])
    print(
        "verify",
        {
            "ddi_total": ddi,
            "monthly_total": monthly,
            "days_202608": days,
            "regions": regions,
            "managers": managers,
            "fact_total": ddi + monthly,
        },
        flush=True,
    )
    conn.close()


if __name__ == "__main__":
    main()
