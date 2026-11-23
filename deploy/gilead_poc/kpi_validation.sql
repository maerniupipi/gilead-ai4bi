-- 管理员模拟数据核验 SQL。真实用户查询必须先应用吉利德授权策略。
-- 仅验证 Monthly，不与 Daily 混合。金额单位人民币元。
SELECT
  SUM(sales_qty) AS actual_qty,
  SUM(target_qty) AS target_qty,
  SUM(sales_amt) AS actual_cny,
  SUM(target_amt) AS target_cny,
  SUM(sales_amt_asp) AS actual_asp_usd,
  SUM(target_amt_asp) AS target_asp_usd,
  SUM(sales_qty) / NULLIF(SUM(target_qty), 0) AS qty_attainment,
  SUM(sales_amt) / NULLIF(SUM(target_amt), 0) AS amount_attainment
FROM sales_target_ai4bi
WHERE data_type = 'Monthly' AND `year_month` = 202608;

-- 四个同比/环比场景。全部使用对齐的完整月份区间。
WITH periods AS (
  SELECT 'month_yoy' AS case_name,202608 AS current_start,202608 AS current_end,202508 AS baseline_start,202508 AS baseline_end
  UNION ALL SELECT 'qtd_yoy',202607,202608,202507,202508
  UNION ALL SELECT 'ytd_yoy',202601,202608,202501,202508
  UNION ALL SELECT 'last_complete_quarter_qoq',202604,202606,202601,202603
), totals AS (
  SELECT p.case_name,
    SUM(CASE WHEN s.`year_month` BETWEEN p.current_start AND p.current_end THEN s.sales_amt ELSE 0 END) AS current_amount,
    SUM(CASE WHEN s.`year_month` BETWEEN p.baseline_start AND p.baseline_end THEN s.sales_amt ELSE 0 END) AS baseline_amount
  FROM periods p JOIN sales_target_ai4bi s
    ON s.data_type='Monthly'
    AND (s.`year_month` BETWEEN p.current_start AND p.current_end
      OR s.`year_month` BETWEEN p.baseline_start AND p.baseline_end)
  GROUP BY p.case_name
)
SELECT case_name,current_amount,baseline_amount,
  (current_amount-baseline_amount)/NULLIF(baseline_amount,0) AS growth_rate
FROM totals ORDER BY case_name;

-- 日明细按唯一产品桥接；不要按品牌直接连接 16 行产品主数据。
SELECT d.sales_date,p.brand_code,
  SUM(d.sales_qty) AS actual_qty,
  SUM(d.sales_qty*d.price_latest) AS actual_cny,
  SUM(d.sales_qty*d.asp_price) AS actual_asp_usd
FROM v_ai4bi_ddi_sales d JOIN prod_master p USING(prod_code_codi)
WHERE d.sales_date BETWEEN '2026-09-01' AND '2026-09-03'
GROUP BY d.sales_date,p.brand_code
ORDER BY d.sales_date,p.brand_code;
