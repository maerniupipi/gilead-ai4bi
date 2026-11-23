# Bootcamp / 百炼实验室连接设计与实施计划

**Goal:** 在 `bootcamp-con` 分支中保留百炼连接，增加可切换的 Bootcamp 实验室连接，以清晰的配置页和可重复的演示数据验证完整问数流程。

**Architecture:** 平台选择与连接配置由后端持久化，分别保存两个提供方的地址、实验室标识与加密凭据。运行开始后固定本次选择，使用相应适配器完成 `ask_lab → query_db → 证据 → 回答`。Bootcamp 的查库已在平台完成，`query_db` 复用同一次实验室执行返回的数据，避免将平台 SQL 发给本地其他数据库。

**Tech Stack:** Vue 3、FastAPI、SQLAlchemy / Alembic、HTTPX、SQLite、pytest。

## 1. 用户行为

- 配置页提供「Bootcamp 实验室」「阿里云百炼」两个选项，并明确显示当前生效的平台。
- 切换时保留另一平台的配置；旧百炼配置仍可使用。
- Bootcamp 配置使用完整服务地址、内部访问密钥、实验室 API 调用 ID；实验室 ID 与访问密钥分别说明。
- 测试连接返回成功或可理解的失败原因，不显示密钥或上游原始异常。
- 本地 mock 模式显式标识；真实 Bootcamp 失败时不能静默退回 mock。

## 2. 真实 Bootcamp 契约

当前平台目录：`/Users/shaox/Desktop/AzCode/AI大集合/new-chat`。

```text
POST http://127.0.0.1:8050/internal/lab/sql-evidence
X-Internal-Token: <服务内部凭据，仅在后端保存>
Content-Type: application/json

{"content":"2026年各区域销售额","id":"DEMOSALES1","features":{}}
```

返回结构：

```text
trace_id, rewritten_query, sql, sqls, sql_data, evidence, chart_spec, steps, error
sql_data = {columns, rows, row_count, ...}
evidence = [{label, sql, columns, rows, row_count, ...}]
```

该端点运行 SQL 生成、SQL 执行与证据整理，仅跳过最终文本总结。不能将它描述为上游仅生成 SQL。公共 SSE `/api/autobi/gateway/v2/lab` 使用管理端登录 JWT；本次后端到后端集成使用内部端点及内部凭据，不依赖浏览器登录会话。

## 3. 证据复用与配置隔离

1. 每次运行创建独立 Bootcamp 适配器，缓存本次响应中按 SQL 对应的数据证据。
2. `ask_lab` 继续返回 SQL 候选和平台 trace ID；上游文字说明不作为事实数据。
3. `query_db` 只接受本次实验室给出的候选 SQL，读取对应证据并转换成现有执行结果结构。未匹配的 SQL 明确报错，不访问本地源数据库。
4. 保留结果行上限和截断标记；重复读取缓存不再发起平台请求。
5. 百炼继续沿用已有 SQL 生成及授权数据源执行路径。
6. 凭据存储与安全视图分开；前端只知道是否已配置，切换不删除另一个平台的凭据。

## 4. 两类演示数据

| 类型 | 数据位置 | 数据量 | 验证范围 |
|---|---|---:|---|
| ReAct 本地 mock | 本项目独立生成的 SQLite 演示数据 | 四表共 92,160 行 | 查询、澄清恢复、轨迹与导出；页面使用时仍需配置主模型，自动测试以脚本模型验证工具链 |
| 真实 Bootcamp 的既有 demo | 平台 `simple_sql_demo`，每次按确定性生成器建内存 SQLite | 销售 2,160 行、库存 48 行、客户 72 行 | 真实 HTTP、内部鉴权、平台 SQL 与结果、适配器缓存及追踪 |

两类数据分别标识，不互相宣称来源。平台 demo 没有可复用的 SQLite 文件路径：每次请求创建 `:memory:` 数据库并关闭；不能把 ReAct 的本地 SQLite 配成“平台数据源”。

平台当前可用实验室：

| 调用 ID | 问题 | 预期列 | 预期结果行数 |
|---|---|---|---:|
| `DEMOSALES1` | 2026年各区域销售额 | `region`, `total_sales_amount` | 6 |
| `DEMOSTOCK1` | 按仓库汇总库存量 | `warehouse`, `total_stock_qty` | 4 |
| `DEMOCUSTS1` | 各城市客户数量 | `city`, `total_customer_count` | 12 |

## 5. 实施与验证

1. 新建平台连接持久化模型和迁移，增加配置读取、保存及连接测试接口；测试旧配置默认行为、凭据隐藏、平台切换与配置保留。
2. 在 `backend_v2/src/xiaoying_quick/infrastructure/lab_http/bootcamp.py` 增加 Bootcamp 适配器；测试鉴权头、响应契约、失败分支、证据匹配与缓存隔离。
3. 运行组装读取当前平台，Bootcamp 使用缓存执行器，百炼沿用既有数据源执行器；验证不会跨数据源执行 SQL。
4. 新增平台配置页与中文提示，检查加载、保存、切换、连接测试、错误反馈及构建。
5. 建立明确标识的本地 mock 数据与端到端演示，验证问题、SQL、数据、回答和结果呈现。
6. 使用 `backend_v2/tools/smoke_bootcamp.py` 调用三个既有平台 demo；核对每个响应 HTTP 200、SQL 候选、结果列和行数，检查两次读取同一 SQL 仍只产生一次 HTTP 请求。

从 `backend_v2` 运行真实平台检查：

```bash
# 运行环境已设置 BOOTCAMP_INTERNAL_TOKEN 或 INTERNAL_SERVICE_TOKEN
.venv/bin/python tools/smoke_bootcamp.py --output var/bootcamp-smoke.json

# 或从平台配置文件读取 INTERNAL_SERVICE_TOKEN（不执行 .env 中的内容）
.venv/bin/python tools/smoke_bootcamp.py \
  --platform-root '/Users/shaox/Desktop/AzCode/AI大集合' \
  --output var/bootcamp-smoke.json
```

脚本不内置平台开发默认密钥。若平台 `.env` 未配置此变量，应由运行环境显式注入平台实际使用的凭据。报告包含结果列、行数、结果校验值和 trace ID，不保存凭据、原始响应或原始数据行；失败时返回非零退出码。

本次平台检查会新增查询 trace，不重建数据库、不修改非 demo 项目，也不需要重复执行现有 demo seed。

## 6. 完成验证

- 后端全量测试 399 项通过，前端 88 项测试与构建通过。
- 页面检查覆盖单实验室保存、两平台配置保留、演示开关，以及桌面和手机宽度。
- 真实 Bootcamp 的三个 demo 实验室均返回有效 SQL 与证据，报告为 `backend_v2/var/bootcamp-smoke.json`。
- 使用项目当前激活的 `sensenova-6.8-flash-lite` 模型，在临时控制面数据库与 secret store 中运行「演示数据：2026年各地区销售额，请导出Excel」，完成实验室 SQL、查数、回答和下载：返回 6 个地区，Excel 下载 HTTP 200，文件结构有效，标有「演示数据」。脱敏报告为 `backend_v2/var/bootcamp-live-model-smoke.json`。
- 自动集成测试另覆盖两平台 Mock、真实接口失败、SQL 证据复用、澄清暂停后切换全局平台再恢复。真实百炼服务本次没有做端到端重测。
