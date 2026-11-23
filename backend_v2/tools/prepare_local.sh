#!/usr/bin/env bash
# Seed local MySQL AI_CVRM plus the MySQL AgentLoop control plane.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

MYSQL_USER="${MYSQL_USER:-root}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-REPLACE_PRIVATE_CREDENTIAL}"
PYTHON="${PYTHON_BIN:-${ROOT}/.venv/bin/python}"

if ! command -v mysql >/dev/null 2>&1; then
  echo "错误：未找到 mysql 客户端。" >&2
  exit 1
fi

if [[ ! -x "${PYTHON}" ]]; then
  echo "错误：未找到 ${PYTHON}；请先创建 backend_v2/.venv。" >&2
  exit 1
fi

echo "正在写入本地 AI_CVRM 样例数据…"
mysql -u"${MYSQL_USER}" -p"${MYSQL_PASSWORD}" < "${ROOT}/tools/seed_local_ai_cvrm.sql"

echo "正在初始化 AgentLoop 控制面并绑定本地数据源…"
"${PYTHON}" "${ROOT}/tools/seed_local_runtime.py"

echo "本地数据已就绪。账号 admin / REPLACE_PRIVATE_CREDENTIAL"
