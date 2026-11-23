#!/usr/bin/env bash
# 把 02_AgentLoop.sql 通过 SAE 接口导入。
# 用法：
#   SAE_URL=https://你的SAE域名 PROVISION_TOKEN=<your-provision-token> \
#     bash tools/import_agentloop.sh dist/sae-sql/02_AgentLoop.sql

set -euo pipefail

SQL="${1:-dist/sae-sql/02_AgentLoop.sql}"
SAE_URL="${SAE_URL:?请设置 SAE_URL，例如 https://xxx.sae.aliyuncs.com}"
TOKEN="${PROVISION_TOKEN:?请设置 PROVISION_TOKEN}"

if [[ ! -f "${SQL}" ]]; then
  echo "找不到 SQL 文件：${SQL}" >&2
  exit 1
fi

curl -fsS -X POST "${SAE_URL%/}/api/v2/system/import-sql" \
  -H "X-Provision-Token: ${TOKEN}" \
  -F "file=@${SQL};type=application/sql"
echo
