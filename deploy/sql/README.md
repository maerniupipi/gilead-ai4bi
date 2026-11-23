# 数据库初始化 SQL

这些文件只包含结构、索引和控制库迁移版本，不含账号密码、模型 Key、历史对话或真实业务明细。

## 新建 MySQL 环境

按顺序执行，SQL 中的库名默认是 `gilead_agent_loop` 和 `gilead_poc`：

1. `mysql/001_databases.sql`：建立控制库和可选业务库。
2. `mysql/002_control_schema.sql`：31 张控制表、全部索引和 Alembic 版本表。
3. `mysql/003_business_schema.sql`：可选的 6 张医药业务表及 1 张模拟数据装载标记表。
4. `mysql/004_users_and_grants.example.sql`：填写自己的密码和来源主机后执行，授权控制库与业务只读账号。

MySQL 版本要求 8.0.16+。应用登录用户由后端创建，业务库 SQL 不预置应用用户。业务表为物理表，名称为：

- `sales_target_ai4bi`
- `v_ai4bi_ddi_sales`（兼容数仓命名的物理表）
- `prod_master`
- `teri_hierachy`（保留业务字典中的字段命名）
- `ddi_coverage`
- `data_range_config`

已有自己的业务库时，可只建立控制库，并在数据源管理中连接现有结构。

## SQLite

- `sqlite/001_control_schema.sql`：控制库，含迁移版本。
- `sqlite/002_chatbots_schema.sql`：助手、工作簿、个人文件归属和后台上传任务。
- `sqlite/003_workspaces_schema.sql`：看板、内容、布局和共享权限。

SQL 不包含助手种子数据。后端首次启动会依据 `CHATBOT_MODE=dual` 初始化数据库问数和个人 XLSX 助手。辅助 SQLite 文件放在 `SECRET_STORE_PATH` 的父目录；控制库使用 MySQL 时，这两个附属文件仍需要持久化。

## 升级与重新生成

初始化 SQL 只用于空库。对已有控制库使用：

```bash
cd backend_v2
.venv/bin/python tools/manage_db.py upgrade
```

结构来源为当前 ORM 与附属存储实现：

```bash
backend_v2/.venv/bin/python deploy/generate_sql.py
backend_v2/.venv/bin/python deploy/generate_sql.py --check
```

修改既有字段时，还要提供 Alembic 增量迁移。不要把业务数据、认证信息或运行数据库的全量 dump 放入这些文件。
