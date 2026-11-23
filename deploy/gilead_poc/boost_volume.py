"""Append synthetic volume so DDI看板 has rich By Date / Month / Region / Manager rows.

Safety:
- Only writes gilead_poc via gilead_poc_owner
- Idempotent batch marker on sales_id / teri_code prefixes
- Targets ~1,000,000+ NEW rows across daily + monthly fact tables
"""

from __future__ import annotations

import math
import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent
BATCH_TAG = "BOOST20261025"
AS_OF = date(2026, 9, 3)
LAST_CLOSED = 202608
REGIONS = ["华北", "华东", "华南", "华中", "西南", "西北"]
GEO = [
    ("北京", "北京"),
    ("天津", "天津"),
    ("上海", "上海"),
    ("江苏", "南京"),
    ("广东", "广州"),
    ("福建", "福州"),
    ("湖北", "武汉"),
    ("湖南", "长沙"),
    ("四川", "成都"),
    ("重庆", "重庆"),
    ("陕西", "西安"),
    ("甘肃", "兰州"),
]
# Extra HCOs beyond the original 001-120 so we don't collide with base seed keys.
EXTRA_HCO_START = 200
EXTRA_HCO_COUNT = 420  # 200..619 → ~1.1M+ daily rows with 3 lines/day
BRANDS = list(range(1, 14))  # 13 brands
DAILY_START = date(2024, 1, 1)
DAILY_LINES = 3


def _connect() -> pymysql.Connection:
    env: dict[str, str] = {}
    for line in (ROOT / "business-owner.env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    conn = pymysql.connect(
        host=env["MYSQL_HOST"],
        port=int(env.get("MYSQL_PORT", 3306)),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        connect_timeout=60,
        ssl_disabled=True,
        charset="utf8mb4",
        autocommit=False,
    )
    return conn


def _months(start: int = 202401, end: int = 202608):
    y, m = divmod(start, 100)
    while y * 100 + m <= end:
        yield y * 100 + m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _org(h: int):
    region_i = (h - EXTRA_HCO_START) % 6
    return {
        "region": REGIONS[region_i],
        "ts": f"TS{h:03d}",
        "sam": f"ASM{region_i + 1:02d}",
        "rd": f"RSM{region_i + 1:02d}",
        "sd": "SD01",
        "ts_name": f"模拟代表{h:03d}",
        "sam_name": f"模拟地区经理{region_i + 1:02d}",
        "rd_name": f"模拟大区经理{region_i + 1:02d}",
    }


def _hco(h: int):
    geo = GEO[(h - EXTRA_HCO_START) % 12]
    return {
        "hco_code": f"MOCKHCO{h:04d}",
        "hco_name": f"模拟医疗机构{h:03d}",
        "province_name_cn": geo[0],
        "city_name_cn": geo[1],
        "province_code": f"P{(h % 12) + 1:02d}",
        "city_code": f"C{(h % 12) + 1:02d}",
        "tier": f"T{h % 3 + 1}",
    }


def _price(brand: int) -> Decimal:
    return Decimal("80") + Decimal(brand) * Decimal("12.5")


def estimate_rows() -> dict[str, int]:
    days = (AS_OF - DAILY_START).days + 1
    daily = days * EXTRA_HCO_COUNT * DAILY_LINES
    months = list(_months())
    monthly = EXTRA_HCO_COUNT * len(BRANDS) * len(months)
    return {
        "v_ai4bi_ddi_sales": daily,
        "sales_target_ai4bi_monthly": monthly,
        "total_new": daily + monthly,
        "days": days,
    }


def already_loaded(cur) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM v_ai4bi_ddi_sales WHERE sales_id LIKE %s",
        (f"{BATCH_TAG}%",),
    )
    return int(cur.fetchone()[0] or 0) > 0


def clear_batch(cur) -> None:
    cur.execute("DELETE FROM v_ai4bi_ddi_sales WHERE sales_id LIKE %s", (f"{BATCH_TAG}%",))
    cur.execute(
        "DELETE FROM sales_target_ai4bi WHERE teri_code LIKE %s AND data_type='Monthly'",
        (f"{BATCH_TAG}%",),
    )


def insert_daily(cur, *, batch_size: int = 4000) -> int:
    sql = (
        "INSERT INTO v_ai4bi_ddi_sales ("
        "id, sales_id, sales_date, `year_month`, affiliate_hco_code, prod_code_codi, prod_code, "
        "sales_qty, price_latest, asp_price, brand_name_cn, data_type, sales_type, "
        "market_type_latest, terminal_type_latest, terminal_channel_latest, "
        "daily_date_version, data_channel"
        ") VALUES ("
        "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Daily','纯销',%s,%s,%s,%s,'DDI'"
        ")"
    )
    buf: list[tuple] = []
    n = 0
    day = DAILY_START
    seq = 0
    markets = ["核心市场", "CSO", "多渠道"]
    terminals = ["医院准入", "药房", "电商"]
    channels = ["医院", "零售药店", "电商平台"]
    while day <= AS_OF:
        ym = day.year * 100 + day.month
        for h in range(EXTRA_HCO_START, EXTRA_HCO_START + EXTRA_HCO_COUNT):
            hco = _hco(h)
            for line in range(DAILY_LINES):
                seq += 1
                brand = BRANDS[(h + day.toordinal() + line) % len(BRANDS)]
                qty = Decimal((day.day * 5 + h % 17 + line * 9) % 40 + 1)
                if seq % 97 == 0:
                    qty = -qty
                price = _price(brand)
                market = markets[(h + line) % 3]
                term = terminals[(h // 3 + line) % 3]
                chan = channels[(h // 5 + day.month) % 3]
                buf.append(
                    (
                        9_000_000_000 + seq,
                        f"{BATCH_TAG}-D{seq:08d}",
                        day,
                        ym,
                        hco["hco_code"],
                        f"MOCKCODI{min(brand, 16):03d}",
                        f"MOCKPROD{min(brand, 16):03d}",
                        qty,
                        price,
                        (price / Decimal("7")).quantize(Decimal("0.01")),
                        f"模拟品牌{brand:02d}",
                        market,
                        term,
                        chan,
                        AS_OF,
                    )
                )
                if len(buf) >= batch_size:
                    cur.executemany(sql, buf)
                    n += len(buf)
                    buf.clear()
                    if n % 100_000 < batch_size:
                        print(f"  daily progress {n}")
        day += timedelta(days=1)
    if buf:
        cur.executemany(sql, buf)
        n += len(buf)
    return n


def insert_monthly(cur, *, batch_size: int = 4000) -> int:
    sql = (
        "INSERT INTO sales_target_ai4bi ("
        "`year_month`, hco_code, hco_name, teri_code, sam_teri_code, rd_teri_code, "
        "brand_code, brand_name_cn, brand_name_en, city_code, city_name_cn, "
        "province_code, province_name_cn, tier, sales_qty, sales_amt, sales_amt_asp, "
        "target_qty, target_amt, target_amt_asp, market_type_latest, terminal_type_latest, "
        "terminal_channel_latest, terminal_platform_latest, ts_name, ts_adid, sam_name, "
        "sam_adid, rd_name, rd_adid, region, data_type, ta, bu"
        ") VALUES ("
        "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Monthly',%s,%s"
        ")"
    )
    buf: list[tuple] = []
    n = 0
    markets = ["核心市场", "CSO", "多渠道"]
    terminals = ["医院准入", "药房", "电商"]
    channels = ["医院", "零售药店", "电商平台"]
    for ym in _months():
        y, m = divmod(ym, 100)
        for h in range(EXTRA_HCO_START, EXTRA_HCO_START + EXTRA_HCO_COUNT):
            hco = _hco(h)
            org = _org(h)
            for brand in BRANDS:
                price = _price(brand)
                qty = Decimal((h % 40) * 8 + brand * 3 + m * 5 + (y - 2024) * 20)
                amt = (qty * price).quantize(Decimal("0.01"))
                t_qty = (qty * Decimal("1.08")).quantize(Decimal("0.01"))
                t_amt = (t_qty * price).quantize(Decimal("0.01"))
                ta = (brand - 1) % 6 + 1
                bu = f"MOCKBU{(ta - 1) // 3 + 1}"
                buf.append(
                    (
                        ym,
                        hco["hco_code"],
                        hco["hco_name"],
                        f"{BATCH_TAG}-{org['ts']}",
                        org["sam"],
                        org["rd"],
                        f"MOCKBRAND{brand:03d}",
                        f"模拟品牌{brand:02d}",
                        f"Synthetic brand {brand:02d}",
                        hco["city_code"],
                        hco["city_name_cn"],
                        hco["province_code"],
                        hco["province_name_cn"],
                        hco["tier"],
                        qty,
                        amt,
                        (amt / Decimal("7")).quantize(Decimal("0.01")),
                        t_qty,
                        t_amt,
                        (t_amt / Decimal("7")).quantize(Decimal("0.01")),
                        markets[h % 3],
                        terminals[(h // 2) % 3],
                        channels[(h // 4) % 3],
                        None,
                        org["ts_name"],
                        f"mock.ts.{h:03d}",
                        org["sam_name"],
                        f"mock.sam.{org['sam'][-2:]}",
                        org["rd_name"],
                        f"mock.rsm.{org['rd'][-2:]}",
                        org["region"],
                        f"模拟治疗领域{ta}",
                        bu,
                    )
                )
                if len(buf) >= batch_size:
                    cur.executemany(sql, buf)
                    n += len(buf)
                    buf.clear()
    if buf:
        cur.executemany(sql, buf)
        n += len(buf)
    return n


def verify(cur) -> dict:
    out: dict = {}
    cur.execute("SELECT COUNT(*) FROM v_ai4bi_ddi_sales")
    out["ddi_total"] = int(cur.fetchone()[0])
    cur.execute(
        "SELECT COUNT(DISTINCT sales_date) FROM v_ai4bi_ddi_sales WHERE year_month=%s",
        (202608,),
    )
    out["ddi_days_202608"] = int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM sales_target_ai4bi WHERE data_type='Monthly'")
    out["monthly_total"] = int(cur.fetchone()[0])
    cur.execute(
        "SELECT COUNT(DISTINCT region) FROM sales_target_ai4bi "
        "WHERE data_type='Monthly' AND year_month=%s",
        (LAST_CLOSED,),
    )
    out["regions_202608"] = int(cur.fetchone()[0])
    cur.execute(
        "SELECT COUNT(DISTINCT ts_name) FROM sales_target_ai4bi "
        "WHERE data_type='Monthly' AND year_month=%s AND ts_name IS NOT NULL AND ts_name<>''",
        (LAST_CLOSED,),
    )
    out["managers_202608"] = int(cur.fetchone()[0])
    cur.execute(
        "SELECT COUNT(DISTINCT year_month) FROM sales_target_ai4bi WHERE data_type='Monthly'"
    )
    out["months"] = int(cur.fetchone()[0])
    return out


def main() -> None:
    plan = estimate_rows()
    print("plan_new_rows", plan)
    if plan["total_new"] < 1_000_000:
        # Scale HCO count upward if estimate under 1M
        raise SystemExit(f"estimate {plan['total_new']} < 1e6; bump EXTRA_HCO_COUNT")

    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT DATABASE(), CURRENT_USER()")
    database, user = cur.fetchone()
    if database != "gilead_poc" or not str(user).startswith("gilead_poc_owner"):
        raise SystemExit(f"refusing to write: database={database} user={user}")

    if already_loaded(cur):
        print("batch already present; clearing then reloading", BATCH_TAG)
        t0 = time.time()
        clear_batch(cur)
        conn.commit()
        print(f"cleared in {time.time() - t0:.1f}s")

    t0 = time.time()
    daily_n = insert_daily(cur)
    conn.commit()
    print(f"inserted daily {daily_n} in {time.time() - t0:.1f}s")

    t1 = time.time()
    monthly_n = insert_monthly(cur)
    conn.commit()
    print(f"inserted monthly {monthly_n} in {time.time() - t1:.1f}s")

    stats = verify(cur)
    print("verify", stats)
    print("new_total", daily_n + monthly_n)
    conn.close()


if __name__ == "__main__":
    main()
