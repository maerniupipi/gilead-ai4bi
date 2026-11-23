# 技能包：把实验室拆成「自己召回 + SQL 生成技能」

> 本文只定方案，不实施。第一期只做一个技能包：`sql_generate`。

---

## 1. 要解决什么

现在的 `ask_lab` 是黑盒：远程实验室内部先做关键词召回，再生成候选 SQL。主链路看不到中间召回，也换不了生成方法。

已经能自己做的部分：

- `knowledge_search` / `knowledge_read`：本地口径与实验室文档
- `bailian_recall`：平台词条、字段、取值
- `update_ledger`：已确认口径

缺的是：把「参考信息 + 原子问题」交给一个**可替换的 SQL 生成器**。这个生成器做成技能包，挂在智能体上勾选。

目标行为：

```text
用户问题
  → 主智能体拆原子、选实验室
  → 实验室智能体用现有工具召回（自己做）
  → 拼成「参考信息」
  → sql_generate 技能包写出候选 SQL
  → 主智能体 query_db 执行
  → 数字只来自查库结果
```

远程 `ask_lab` 过渡期可留作备用，默认不勾。

---

## 2. 三层不要混

已经有「工具」和「智能体」。技能包是第三层。

| 层 | 是什么 | 页面能做什么 |
|---|---|---|
| 工具 | 可执行动作：召回、查库、澄清 | 只看说明，不能改 |
| 技能包 | 某类活的做法：提示词、输入输出约定、生成步骤 | 只看名称/说明；在智能体里勾选 |
| 智能体 | 谁来跑：工具子集 + 子智能体 + 技能包 | 开停、勾选 |

子智能体是「谁」；技能包是「怎么做这件事」。实验室智能体勾选「SQL 生成」，不是再造一个智能体。

技能包和工具一样：**代码里有才登记得上**，页面不能发明。

---

## 3. 第一期只做一个包：`sql_generate`

### 3.1 职责

做：根据已召回的参考信息，生成候选 SQL（`sql` + 简短理解），形状与现在实验室返回对齐。

不做：

- 不再做召回（不调百炼、不搜知识）
- 不执行 SQL（必须交回 `query_db`）
- 不向用户澄清（缺要素写在返回里，由实验室智能体或主智能体决定）
- 不探测权限、不改 ODS / 零售口径（这些必须已经出现在参考信息里）

### 3.2 输入 / 输出

输入：

| 字段 | 含义 |
|---|---|
| `question` | 原子化查数问题 |
| `lab_id` | `actual` / `demand` / `ext_simple` / `ext_complex` |
| `context` | 已经拼好的参考信息：表/字段/取值、KPI、已确认口径、时间锚点、上一跳 SQL |

输出：与 `ask_lab` 相同的候选列表，便于主智能体和 Trace 不用换渲染。

```text
candidates[]: { candidate_no, sql, narrative }
```

### 3.3 实现（第一期最小）

提示词先用仓库里现成的 `实验室Prompt/{Actual,Demand,External-*}/SQL生成提示词.md`，按 `lab_id` 选择。模型用当前激活的聊天模型。

以后要换更准的 skill，只换这一包的实现（提示词文件或生成器），智能体配置页不用改。

### 3.4 挂在谁身上

挂在**实验室智能体**，不挂主智能体。

主智能体若直接勾选 SQL 生成，容易回到「自己写取数 SQL」、丢掉权限口径。主智能体继续：拆问题、委托、`query_db`、回答。

实验室智能体默认工具（方向，实施时再定默认勾选）：

- 召回：`knowledge_search`、`knowledge_read`、可选 `bailian_recall`
- 技能包：`sql_generate`
- 备用：`ask_lab`（对照期）
- 不要：`query_db`、`ask_user`、`export_xlsx`

---

## 4. 运行时怎么走

```text
主智能体
  └─ 调用 实验室智能体(question, lab_id)
        ├─ 召回工具 → 词条/字段/口径
        ├─ 组装 context（参考信息）
        ├─ sql_generate(question, lab_id, context)
        └─ 返回候选 SQL
  └─ query_db(候选 SQL)
  └─ 回答
```

参考信息建议固定几块，和现在送给实验室的 `loop_prompt_1..5` 对齐，但所有权在我们这边，不再塞进远程 `features`：

1. 术语与字段取值（百炼 + 本地知识）
2. 已确认口径
3. 时间锚点（数据最新月，不是日历今天）
4. KPI 公式
5. 上一跳已核验 SQL（仅 `attach_upstream` 时）

权限口径（ODS、零售渠道等）必须作为召回结果进入第 1 或第 2 块。技能包看不到的口径，写出来的 SQL 就不会带上。这是拆开黑盒后最大的风险，要用评测集对一下「以前实验室会带、技能包漏掉」的题。

---

## 5. 配置怎么长

在现有智能体配置弹层加第三组，仍然只勾名称：

```text
工具
子智能体
技能包     ← 第一期只有「SQL生成」
```

落库：现有 `agent_configs` 增加 `skill_pack_ids`（JSON 字符串数组），校验必须是代码目录的子集。未知名字拒绝。

代码目录（示意）：

```text
SkillPackSpec
  id: sql_generate
  name: SQL生成
  blurb: 用已召回的参考信息生成候选 SQL，不查库
  allowed_on: lab_sql          # 建议只允许实验室智能体勾选
```

页面：技能包目录只读（和工具目录一样）；智能体里勾选。

---

## 6. 和现有实验室的关系

| | 现在 `ask_lab` | 技能包路径 |
|---|---|---|
| 召回 | 实验室内部 | 我们的工具 |
| 写 SQL | 实验室内部 | `sql_generate` |
| 权限过滤 | 实验室生成时带上 | 必须先召回到 context |
| 执行 | `query_db` | 不变 |
| 失败换路 | 换问法再 `ask_lab` | 换问法或补召回再生成；对照期可回退 `ask_lab` |

第一期建议：**技能包为主，`ask_lab` 备用**。实验室智能体两个都勾时，提示词写清：有足够参考信息就走技能包；参考信息明显不足且备用开启，才 `ask_lab`。

---

## 7. 明确不做（第一期）

- 不接外部任意 GitHub skill、不在页面上传技能包
- 技能包不能直接查库、不能绕过 `query_db`
- 主智能体不直接勾 `sql_generate`
- 不做并行子智能体（另议）
- 不把技能包做成第四条问答流水线；它只是实验室智能体循环里的一个生成步骤

---

## 8. GitHub 上能参考什么

公开仓库里，**几乎没有**「带业务口径的制药查数 SQL 技能」。能抄的是做法，不是现成的阿斯利康口径包。按对我们的用处分类：

### 8.1 值得借鉴（生成流程，不是直接安装）

| 来源 | 地址 | 能抄什么 | 不能当什么 |
|---|---|---|---|
| text-to-sql-agent | https://github.com/kweinmeister/text-to-sql-agent | 生成 → SQLGlot 校验 → 执行失败再纠正。我们已有 SQLGlot 只读检查，`query_db` 失败后模型重试可以做成技能包内的纠正环 | 它会自己连库执行；我们执行必须仍走 `query_db`。Schema 从库里抽，我们的口径在知识/百炼 |
| agent-studio `text-to-sql` | https://github.com/oimiragieo/agent-studio/blob/main/.claude/skills/text-to-sql/SKILL.md | SKILL.md 形态：先给 schema、生成前校验表字段、禁止无 schema 瞎写、SELECT 要列清单 | 示例是通用电商表，没有实验室/权限口径 |
| Anthropic Cookbook Text-to-SQL | https://github.com/anthropics/anthropic-cookbook/tree/main/capabilities/text_to_sql | RAG 取 schema、少样本、复杂题用逐步推理 | 教学材料，不是可挂载包 |
| KWDB `kwdb-text2sql-aiot` | 见 KWDB Agent Skills 介绍（KaiwuDB 仓库配套） | 先发现 schema，再按任务类型选参考文件，生成后附字段映射和验证清单 | 时序库方言，业务无关 |
| dbt-skillz | https://github.com/atlasfutures/dbt-skillz | 把领域知识编译成 agent 可读的 Markdown，当「参考信息」而不是生成器 | 它解决的是 context 打包，对应我们的知识灌入，不是写 SQL |

### 8.2 看起来像 SQL skill、但对「生成查数 SQL」用处不大

| 来源 | 地址 | 实际做什么 |
|---|---|---|
| MotherDuck Agent Skills | https://github.com/MotherDuck-Open-Source/agent-skills （介绍：https://motherduck.com/blog/motherduck-agent-skills/） | DuckDB 连接、方言、分析工作流，不是 NL→业务 SQL |
| supabase-postgres-best-practices | https://github.com/supabase/agent-skills | Postgres 生命周期、RLS、迁移 |
| sql-optimization-patterns（wshobson/agents） | skills.sh / lazyskills 收录 | EXPLAIN、索引，优化已有 SQL |
| sql-expert | https://github.com/questfortech-investments/claude-code-skills | 通用写 SQL / 方言转换 |
| VoltAgent `sql-pro` | https://github.com/VoltAgent/awesome-claude-code-subagents | 优化与仓库设计子智能体 |
| PostgreSQL Claude Skill Package | https://github.com/OpenAEC-Foundation/PostgreSQL-Claude-Skill-Package | 38 个 Postgres 专题（JSONB、分区、RLS），偏 DBA |
| Jam SQL / mssql-tools | 各类数据库 CLI skill | 教 agent 怎么连库、跑查询，不负责按口径生成 |

结论：第一期**不要**把这些仓库当可安装技能包接进来。技能包格式可以对齐 `SKILL.md`（frontmatter + 步骤 + 反模式），内容用我们自己的实验室 SQL 提示词 + 召回 context。开源项目里最该吸收的三条：

1. **生成器不负责召回**：schema / 口径作为输入喂进去。
2. **生成后先语法校验再执行**：继续用现有 SQLGlot SELECT-only，失败观察回模型。
3. **纠正环针对执行错误**：`query_db` 报错后由实验室智能体改问法或补 context，再调技能包，而不是主智能体手写 SQL。

---

## 9. 风险

| 风险 | 为什么 | 缓解 |
|---|---|---|
| 丢掉实验室权限层 | ODS / 零售过滤以前藏在实验室生成里 | 召回必须覆盖这些口径；评测集对比 `ask_lab` 与技能包 |
| 模型看见表结构就自己 invent 条件 | 开源 text-to-SQL 常把探测当生成 | 技能包禁止使用未出现在 context 里的表、字段、枚举值 |
| 主智能体绕过实验室智能体 | 若主循环也能调生成器 | `sql_generate` 只允许实验室智能体勾选 |
| 提示词与代码双份 | `实验室Prompt/` 与技能包目录漂移 | 第一期直接读现有 md，不复制一份 |

---

## 10. 实施顺序（未开工）

1. 代码登记 `sql_generate` 技能包目录；`agent_configs` 增加 `skill_pack_ids`。
2. 智能体配置页第三组「技能包」。
3. 实验室智能体循环里：召回 → 组装 context → 调技能包 → 返回候选。
4. 用现有评测集对比：`ask_lab` vs 技能包（尤其权限口径题）。
5. 对照稳定后再考虑默认关掉 `ask_lab`。

当前状态：方案待对齐，**不写代码**。

---

## 11. 需要对齐的点

1. 第一期技能包为主、`ask_lab` 备用——是否同意。
2. `sql_generate` 是否只允许实验室智能体勾选。
3. 参考信息是否沿用 `loop_prompt_1..5` 五块，还是重新命名。
