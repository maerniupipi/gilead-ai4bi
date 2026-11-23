from pathlib import Path
import pymysql

env = {}
for line in Path(__file__).with_name("business-owner.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
c = pymysql.connect(
    host=env["MYSQL_HOST"],
    port=int(env.get("MYSQL_PORT", 3306)),
    user=env["MYSQL_USER"],
    password=env["MYSQL_PASSWORD"],
    database=env["MYSQL_DATABASE"],
    ssl_disabled=True,
    charset="utf8mb4",
)
cur = c.cursor()
queries = [
    ("ddi_total", "SELECT COUNT(*) FROM v_ai4bi_ddi_sales"),
    ("ddi_boost", "SELECT COUNT(*) FROM v_ai4bi_ddi_sales WHERE sales_id LIKE 'BOOST%'"),
    ("ddi_days_202608", "SELECT COUNT(DISTINCT sales_date) FROM v_ai4bi_ddi_sales WHERE `year_month`=202608"),
    ("monthly_total", "SELECT COUNT(*) FROM sales_target_ai4bi WHERE data_type='Monthly'"),
    ("regions", "SELECT COUNT(DISTINCT region) FROM sales_target_ai4bi WHERE data_type='Monthly' AND `year_month`=202608"),
    ("managers", "SELECT COUNT(DISTINCT ts_name) FROM sales_target_ai4bi WHERE data_type='Monthly' AND `year_month`=202608 AND ts_name IS NOT NULL AND ts_name<>''"),
    ("months", "SELECT COUNT(DISTINCT `year_month`) FROM sales_target_ai4bi WHERE data_type='Monthly'"),
]
for name, sql in queries:
    cur.execute(sql)
    print(name, cur.fetchone()[0])
c.close()
