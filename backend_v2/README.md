# Gilead AI4BI Backend

FastAPI + ReAct Agent，提供数据库问数、个人 XLSX 问数、澄清、图表、看板、导出和后台管理。

完整的安装、SQL、部署、备份和接入说明见项目根目录的 [README](../README.md)。

## 本地开发

在仓库根目录运行 `./start.sh --setup-only`，它会安装运行依赖并生成私有配置。随后：

```bash
cd backend_v2
.venv/bin/python tools/manage_db.py upgrade
.venv/bin/python -m uvicorn xiaoying_quick.app:app --host 127.0.0.1 --port 18001
```

默认 `CHATBOT_MODE=dual`。管理员账号和初始密码来自 `.env`，首次启动创建账号；更换配置不会覆盖已有用户密码。

## 验证

```bash
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest tests -q
.venv/bin/python tools/manage_db.py check
```

API 文档位于开发后端 `/docs`；健康检查为 `/api/v2/health/ready`。模型密钥与数据源密码在持久目录加密保存，保留相应 `MASTER_KEY`。

## 数据库

- 控制表通过 Alembic 管理，新建库可使用 `../deploy/sql/` 的完整 SQL。
- `tools/manage_db.py` 使用与后端相同的 `.env`，支持 `upgrade`、`check` 和 `status`。
- `chatbots.sqlite3`、`workspaces.sqlite3`、加密凭证及品牌素材与控制库一起备份。
- `tools/seed_uat_runtime.py` 等原环境工具保留供迁移参考，需要通过环境变量提供连接和凭证；新环境按根 README 配置。
