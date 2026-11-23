# 先问实验室再校验

> **Goal:** 取数默认先判实验室、先 `ask_lab`；结论数字只来自实验室 SQL。主链路只做轻量路由和校验，不写取数 SQL，不管实验室权限口径。
>
> **Architecture:** 简单题只判实验室就调用。关键词不清也先调用——实验室有关键词召回，生成的 SQL 和 narrative 当字段映射参考。`query_db` 绑定本轮实验室候选；探测 SQL 不能当事实。ODS / Retail Pharmacy 等权限过滤留在实验室内。

---

## 1. 为什么改

评测 150 题里，大约一半错误不是「实验室 SQL 写错」，而是主链路没把实验室 SQL 当结论：

- 8 题完全没调 `ask_lab`，自己 `SUM` / `DISTINCT`
- 约 10 题调了 Actual 实验室，结论 SQL 却没有实验室权限口径（ODS）
- 5 题实验室 SQL 跑过，随后被手写 SQL 覆盖（#81、#105、#119、#124）
- 模型先 `DISTINCT` / `LIKE` 摸库猜「院外 / HLP / BU core / 流向」，再自己拼 SQL
- 澄清卡用探测结果当推荐选项，把内部题推进外部 / Demand

实验室本身会做关键词召回、字段映射、权限过滤。主链路再猜一遍，既慢又错。

ODS / Retail Pharmacy **不是**主链路要补的规则。它是实验室权限层。缺 ODS 只能解读成：这条结论 SQL 不是实验室出的。

---

## 2. 目标行为

```
用户问题
  │
  ├─ 轻量判实验室（只分内外、actual / demand / ext）
  │     不要在这里把「院外」改写成 EC+CHC
  │
  ├─ 立刻 ask_lab
  │     问句尽量保留用户原词（院外、HLP、BU core、流向为医院、零售大仓）
  │     简单题：原问题几乎原样送进去
  │     嵌套题：只拆原子，不改口径词
  │
  ├─ 读实验室返回：SQL + 理解（narrative）
  │     这就是关键词召回的结果，当字段映射参考
  │     例如 SQL 里出现 ddi_category='Hospital Sales' → 流向已落地，不要再手写
  │
  ├─ 校验（主链路只做这件事）
  │     用户原问题里的约束，在实验室 SQL 里有没有痕迹
  │     对不上 → 换问法再 ask_lab，或真歧义才 ask_user
  │     对得上 → query_db(实验室 SQL)
  │
  └─ 回答里的数字 = 已执行的实验室 SQL 结果
        禁止用探测行当结论
        禁止把实验室 SQL 拆开重写（会丢掉权限层）
```

### 2.1 简单题

「25年YTD01江西安达唐County的Actual、达成、增速」这类：

1. 判 `actual`
2. `ask_lab(question≈原问题, lab_id=actual)`
3. `query_db(候选 SQL)`
4. 回答

不要先读完总索引 + 业务知识 + labs/actual.md，再 DISTINCT channel，再自己写 WITH。

### 2.2 关键词不清

「倍择瑞院外的销量」「广西新兴市场」「流向为医院」：

**先问实验室，不要先澄清、不要先摸库。**

实验室召回会把词落到字段，返回的 SQL 就是参考：

- 看 `WHERE` / `GROUP BY` 用了哪一列
- 看 narrative 怎么理解这个词
- 口径合理 → 直接执行这条 SQL
- 实验室明确说找不到 / 丢掉了用户原词 → 再澄清或换实验室

禁止的旧路径：探测到 `channel` 有 EC/CHC → 澄清推荐「院外=EC+CHC」→ 自己写 SQL。

### 2.3 主链路仍然要做的轻量路由

「先问实验室」不等于乱选实验室。只做这一层，不做字段映射：

| 信号 | 实验室 |
|---|---|
| 默认内部销量 / 达成 / 指标 / 增速 | `actual` |
| 明确 demand / 纯销 / 一级商出货 | `demand` |
| 「流向为医院 / 医院流向 / DTP 流向 / 关联药店」 | **`actual`**（`ddi_category`，不是 Demand 实验室） |
| 份额 / 市场 / AIA / CHPA / PDOT 且原句已有外部词 | `ext_simple` / `ext_complex` |
| 单独「增长最快」无外部词 | `actual`，不要因澄清推荐 PDOT 而转外部 |

「流向」两个字不够路由到 Demand；后面跟着医院 / DTP / 关联药店时走 Actual。

---

## 3. 明确不做什么

- 不在 harness / Prompt / SQL 审查里补 `sub_bu_name NOT IN ('ODS', 'Retail Pharmacy')`
- 不把 HLP、院外、零售大仓、BU core 的字段映射写成主链路规则去拼 SQL
- 不把实验室 SQL「参考」成：抽出字段名，再自己写一条新 SQL
- 澄清卡不提供「把内部题改成 AIA / PDOT / Demand」的推荐项，除非原句已经是那种语境
- 「我的 / 辖区」没有 `trty_code` 时，问实验室也没用，继续要身份；评测要注入身份或从分母拿掉

---

## 4. 改哪里

### 4.1 取数纪律（提示词）— 先实验室

**文件:** `backend_v2/src/xiaoying_quick/application/agent_run/loop.py` 里 `AGENT_SYSTEM_PROMPT`

把「知识检索顺序」和「取数纪律」改成：

1. 先判实验室，立刻 `ask_lab`。简单查数题不要先 knowledge_read 一整圈。
2. 关键词不确定（渠道黑话、流向、HLP、core/emerging）→ 仍先 `ask_lab`，原词进问句。实验室召回 + SQL 当参考。
3. 结论数字必须来自本轮实验室候选 SQL 的 `query_db` 结果。
4. 探测 SQL 只允许在已经拿到实验室 SQL 之后，且只用于 `MAX(date)` / 枚举校对；探测行不是事实。
5. 实验室 SQL 执行失败或覆盖审查失败 → 换问法再 `ask_lab`，禁止手写 SUM。
6. 概念题（「BU 是什么」）才走 knowledge_*，不要问实验室。

`ask_lab` 工具 description 同步：问句保留用户口径词，禁止把「院外」改写成渠道枚举再送进去。

### 4.2 工具层硬约束 — 结论 SQL 必须是实验室候选

**文件:**

- `backend_v2/src/xiaoying_quick/application/agent_run/loop.py`（保存本轮候选）
- `backend_v2/src/xiaoying_quick/application/agent_run/tools.py`（`query_db`）
- 新建小模块更干净：`backend_v2/src/xiaoying_quick/application/agent_run/lab_sql_bind.py`

行为：

| `query_db` SQL 类型 | 处理 |
|---|---|
| 与本轮某条 `ask_lab` 候选归一化后相同（空白/大小写/末尾分号可忽略） | 放行 |
| 仅改 `LIMIT` / 外层包一层不改 WHERE | 放行（小幅修正白名单） |
| `MAX(date)` / 单列 `DISTINCT` 且本轮已有实验室候选 | 探测，放行；结果 `trusted=false`，不进事实台账 |
| 其它手写 `SUM(sales_val)` / JOIN 重写 / 丢掉 WHERE | **拒绝**，提示「请执行实验室候选或换问法再 ask_lab」 |

本轮还没有 `ask_lab` 成功结果时，除 `MAX(date)` 探测外全部拒绝。这直接堵上 #43、#46 这类自己写结论 SQL。

归一化不要做语义 diff，不要在绑定层检查 ODS。绑定的是「出处」，不是「权限规则」。

### 4.3 覆盖审查 — 对照原问题，不对照权限口径

**文件:** `backend_v2/src/xiaoying_quick/application/agent_run/sql_review.py`

继续只检查：用户原词 / 已确认口径，在 SQL 文本里有没有痕迹。

- 用户说「院外」，SQL 里既没有「院外」也没有对应过滤 → `ok=false`，要求再 `ask_lab`
- 不要把 ODS 写进审查词表
- 审查失败的行已经「不可作为最终事实」——保持；再加一句「请换问法 ask_lab，不要手写替换」

### 4.4 澄清降权 — 不要教错映射

**文件:** 澄清选项生成（`modules/clarification/` 与 loop 里澄清纪律）

规则：

- 实验室还没返回前，不要为「院外 / HLP / 零售大仓 / BU core / 非关联药店 / 流向为医院」出字段映射选项
- 推荐项不得把实验室从 actual 改到 ext / demand（PDOT、AIA、Demand 口径），除非原句已有这些外部 / Demand 信号
- 真歧义才问：哪一年、金额还是数量、对比窗口、「我的」是谁
- 评测自动点「推荐」会放大错误选项，所以推荐项必须来自已发布知识或实验室 narrative，不能来自本轮 `DISTINCT` 探测

### 4.5 路由例外 — 只补「流向」这一类

**文件:** `knowledge/项目知识文档/实验室总索引.md`（§2.2）

加一条，写进路由文档即可，不要在 SQL 层实现：

> 「流向为医院 / 医院流向 / DTP 流向 / 关联药店」是 Actual 表 `ddi_category`，走 `actual`，不走 `demand`。单独「demand / 纯销 / 一级商」才走 Demand。

这修 #51 / #53 / #137 的实验室选错。字段值仍由实验室召回，主链路不写 `ddi_category = 'Hospital Sales'`。

BU core / 新兴 / 社区卫生服务中心 **不要**在主链路写死字段。原词进 Actual 实验室，让召回生成 `sub_channel`。

### 4.6 评测导出 — 「最终 SQL」不要用最后一条探测

**文件:** `frontend/src/eval/format.js`

现在把最后一条 `query_db` 标成最终查询，#2 / #24 / #41 / #91 的结论 KPI 被 brand `DISTINCT` 盖掉。

改为：优先最后一条「非探测且本轮匹配实验室候选」的 SQL；没有再回退到最后一条 KPI SQL。

---

## 5. 和评测错误怎么对上

| 错误类型 | 本方案怎么收 |
|---|---|
| 没调实验室自己写 SQL（#25 探测、#43 手写 SUM、#97） | 无候选则拒绝结论 SQL；简单题默认先 ask_lab |
| 调了实验室却手写覆盖、丢掉 ODS（#81、#119、#124） | `query_db` 绑定候选，重写即拒绝 |
| 先摸库再猜字段（院外 / HLP / 大仓 / 新兴 / BU core） | 原词进实验室，用返回 SQL 当参考，禁止探测驱动映射 |
| 澄清推荐把题带去外部 / Demand（#87、#98、#115） | 澄清不得改实验室；原句无外部词就停在 actual |
| 流向为医院却进 Demand（#51、#53、#137） | 路由例外：这类词走 actual |
| 人员层级 / 大区 / 地区经理（#18、#25、#34） | 原词进实验室（大区、地区经理、人名），让召回选 `region_name` / `dsm_name` / `rsd_name`；不要主链路先 `mr_name LIKE` |
| 「我的」无身份（#32、#84、#106、#107） | 无 `trty_code` 则 ask_user 要身份；评测注入或剔除 |
| Target JOIN 销售表放大（#124） | 绑定实验室 SQL 后不会发生；实验室不会这样 JOIN |
| 缺 ODS 被当成 SQL 规则 | **不修。** 只当「没用实验室 SQL」的探针 |

---

## 6. 实施顺序

### Task 1: 实验室 SQL 绑定（硬约束，收益最大）

- 新增 `lab_sql_bind.py`：归一化、探测判定、是否匹配候选
- `AgentRunService` 保存本轮 `ask_lab` 候选列表
- `query_db` 执行前检查；拒绝时 `ok=false`，文案明确「请执行实验室候选」
- 单测：匹配放行、改 LIMIT 放行、手写 SUM 拒绝、无 ask_lab 时拒绝 KPI、MAX(date) 可探测但不进事实

### Task 2: 提示词改为实验室优先

- 改 `AGENT_SYSTEM_PROMPT` 取数纪律 / 知识顺序
- 改 `ask_lab` / `query_db` description
- 单测锁定 description 关键字（已有 ask_lab description 锁定可仿）

### Task 3: 覆盖审查文案 + 探测不当事实

- 审查失败提示改成「再 ask_lab」
- `trusted=false` 的探测不写入 `_facts` / `_hops`（loop.py 已有 `trusted` 开关，把探测标上去）

### Task 4: 路由文档 + 澄清纪律

- 总索引 §2.2 流向例外
- 澄清：实验室返回前不对黑话出映射选项；推荐项不切换实验室

### Task 5: 评测最终 SQL

- `format.js` + `frontend/tests/eval.test.js`

### 刻意不做

- 不在主链路或审查里加入 ODS 规则
- 不把 BU_Core / CHC / HLP 的字段映射写进 harness
- 第一轮不改实验室 Prompt（召回仍在实验室内）

---

## 7. 验收

用同一份 150 题回归，至少看这些探针：

1. 结论 SQL 与某条 `ask_lab` 候选归一化一致（Actual 题应自然带上 ODS，但不断言 ODS 本身）
2. 错误题里「无 ask_lab」「先有 ODS 后被手写覆盖」应变 0
3. 「院外 / 新兴 / BU core / 流向为医院」类题：澄清卡不再推荐 EC+CHC / 产品组 / Demand 全量
4. 简单销量题：`ask_lab` 出现在第一条 KPI `query_db` 之前，中间探测条数明显下降
5. #46 这类没走实验室却判对的题，新约束下必须先 ask_lab

实验室侧关键词召回仍可能把个别词映射错。那是实验室知识问题，主链路只保证：**问到了、用了它的 SQL、没有手写覆盖。**
