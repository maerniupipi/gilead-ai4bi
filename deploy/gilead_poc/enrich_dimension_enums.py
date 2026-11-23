"""Diversify market/terminal enums in gilead_poc so insight scope options have data.

Idempotent: sets market_type_latest / terminal_type_latest / terminal_channel_latest
by deterministic region (and brand for daily) buckets. Does not invent tax/collection
columns. Only touches gilead_poc via the business-owner account.
"""

from __future__ import annotations

import json
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "enrich-dimension-enums.json"

def _connect(env_path: Path) -> pymysql.Connection:
    env: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return pymysql.connect(
        host=env["MYSQL_HOST"],
        port=int(env.get("MYSQL_PORT", 3306)),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        connect_timeout=30,
        ssl_disabled=True,
        charset="utf8mb4",
        autocommit=False,
    )


def main() -> None:
    c = _connect(ROOT / "business-owner.env")
    cur = c.cursor()
    cur.execute("SELECT DATABASE(), CURRENT_USER()")
    database, user = cur.fetchone()
    if database != "gilead_poc" or not str(user).startswith("gilead_poc_owner"):
        raise SystemExit(f"refusing to write: database={database} user={user}")

    report: dict = {"database": database, "user": user, "updates": {}}

    # sales_target_ai4bi — has region
    stmts = [
        (
            "sales_market",
            "UPDATE sales_target_ai4bi SET market_type_latest = CASE region "
            "WHEN '华南' THEN '核心市场' WHEN '华东' THEN '核心市场' "
            "WHEN '华北' THEN 'CSO' WHEN '西北' THEN 'CSO' "
            "WHEN '华中' THEN '多渠道' WHEN '西南' THEN '多渠道' "
            "ELSE '核心市场' END",
        ),
        (
            "sales_terminal_type",
            "UPDATE sales_target_ai4bi SET terminal_type_latest = CASE region "
            "WHEN '华南' THEN '医院准入' WHEN '华东' THEN '医院准入' WHEN '西北' THEN '医院准入' "
            "WHEN '华北' THEN '药房' WHEN '华中' THEN '药房' "
            "WHEN '西南' THEN '电商' ELSE '医院准入' END",
        ),
        (
            "sales_terminal_channel",
            "UPDATE sales_target_ai4bi SET terminal_channel_latest = CASE region "
            "WHEN '华南' THEN '医院' WHEN '华东' THEN '医院' WHEN '西北' THEN '医院' "
            "WHEN '华北' THEN '零售药店' WHEN '华中' THEN '零售药店' "
            "WHEN '西南' THEN '电商平台' ELSE '医院' END",
        ),
    ]
    for name, sql in stmts:
        cur.execute(sql)
        report["updates"][name] = cur.rowcount

    # v_ai4bi_ddi_sales — no region; diversify by brand_name_cn buckets
    cur.execute(
        """
        UPDATE v_ai4bi_ddi_sales SET
          market_type_latest = CASE
            WHEN brand_name_cn IN ('模拟品牌01','模拟品牌02','模拟品牌03','模拟品牌04') THEN '核心市场'
            WHEN brand_name_cn IN ('模拟品牌05','模拟品牌06','模拟品牌07','模拟品牌08') THEN 'CSO'
            ELSE '多渠道'
          END,
          terminal_type_latest = CASE
            WHEN brand_name_cn IN ('模拟品牌01','模拟品牌02','模拟品牌03','模拟品牌04') THEN '医院准入'
            WHEN brand_name_cn IN ('模拟品牌05','模拟品牌06','模拟品牌07','模拟品牌08') THEN '药房'
            ELSE '电商'
          END,
          terminal_channel_latest = CASE
            WHEN brand_name_cn IN ('模拟品牌01','模拟品牌02','模拟品牌03','模拟品牌04') THEN '医院'
            WHEN brand_name_cn IN ('模拟品牌05','模拟品牌06','模拟品牌07','模拟品牌08') THEN '零售药店'
            ELSE '电商平台'
          END
        """
    )
    report["updates"]["ddi_enums"] = cur.rowcount

    # verify distributions @ 202608 monthly
    cur.execute(
        "SELECT market_type_latest v, COUNT(*) n, SUM(sales_amt) a "
        "FROM sales_target_ai4bi WHERE data_type='Monthly' AND `year_month`=202608 "
        "GROUP BY 1 ORDER BY n DESC"
    )
    report["monthly_market"] = [
        {"v": r[0], "n": r[1], "amt": float(r[2])} for r in cur.fetchall()
    ]
    cur.execute(
        "SELECT terminal_type_latest v, COUNT(*) n "
        "FROM sales_target_ai4bi WHERE data_type='Monthly' AND `year_month`=202608 "
        "GROUP BY 1 ORDER BY n DESC"
    )
    report["monthly_terminal_type"] = [{"v": r[0], "n": r[1]} for r in cur.fetchall()]
    cur.execute(
        "SELECT terminal_channel_latest v, COUNT(*) n "
        "FROM sales_target_ai4bi WHERE data_type='Monthly' AND `year_month`=202608 "
        "GROUP BY 1 ORDER BY n DESC"
    )
    report["monthly_terminal_channel"] = [{"v": r[0], "n": r[1]} for r in cur.fetchall()]
    cur.execute(
        "SELECT market_type_latest v, COUNT(*) n FROM v_ai4bi_ddi_sales GROUP BY 1 ORDER BY n DESC"
    )
    report["ddi_market"] = [{"v": r[0], "n": r[1]} for r in cur.fetchall()]

    c.commit()
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    cur.close()
    c.close()


if __name__ == "__main__":
    main()
