# Gilead AI4BI

医药经营分析应用，包含 Vue 前端、FastAPI 后端与 ReAct Agent。默认同时提供两个入口：

| 入口 | 数据来源 | 主要能力 |
|---|---|---|
| 数据库问数助手 | 已授权的业务数据库与配置的 Bootcamp／百炼实验室 | 自然语言查数、指标口径澄清、经营分析、交互报告 |
| XLSX 问数助手 | 当前账号上传的 Excel | 私有文件问数、医药通用分析、复合图、数据表、看板 |

两个入口共用账号、模型配置与看板工作台，可以从侧栏顶部或账号菜单切换。XLSX 上传、会话和查询按账号隔离；看板通过“分享与权限”授权其他账号查看或编辑。

## 1. 环境与目录

- Python **3.11+**，推荐 3.11 或 3.13。
- Node.js **20+**、npm；前端依赖使用 `package-lock.json`。
- 本地快速启动使用 SQLite；部署控制库可选 **MySQL 8.0.16+**。业务数据库账号使用只读权限。
- 问答需要一个 OpenAI Chat Completions 兼容模型接口。数据库问数还需要实验室连接及已发布的数据源绑定；XLSX 使用内置只读查询引擎。

```text
backend_v2/                 FastAPI、Agent、权限、模型、数据库迁移和测试
frontend/                   Vue 3、ECharts、问答、看板和管理界面
knowledge_gilead/            六表医药示例的字段、业务口径和实验室知识
start.sh                    默认双入口本地启动脚本
start_xlsx_demo.sh           原单 XLSX 演示启动脚本
start_jilide.sh              原专用 POC 启动脚本，需要自行准备 POC 连接配置
deploy/setup_env.py          生成私有环境文件、独立密钥与管理员初始密码
deploy/generate_sql.py       从当前代码生成 SQL，不读取或导出用户数据
deploy/sql/                 MySQL 和 SQLite 初始化 SQL
deploy/xlsx_demo/            可选的五账号及医药模拟看板初始化工具
```

仓库包含源码、配置模板和建表 SQL。实际 `.env`、模型密钥、数据库密码、用户上传文件、私有数据库和历史运行凭证由部署环境提供。

## 2. 本地启动

```bash
git clone https://newgitlab.digitalchina.com/gilead/gilead-ai4bi.git
cd gilead-ai4bi
./start.sh --setup-only
```

首次执行会安装锁定依赖并生成 `backend_v2/.env`，文件权限为 `0600`。管理员账号默认 `admin`，随机初始密码见文件中的 `XIAOYING_BOOTSTRAP_ADMIN_PASSWORD`。也可以在首次执行前设置环境变量 `GILEAD_ADMIN_PASSWORD`，指定自己的初始密码。

保留生成的 `XIAOYING_MASTER_KEY`，它用于解密已保存的模型和数据源凭证。配置生成器遇到已有文件会保留原文件。

```bash
./start.sh
```

- 前端：<http://127.0.0.1:15173/>
- 后端：<http://127.0.0.1:18001/>
- 健康检查：<http://127.0.0.1:18001/api/v2/health/ready>

脚本先升级控制库，再启动前后端；`Ctrl+C` 关闭本次启动的进程。端口被占用时可以指定其他端口：

```bash
BACKEND_PORT=18011 FRONTEND_PORT=15183 ./start.sh
```

如果手动安装依赖：

```bash
python3 -m venv backend_v2/.venv
backend_v2/.venv/bin/python -m pip install -r backend_v2/requirements-runtime.lock -e backend_v2
npm --prefix frontend ci
backend_v2/.venv/bin/python deploy/setup_env.py
cd backend_v2
.venv/bin/python tools/manage_db.py upgrade
```

## 3. 两个入口的配置

`backend_v2/.env` 中的 `XIAOYING_CHATBOT_MODE` 控制目录：

| 配置 | 入口 |
|---|---|
| `dual`（默认） | 数据库问数 + 个人 XLSX 问数 |
| `xlsx` | 仅个人 XLSX 问数 |
| `full` | 原完整目录，包括 DDI、行为样例和自建助手 |

切换配置后重启后端。模式切换保留工作簿、会话及看板。原环境若显式配置了 `xlsx`，升级后需把该值改为 `dual`。

### 3.1 配置模型

管理员登录后进入“模型管理”，新增模型，填写接口地址、API Key、模型 ID，测试并启用。也可以在空环境中通过 `XIAOYING_MODEL_ENDPOINT_URL`、`XIAOYING_MODEL_API_KEY`、`XIAOYING_MODEL_ID` 初始化模型。环境变量示例见 [backend_v2/.env.example](backend_v2/.env.example)。

当前版本使用 Chat Completions 兼容接口。已有模型配置由控制库和加密凭证文件保存；更新环境变量不会覆盖已启用模型。

### 3.2 数据库问数

1. 执行下节 SQL，或准备已有业务库的只读账号。
2. 将业务库主机加入 `XIAOYING_DATA_SOURCE_ALLOWED_HOSTS`，重启后端。
3. 管理员在“数据源”新增连接、测试连接，选择允许的表、创建并发布修订，配置 `actual` 等领域绑定。
4. 在“实验室连接”中配置并测试 Bootcamp 或百炼连接，绑定对应实验室 API Access ID／Token；数据库助手默认查询 `actual` 域。
5. 按实际数据库字段更新 `knowledge_gilead/` 的口径与字典，发布后进入“数据库问数助手”提问。

Bootcamp 采用同次 trace 的 SQL 执行证据；百炼连接按数据源、对象白名单、只读检查及用户数据范围执行。默认 `LAB_FALLBACK=off`，连接缺失或执行失败时会明确提示。

例如：`按月展示销售金额、目标金额和达成率，并分析目标缺口最大的城市。` 实际结果取决于所绑定数据库的字段与数据，仓库中的业务 SQL 只创建空表。

### 3.3 XLSX 问数

切换到“XLSX 问数助手”，在“我的文件”上传：

- 每个账号最多 **10 个 XLSX**，每个不超过 **10 MiB**。
- 每个文件最多 **5 个 sheet**，包含空白和隐藏工作表。
- 首行为非空、唯一的字段名，后续为数据；读取 Excel 已保存的单元格值。公式应在 Excel 中计算并保存。
- 大文件接收后在后台解析，页面展示排队与解析状态；刷新可恢复状态，相同请求重试不会重复入库。
- 文件只进入上传账号的查询上下文。每轮分析固定所选文件；文件被移除后会提示重新上传。

遇到字段、单位、时间范围、目标口径或去重维度不明确的问题，助手会主动澄清。金额、数量、达成率和总数可组合为多柱多线图，并保留图下数据表。

## 4. SQL 建库与版本

完整文件与执行顺序见 [deploy/sql/README.md](deploy/sql/README.md)。数据库账号与应用登录账号分开管理。

### 4.1 MySQL：新安装

先用 DBA 账号执行。下列命令会提示输入数据库密码：

```bash
mysql -h DB_HOST -u DBA_USER -p < deploy/sql/mysql/001_databases.sql
mysql -h DB_HOST -u DBA_USER -p < deploy/sql/mysql/002_control_schema.sql
# 可选：使用六表医药业务结构时执行
mysql -h DB_HOST -u DBA_USER -p < deploy/sql/mysql/003_business_schema.sql
```

把 `004_users_and_grants.example.sql` 中的密码及允许连接的主机改为实际值后执行，创建控制库账号与业务只读账号。

编辑 `backend_v2/.env`：

```dotenv
XIAOYING_DATABASE_URL=mysql+pymysql://gilead_react_app:URL_ENCODED_PASSWORD@DB_HOST:3306/gilead_agent_loop?charset=utf8mb4
XIAOYING_DB_AUTO_CREATE=false
XIAOYING_CHATBOT_MODE=dual
XIAOYING_DATA_SOURCE_ALLOWED_HOSTS=DB_HOST
```

`002_control_schema.sql` 创建 **31 张应用表**和 Alembic 版本表，不含预置用户或密钥。管理员在首次启动时根据 `.env` 创建。业务表需另行装载自己的数据；业务库也可使用已存在的结构。

### 4.2 SQLite：本地或单机控制库

`./start.sh` 会执行迁移并自动创建附属数据库。手工建库的完整 SQL 也已提供：

```bash
mkdir -p backend_v2/var
sqlite3 backend_v2/var/control.sqlite3 < deploy/sql/sqlite/001_control_schema.sql
sqlite3 backend_v2/var/chatbots.sqlite3 < deploy/sql/sqlite/002_chatbots_schema.sql
sqlite3 backend_v2/var/workspaces.sqlite3 < deploy/sql/sqlite/003_workspaces_schema.sql
```

即使控制库使用 MySQL，当前单机版仍会把以下附属数据保存在 `XIAOYING_SECRET_STORE_PATH` 同目录：

| 文件 | 内容 |
|---|---|
| `chatbots.sqlite3` | 助手目录、个人工作簿、解析后的单元格、上传任务与恢复状态 |
| `workspaces.sqlite3` | 看板、图表／表格／HTML 快照、共享成员与布局版本 |
| `secrets.json` | 加密的模型和数据源凭证 |
| `branding/` | 上传的品牌素材 |

该目录需要读写权限与持久卷。当前结构面向单实例部署，扩容前需把附属存储与上传解析队列改为共享服务。

### 4.3 已有环境升级

先备份控制库和附属数据，保留原 `.env` 与 `MASTER_KEY`。已有库使用迁移：

```bash
cd backend_v2
.venv/bin/python tools/manage_db.py upgrade
.venv/bin/python tools/manage_db.py status
```

`manage_db.py` 会读取与后端相同的 `.env`，避免迁移指向错误数据库。初始化 SQL 仅用于空库；已有库不要重新导入它。当前迁移版本为 `20261025_0015`。

## 5. 生产部署

推荐反向代理提供 HTTPS；应用静态资源与 API 可由一个 FastAPI 服务提供。

1. 准备 Python、MySQL／SQLite 和持久目录，安装依赖并执行建库或迁移。
2. 参考配置生成器创建生产配置，例如先设置 `XIAOYING_DATA_SOURCE_ALLOWED_HOSTS` 和控制库连接，再运行 `python3 deploy/setup_env.py --environment production --output /安全目录/gilead.env`。
3. 设置 `ENVIRONMENT=production`、`DB_AUTO_CREATE=false`、独立的认证与 SQL 审批 HMAC 密钥、Fernet `MASTER_KEY`、允许的数据源主机；生产关闭 SQLite **业务数据源**与 mock 回退。控制库可以使用 SQLite。
4. 把 `SECRET_STORE_PATH`、`SECRET_KEY_PATH`、`BRANDING_ASSETS_PATH` 改为持久目录绝对路径，配置实际前端域名的 CORS。
5. 构建前端并运行后端：

```bash
npm --prefix frontend ci
npm --prefix frontend run build
cd backend_v2
# 后端从本目录 .env 读取配置；systemd 可通过 EnvironmentFile 注入。
XIAOYING_STATIC_ROOT=../frontend/dist .venv/bin/python -m uvicorn xiaoying_quick.app:app --host 0.0.0.0 --port 9999
```

如果从其他路径启动，显式配置 `PYTHONPATH`、静态目录和知识目录的绝对路径。生产配置必须能通过 `Settings` 校验。服务就绪以 `/api/v2/health/ready` 返回 200 为准；前端端口在反向代理之后开放。

五个独立业务账号和模拟默认看板为可选初始化项：

```bash
# GILEAD_DEMO_PASSWORD 从部署环境设置；不会写入代码或日志。
PYTHONPATH=backend_v2/src backend_v2/.venv/bin/python deploy/xlsx_demo/provision.py --data-dir /持久目录
```

该命令仅适用于 SQLite 控制库，创建 `Gilead001`–`Gilead005`，为每人生成可独立编辑的医药模拟看板；保留已有看板修改。用于 MySQL 控制库时，在账号管理中创建用户，再按业务需要建立或共享看板。应用管理员、五个业务账号和 MySQL 账号的密码独立配置。

## 6. 图表、看板与导出

支持多种 ECharts 图表、复合柱线图、指标卡和可见数据表。可以把单张图、单张表、整份 HTML 分析加入看板，也可共享看板。历史会话先恢复消息，再按可见区域加载报告；初始定位最新用户问题，生成过程保留用户的滚动位置。

问答与看板支持导出 PPTX、XLSX、PDF。PPTX 使用可编辑标题／指标／表格与图表图片；XLSX 保存已有分析结果的单元格数据；PDF 包含中文字体和分页。导出保留当次分析范围，明细以已保存的查询结果为准。PPT／PDF 单张数据表最多展示 100 行，长表请使用 XLSX；问答查询结果上限为 5,000 行，不等于原始工作簿全量导出。

## 7. 验证与维护

```bash
cd backend_v2
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest tests -q
cd ../frontend
npm test
npm run build
cd ..
backend_v2/.venv/bin/python deploy/generate_sql.py --check
```

SQL 由当前 ORM 和附属存储结构生成；字段变更后运行 `deploy/generate_sql.py` 更新快照，并补充已有数据库的 Alembic 迁移。

定期备份控制库、`chatbots.sqlite3`、`workspaces.sqlite3`、加密凭证及对应 `MASTER_KEY`。SQLite 使用其备份接口或停服后复制，避免在写入时直接复制单个数据库文件。切换仓库或服务器时，按原账号 ID 一起迁移文件和看板数据。

常见定位：

- 登录成功但没有可用模型：在模型管理中测试并启用模型。
- 数据库问数无连接：检查已发布的数据源修订、领域绑定和实验室连接。
- 找不到历史 XLSX 或凭证解密失败：核对持久目录、文件属主和原 `MASTER_KEY`。
- 只有一个入口：核对启动脚本及环境变量是否仍显式设置 `CHATBOT_MODE=xlsx`。
- readiness 提示 schema 过旧：在同一配置下执行 `tools/manage_db.py upgrade`。
