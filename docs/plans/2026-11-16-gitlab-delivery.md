# GitLab 双入口交付 Implementation Plan

> **For Claude:** Use the existing coding workflow to implement and verify each task in this plan.

**Goal:** 将本地前后端及 Agent 完整源码交付到 gilead/gilead-ai4bi，默认开放数据库问数与个人 XLSX 问数，提供可执行 SQL 和完整部署 README。

**Architecture:** 保留目标仓库初始提交，在独立工作目录发布当前源码快照。新增 dual 目录模式（数据库 ddi + 私有 xlsx），保留 full/xlsx 兼容模式和现有账号数据。控制库使用 Alembic 管理，交付 MySQL 建库/迁移 SQL 与附属 SQLite 初始化 SQL，运行密钥通过环境配置注入。

**Tech Stack:** FastAPI、SQLAlchemy/Alembic、MySQL 8 / SQLite、Vue 3、Vite、ECharts。

---

### Task 1: 安全的源码快照
- 从当前工作区复制源码及未提交功能，保留原目录的本地运行配置。
- 不复制 .env、密钥、用户数据库和私有运行证据，清理源码内历史凭证并提供环境变量模板。
- 保留新 GitLab master 的初始提交，避免继承历史仓库中的运行凭证。

### Task 2: 双入口
- 新增并默认启用 dual；数据库问数与按账号隔离的 XLSX 助手同时出现在入口、账号菜单与侧栏切换中。
- 兼容 full 和 xlsx；切换模式不删除历史会话、文件或看板。
- 验证双入口的查询路由、上传配额、访问隔离、会话恢复与切换。

### Task 3: 数据库交付
- 生成 MySQL 控制库创建与完整 Alembic SQL；提供六张业务表和只读账号授权模板。
- 提供 SQLite 控制库/工作簿/看板建表 SQL，注明辅助数据库位于持久目录。
- 补齐 ORM 与迁移的索引差异，验证新库从 SQL 初始化及迁移版本一致。

### Task 4: 运行说明与配置
- 重写 README，包括依赖、目录、配置生成、本地启动、SQL 执行顺序、模型/数据库/实验室接入、生产部署、备份与升级。
- 提供不依赖历史私有配置的启动入口和管理员初始化流程。

### Task 5: 验证与推送
- 在交付目录运行后端、前端测试和生产构建，对默认双入口及 SQL 建库进行冷启动验证。
- 扫描提交中的已知密钥和私有文件，复核 diff。
- 正常提交并推送目标 master，确认远端提交与本地一致，返回仓库和 README 链接。
