#!/usr/bin/env bash
set -Eeuo pipefail
XLSX_DEMO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-18001}"
FRONTEND_PORT="${FRONTEND_PORT:-15173}"
XLSX_DEMO_DATA="$XLSX_DEMO_ROOT/backend_v2/var/xlsx-demo"
mkdir -p "$XLSX_DEMO_DATA/knowledge" "$XLSX_DEMO_DATA/branding"
[[ -x "$XLSX_DEMO_ROOT/backend_v2/.venv/bin/python" && -x "$XLSX_DEMO_ROOT/frontend/node_modules/.bin/vite" ]] || "$XLSX_DEMO_ROOT/start_jilide.sh" --setup-only
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
    printf '端口 %s 已被占用，请调整端口后启动。\n' "$port" >&2
    exit 1
  fi
done
export XIAOYING_CHATBOT_MODE=xlsx
export XIAOYING_DATABASE_URL="${XLSX_DEMO_DATABASE_URL:-sqlite:///$XLSX_DEMO_DATA/control.sqlite3}"
export XIAOYING_DB_AUTO_CREATE=true
export XIAOYING_SECRET_STORE_PATH="$XLSX_DEMO_DATA/secrets.json"
export XIAOYING_SECRET_KEY_PATH="$XLSX_DEMO_DATA/master.key"
export XIAOYING_BRANDING_ASSETS_PATH="$XLSX_DEMO_DATA/branding"
export XIAOYING_KNOWLEDGE_ROOT="$XLSX_DEMO_DATA/knowledge"
export XIAOYING_LAB_FALLBACK=off
export XIAOYING_LAB_FALLBACK_ON_ERROR=false
export XIAOYING_REPORT_DATA_LABEL='用户上传的 XLSX 工作簿'
export XIAOYING_REPORT_SAMPLE_DATA=false
backend_pid=''
frontend_pid=''
cleanup() {
  [[ -z "$backend_pid" ]] || kill "$backend_pid" 2>/dev/null || true
  [[ -z "$frontend_pid" ]] || kill "$frontend_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
(
  cd "$XLSX_DEMO_ROOT/backend_v2"
  exec .venv/bin/python -m uvicorn xiaoying_quick.app:app --host 127.0.0.1 --port "$BACKEND_PORT"
) &
backend_pid=$!
(
  cd "$XLSX_DEMO_ROOT/frontend"
  export VITE_DEV_API_TARGET="http://127.0.0.1:$BACKEND_PORT"
  exec node_modules/.bin/vite --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort
) &
frontend_pid=$!
"$XLSX_DEMO_ROOT/backend_v2/.venv/bin/python" "$XLSX_DEMO_ROOT/deploy/gilead_poc/wait_ready.py" "$BACKEND_PORT" "$FRONTEND_PORT"
printf 'XLSX 问数演示已启动：http://127.0.0.1:%s\n数据保存在 %s\n' "$FRONTEND_PORT" "$XLSX_DEMO_DATA"
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do sleep 1; done
exit 1
