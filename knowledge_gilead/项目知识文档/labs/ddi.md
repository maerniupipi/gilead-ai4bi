# 吉利德 DDI 实验室

> lab_id: `actual` · 文件：`labs/ddi.md` · 业务显示名：吉利德 DDI  
> **职责：本域能力**（何时找我、支持 KPI、槽位、歧义、SQL）。路由 → `实验室总索引.md`；公式权威 → `业务知识.md`。  
> 说明：POC 仅此一个实验室。实验中心凭证槽位仍用兼容 id `actual`；文档与路由对外称 DDI。

## 1. 何时找我

吉利德 **DDI 销售与目标达成**：销售金额 / 数量、指标、达成率、同比（Month / QTD / YTD）、环比（月环比 / 上季环比）、以及 **DDI 当月日累计（MTD）** 金额及其同环比。  
不含 Demand 流向、不含外部市场（本 POC 未配置）。  
**仅支持 §4 列出的 KPI，其余一律不支持。**

## 2. 能回答的问题类型（真实枚举示例）

新增样例品牌A/B/C对应品牌编码BIRPT20261026B1/B2/B3，是与模拟品牌01/02/03不同的品牌。查询时保留用户指定的品牌字面量或明确编码；大区字段使用华东、华南、华北、华中、西南、西北。


更全清单见 `业务知识.md` §8。下列实体名均来自库内实测：

- 达成 / 指标：「202608 全国金额达成率」「华南模拟品牌03 金额达成」「华东各品牌数量达成」「各省 A/T% 低于 80%」「MOCKBU1 × 模拟治疗领域3 达成」
- 金额 / 数量：「全国本月销售金额」「省份 Top10」「模拟品牌03 在华南卖了多少钱/多少盒」「广州 vs 成都 vs 武汉金额」「模拟医疗机构079 本月金额」
- 日累计：「截至 2026-09-03 的 DDI MTD Actual」「按模拟品牌拆分 MTD」「广东 DDI 当月日累计」
- 同比：「全国金额 YoY」「华东 QTD 同比」「模拟品牌03 YTD 同比」「西南数量同比」「江苏金额同比」
- 环比：「全国相对 202607 的 MoM」「2026Q2 vs Q1 的 QoQ」「华中 MoM + 达成」「西北模拟品牌02 月环比」
- MTD 同环比：「DDI MTD Actual 同比 / 环比」「模拟品牌03 的 MTD 同比」
- 复合（拆原子问）：「华南模拟品牌03：金额 + 达成 + 同比」「MTD Actual 及其同环比」

## 3. 数据范围与维度

> **注意**：下表“当前库取值”来自 `gilead_poc` 实测；维度类问题仍用 GROUP BY，不要把列表当成不可扩展的硬编码白名单。


| 维度 | 常用字段 / 说明 | 当前库取值（实测） |
| --- | --- | --- |
| 时间 | `year_month`；日明细 `sales_date` | 最近完整月 `202609`；DDI 截至 `2026-09-30`；YTD=202601–202609；QTD=202607–202609 |
| 粒度 | `data_type` | `Monthly`（默认）/ `Daily`（勿混加） |
| 市场 | `market_type_latest` | 核心市场、CSO、多渠道 |
| 终端 | `terminal_type_latest` | 医院准入、药房、电商 |
| 渠道 | `terminal_channel_latest` | 医院、零售药店、电商平台 |
| 产品 | `brand_code` / `brand_name_cn`；日明细经 `prod_code_codi` | 模拟品牌01…13（`MOCKBRAND001`…`013`） |
| TA | `ta` / `ta_name_cn` | 模拟治疗领域1…6 |
| BU | `bu` | `MOCKBU1`、`MOCKBU2` |
| 大区 | `region` | 华东、华中、华北、华南、西北、西南 |
| 省份 | `province_name_cn` | 上海、北京、四川、天津、广东、江苏、湖北、湖南、甘肃、福建、重庆、陕西 |
| 城市 | `city_name_cn` | 上海、兰州、北京、南京、天津、广州、成都、武汉、福州、西安、重庆、长沙 |
| 机构 | `hco_code` / `hco_name` | 如 模拟医疗机构079（`MOCKHCO0079`）等 |
| 辖区 | `teri_hierachy` | TS 如 模拟代表辖区001；SD：模拟全国 |

**默认**：未指明日历日时用 **Monthly + 最近完整月**；显式「按日 / MTD / 截止某日」才走 `v_ai4bi_ddi_sales`。  
「DDI」问法默认指日累计主题，**不要**再过滤 `market_type_latest='DDI'`。

## 4. 支持的 KPI（仅下列；同义已合并）

「销量」未标明盒数时默认 **销售金额（CNY）**。权威公式见 `业务知识.md` §指标口径。


| # | KPI | 别名 | 计算逻辑（摘要） |
| --- | --- | --- | --- |
| 1 | 销售金额 | 销售额、金额、Actual、Act Value、卖了多少钱、业绩 | `SUM(sales_amt)`（月表 Monthly）；日明细为 `SUM(sales_qty * price_latest)` |
| 2 | 销售数量 | 盒数、数量、Qty、Vol、卖了多少盒 | `SUM(sales_qty)` |
| 3 | DDI MTD Actual | DDI当月日累计销售金额、当月日累计金额、MTD Actual | 在最新 DDI 日内，对当月 `sales_date` 的日明细汇总人民币金额 |
| 4 | Target | 销售指标、指标、目标、要做多少 | 金额指标 `SUM(target_amt)`；数量指标 `SUM(target_qty)`；默认金额 |
| 5 | A/T% | 达成率、完成率、a/t、完成进度 | 同维度 `SUM(实际) / NULLIF(SUM(指标),0)`；默认金额达成 |
| 6 | YoY GR% | 同比、同比增长、同比增速、Month/QTD/YTD 同比 | `(当期 − 去年同期) / NULLIF(去年同期, 0)`；窗口对齐截止月 |
| 7 | DDI MTD YoY GR% | DDI当月日累计同比、MTD 同比 | 当年 MTD 金额相对去年同月「截至可比日」MTD 的同比 |
| 8 | MoM GR% | 月环比、环比上月 | `(本月 − 上月) / NULLIF(上月, 0)`；完整月对完整月 |
| 9 | DDI MTD MoM GR% | DDI当月日累计环比、MTD 环比 | 本月 MTD 相对上月「截至上月同日序」MTD 的环比 |
| 10 | QoQ GR% | 季度环比、上季度环比、环比上季 | 最近完整季度合计相对上一完整季度；或按业务约定的季月均口径（见业务知识） |

**不支持示例**：外部市场份额、Demand 流向、Target GR%。报告的销售占比、目标差额等展示字段由HTML模板使用已核验的金额与目标计算，无需新增实验室KPI。

## 5. KPI 的 SQL 写法

公共变量：

- `{max_month}` = `data_range_config.max_daily_yearmonth`（整数 YYYYMM，如 `202608`）
- `{max_ddi_date}` = `CAST(data_range_config.max_ddi_version AS DATE)`（如 `2026-09-03`）
- 月表过滤：`` `year_month` `` 必须反引号；`data_type = 'Monthly'`
- 禁止 Daily 与 Monthly 混加

### 5.1 销售金额（月）

- 表：`sales_target_ai4bi`
- 字段：`SUM(sales_amt)`
- 条件：`data_type = 'Monthly'`，`` `year_month` = {max_month} ``（或用户给定区间）

### 5.2 销售数量（月）

- 表：`sales_target_ai4bi`
- 字段：`SUM(sales_qty)`
- 条件：同 5.1

### 5.3 DDI MTD Actual（当月日累计销售金额）

- 表：`v_ai4bi_ddi_sales`（可 `prod_code_codi` 关联 `prod_master` 取品牌）
- 金额：`SUM(sales_qty * price_latest)`
- 条件：
  1. `sales_date <= {max_ddi_date}`
  2. `` `year_month` = YEAR({max_ddi_date})*100 + MONTH({max_ddi_date}) ``（当月）
- 注意：`sales_id` 不唯一，勿按它去重；退货负数保留

### 5.4 Target（指标）

- 表：`sales_target_ai4bi`，`data_type = 'Monthly'`
- 金额指标：`SUM(target_amt)`；数量指标：`SUM(target_qty)`
- 默认金额；用户明确「数量指标 / 盒数指标」时用数量

### 5.5 A/T%（达成率）

- 含义：同维度实际 ÷ 同维度指标
- 步骤：
  1. 子查询 A：月表汇总实际（金额用 `sales_amt`，数量用 `sales_qty`）
  2. 子查询 B：月表汇总指标（`target_amt` / `target_qty`）
  3. 按相同维度对齐后 `actual / NULLIF(target, 0)`
- 强制规则：
  1. 实际与指标必须同一 `data_type`、同一时间窗、同一 GROUP BY
  2. 目标为 0 → 结果 NULL，回答「不适用」，不编造 0%
  3. 允许负实际（退货）；禁止先 JOIN 再汇总导致指标重复放大

```sql
WITH actual_v AS (
  SELECT SUM(sales_amt) AS actual_amt
  FROM sales_target_ai4bi
  WHERE data_type = 'Monthly' AND `year_month` = {max_month}
),
target_v AS (
  SELECT SUM(target_amt) AS target_amt
  FROM sales_target_ai4bi
  WHERE data_type = 'Monthly' AND `year_month` = {max_month}
)
SELECT actual_amt / NULLIF(target_amt, 0) AS at_rate
FROM actual_v, target_v;
```

### 5.6 YoY GR%（Month / QTD / YTD）

- 表：`sales_target_ai4bi`，`data_type = 'Monthly'`
- 度量默认 `sales_amt`（数量同比改 `sales_qty`）
- 窗口：
  - **Month**：当期 `{max_month}` vs 去年同月
  - **QTD**：当年已完整季内月份至 `{max_month}` vs 去年对齐月份
  - **YTD**：`YYYY01`–`{max_month}` vs 去年 `YYYY01`–去年同月
- 公式：`(curr - prev) / NULLIF(prev, 0)`；基期为 0 → NULL / 不适用
- 两边 GROUP BY / 筛选必须一致，仅年份平移

### 5.7 DDI MTD YoY GR%

- 表：`v_ai4bi_ddi_sales`
- 当期：当月且 `sales_date <= {max_ddi_date}` 的 MTD 金额
- 基期：去年同月，且 `sales_date <= 去年同月「日序相同」的日期`（日序超出上月天数则取上月月末）
- 公式同 YoY；基期 0 → 不适用

### 5.8 MoM GR% / DDI MTD MoM GR%

- **月环比（完整月）**：月表上 `{max_month}` vs 上一完整月
- **DDI MTD 环比**：本月 MTD vs 上月「截至上月同日序」的 MTD
- 公式：`(curr - prev) / NULLIF(prev, 0)`

### 5.9 QoQ GR%（上季度环比）

- 默认比较**最近两个完整自然季度**的销售金额合计（演示口径：完整 2026Q2 vs 2026Q1；若 `{max_month}=202608` 则最近完整季为 2026Q2）
- 公式：`(本季合计 - 上季合计) / NULLIF(上季合计, 0)`
- 若业务要求「季月均环比」，在回答中注明采用的是合计还是月均

## 6. 必填槽位


| 槽位 | 说明 | 缺失时 |
| --- | --- | --- |
| 时间窗口 | 默认最近完整月 / 对应 YTD·QTD | 可默认，回答注明截止月 |
| 金额 or 数量 | 默认金额 | 默认金额；个人记忆纠偏优先 |
| 范围 | 全国 / 大区 / 省 / 品牌等 | 默认全国；多实体并列则拆原子问 |
| 日 or 月 | 默认月；MTD/按日才走日表 | 默认 Monthly |


## 7. 常见歧义与澄清话术

- 「达成」默认 **金额 A/T%**；数量达成需明确。
- 「增速 / 增长」未说同环比 → 默认 **YoY（Month）**，回答注明。
- 「销量」→ 销售金额；要盒数需确认销售数量。
- 「DDI / 当月累计 / MTD」→ DDI MTD Actual（日表），不要误用整月 Monthly 冒充日累计。
- 「环比」未说上月还是上季 → 先看语境；无语境默认 **月环比**；「上季度」明确则 QoQ。
- 用户说「DDI」默认指日累计 / 实验室主题 → 走 `v_ai4bi_ddi_sales`；勿把「DDI」当成 `market_type_latest` 枚举（市场类型为 核心市场/CSO/多渠道）。

## 8. 调用样例（atomic_query · 真实枚举）

```
202608 全国销售金额与金额达成率
华南 模拟品牌03 202608 金额达成率
华东各品牌本月数量指标与数量达成
模拟医疗机构079 本月销售金额
截至 2026-09-03 的当月日累计销售金额（DDI MTD Actual）
广东 DDI MTD Actual
202608 各省份销售金额同比 YoY
2026 YTD 模拟品牌03 销售金额同比
2026 QTD 华东销售金额同比
上季度全国销售金额环比 QoQ
华中本月相对上月金额环比与达成率
DDI MTD Actual 同比与环比
模拟品牌03 的 DDI MTD Actual 同比
```

## 9. 已知限制

- Daily 与 Monthly 不可混加，否则重复计数。
- 层级表 `teri_hierachy` 含未来月份（如 203603）；历史归属用业务月，权限/生效快照用批准月，禁止裸用 `MAX(year_month)`。
- `brand_code` 在 `prod_master` 不唯一，按品牌关联前须按品牌去重。
- 日明细关联层级须至少带齐业务月 + HCO + TA + BU，禁止只按 HCO 连接。
- 覆盖系数 `ddi_coverage.coverage` 可能 >1 或缺失；未经批准不截断、不外推。
- 本应用 `query_db` 只消费同次实验室 trace 的执行证据，不得改 SQL 套旧结果。

## 10. 表与关键字段（精简）

完整列定义见 `数据字典.md`。取数优先下列字段。

### `sales_target_ai4bi`（月/日事实；默认用 Monthly）

`year_month`, `data_type`, `sales_qty`, `sales_amt`, `target_qty`, `target_amt`, `brand_code`, `brand_name_cn`, `province_name_cn`, `city_name_cn`, `region`, `hco_code`, `hco_name`, `ta`, `bu`, `market_type_latest`, `terminal_type_latest`

### `v_ai4bi_ddi_sales`（DDI 日明细）

`sales_date`, `year_month`, `sales_qty`, `price_latest`, `prod_code_codi`, `affiliate_hco_code`, `market_type_latest`, `brand_name_cn`

### `prod_master`

`prod_code_codi`, `brand_code`, `brand_name_cn`, `ta_code`, `ta_name_cn`

### `teri_hierachy`

`year_month`, `hco_code`, `province_name_cn`, `city_name_cn`, `ta`, `bu`, `ts_teri_code`, `rsm_lvl_teri_code`, `sd_lvl_teri_code`

### `data_range_config`

`max_daily_yearmonth`, `max_ddi_version`

### `ddi_coverage`

`brand_code`, `coverage`（仅覆盖类问题需要时使用）
