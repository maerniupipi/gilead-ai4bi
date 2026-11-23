# 吉利德 AI4BI 交付说明

当前交付入口、运行配置、数据库 SQL、生产部署和验证步骤已统一到 [README.md](README.md)。

默认模式为 `dual`，同时提供数据库问数与个人 XLSX 问数。原 POC 专用脚本保留在 `deploy/gilead_poc/`，其实际运行连接和密钥由环境提供；原单 XLSX 模式仍可通过 `CHATBOT_MODE=xlsx` 使用。

当前仓库不分发历史 `.env`、POC 数据库账号、实验室 Token、运行数据或模型密钥。迁移既有环境时保留原账号 ID、控制库、工作簿／看板附属数据库以及对应的 `MASTER_KEY`。
