# 百炼召回工具

> 只加一个工具，并在 Agent loop 里写清何时调用。`ask_lab` / `query_db` / 选实验室 / 澄清 / 权限口径一律不改。

---

## 1. 要解决什么

问句里的业务词（院外、HLP、BU core、流向为医院、零售大仓、地区经理、County…）需要落到**字段和取值**。这些词条在百炼侧，不在本地文档里。

本地 `knowledge_search` / `knowledge_read` 读的是仓库里的 md。百炼召回是同一类动作，只是去调 API 理解知识。query 可以是用户原问题全文，也可以是某个短词。

百炼召回只返回知识，不出 SQL、不算数。

---

## 2. 工具：`bailian_recall`

**不是实验室 completions。** 和 `query_db` 一样走 AZAI 查数：`createSession` + `run`。换一组 Agent code / token，`message.text` 里传知识 query，不传 SQL。

### 2.1 调用（与查数对齐）

```
POST {AZAI_CREATE_SESSION_URL}
Authorization: Bearer {BAILIAN_TOKEN}
{"agentCode": "<bailian agent code>"}

POST {AZAI_RUN_URL}
Authorization: Bearer {BAILIAN_TOKEN}
{
  "sessionId": "<uniqueCode>",
  "message": {
    "text": "{\"query\": \"<query>\", \"lab_type\": \"<lab_type>\"}",
    "metadata": {"messages": []}
  }
}
```

Agent 工具参数：

| 参数 | 必填 | 说明 |
|---|---|---|
| `query` | 是 | 可以是**用户原问题全文**，也可以是**某个短词**。例：「倍择瑞院外的销量多少」或「院外」 |
| `lab_type` | 是 | 对应实验室名称，与 `ask_lab` 的 `lab_id` 相同：`actual` / `demand` / `ext_simple` / `ext_complex` |

百炼只有一个 Agent，不进《实验室总索引》，也不进 `ask_lab` 枚举。`lab_type` 只是召回时告诉它当前问题属于哪个实验室。

实测：`lab_type=actual` 会带回 Actual / sales_val 等词条；`lab_type=demand` 会带回流向类型、OtherDemandSales 等。返回 JSON 含 `知识词条`、`NER`、`候选值`。

### 2.2 返回

不走 `LabResponseExtractor`（那是 `sql_citations`）。从 SSE 结束事件抽出 `content[0].text.value`，解析为知识 JSON，整理后给模型：

```
百炼召回（lab_type=actual，query=院外）：
知识词条：
- 院外：ddi_category in ('From Link Pharmacy','From DTP','From ETP')
NER：
- 院外：ddi_category='From Link Pharmacy'
候选值：
- ...
```

空结果：`未召回到相关词条。不要猜字段；需要口径时 ask_user。`

未配置：`百炼召回未配置，跳过。继续用 knowledge_search / knowledge_read，或 ask_user。`

即使返回里误带了 SQL，也不执行、不当数字。

### 2.3 配置

| 环境变量 | 要求 |
|---|---|
| `XIAOYING_AZAI_CREATE_SESSION_URL` | 复用现有查数 URL |
| `XIAOYING_AZAI_RUN_URL` | 复用现有查数 URL |
| `XIAOYING_BAILIAN_AGENT_CODE` | 可选。百炼 Agent code |
| `XIAOYING_BAILIAN_AUTHORIZATION` | 可选。百炼 token（可带或不带 `Bearer ` 前缀） |

四个实验室 token 的校验规则不变。百炼缺配置时工具仍注册，调用时返回「未配置」而不是让整个 Agent 起不来。

### 2.4 接入点（只加，不改旧工具）

- `BailianRecallRunner`：查数 HTTP；`build_bailian_recall_tool()` 注册进 `ToolRegistry`
- 前端轨迹标签「百炼召回」；评测多一列「百炼召回」
- loop 提示词补充何时检索（见 §3）

---

## 3. Loop：什么时候调用

只改 `AGENT_SYSTEM_PROMPT` 的「知识检索」相关段落。取数纪律、澄清、沉淀、SQL 三级**不动**。

百炼召回和 `knowledge_search` 是同一类动作：都是去取知识，不是去取数。差别只在知识在哪：

| | 本地检索 | 百炼召回 |
|---|---|---|
| 工具 | `knowledge_search` / `knowledge_read` | `bailian_recall` |
| 知识在哪 | 当前仓库里的 md | 调 API 理解知识 |
| query | 检索词 | **用户原问题全文**，或**某个短词** |

### 3.1 何时用哪一种检索

需要理解口径、词条、字段、定义时，先检索再 `ask_lab`。两种检索可以都用，不互斥。

- 看本地文档（总索引、实验室能力、KPI 公式、已写入 md 的口径）→ `knowledge_search` / `knowledge_read`
- 需要平台侧对这个问题或这个词的理解（词条、字段名、取值）→ `bailian_recall`

选实验室仍读《实验室总索引.md》。出 SQL 仍是 `ask_lab`，跑 SQL 仍是 `query_db`。这两件事不要问百炼。

### 3.2 query 怎么写

两种都合法，按当前需要选：

1. **完整 query**：把用户原问题原样送给百炼，让它理解整句里的词。适合刚入手、还不知道哪个词会卡住。
2. **短词**：已经定位到某个词（院外、HLP、流向为医院、BU core），只召回这一个。适合台账里该要素仍是「待确认」，或整句召回后还要对某个词补一刀。

已选定实验室时带上 `lab_id`。召回结果用同一 key 写入台账后，再 `ask_lab`。

同一 query 本轮已经召回过、没有新上下文，不要重复调用。

### 3.3 不要当成取数

- 要数字或 SQL → `ask_lab` / `query_db`
- 查数据最新月 → 现有 `MAX(date)` 探测
- 查某个人名在不在库里 → 数据问题，不是知识检索

召回为空：不要猜字段，也不要靠 `SELECT DISTINCT` 代替词条；本地 md 也没有则 `ask_user`。

### 3.4 提示词落点（草稿）

插在现有「知识检索顺序」里，作为和 `knowledge_search` 并列的检索手段：

```
## 知识检索顺序
- 选择实验室前：先 knowledge_read《实验室总索引.md》并 knowledge_search 业务知识，确定问题归属；
确定实验室后，再 knowledge_read 对应的 labs/ 文档，掌握它的能力与口径。
- 概念/定义/口径不确定：先检索。本地 md 用 knowledge_search / knowledge_read；
需要平台侧词条、字段、取值时用 bailian_recall。
- bailian_recall 的 query 可以是用户原问题全文，也可以是某个短词。
已选定实验室则带 lab_id。百炼只返回知识，不返回 SQL 或数字。
- 同一 query 本轮已召回则不要重复。召回为空时不要猜字段，文档也没有则 ask_user。
```

「进度台账」里「含义不明的要素…用 knowledge_search / knowledge_read」改为：

```
含义不明的要素先记「待确认」，随后检索：
本地 md → knowledge_search / knowledge_read；
词条/字段/取值 → bailian_recall（全文或短词）。
弄清后立刻用同一 key 更新台账。
```

其余段落保持原文。

---

## 4. 明确不改

- `ask_lab` 参数、实验室路由、四个 Lab token 校验
- `query_db` 是否绑定实验室 SQL、探测 SQL 纪律
- ODS / Retail Pharmacy 等实验室权限
- `knowledge_search` / `knowledge_read` 实现
- 澄清卡协议、`ask_user` 实现

---

## 5. 实现顺序

1. `BailianRecallRunner`：createSession + run，`message.text` 为 `{query, lab_type}`
2. `build_bailian_recall_tool` + 可选 `BAILIAN_AGENT_CODE` / `BAILIAN_AUTHORIZATION`
3. 改 `AGENT_SYSTEM_PROMPT` 知识检索段（§3.4）
4. 前端轨迹 + 评测列「百炼召回」
5. 单测：解析知识 JSON、校验 lab_type、未配置跳过、prompt 含全文/短词
