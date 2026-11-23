#!/usr/bin/env bash
set -Eeuo pipefail
GILEAD_DELIVERY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-18001}"
FRONTEND_PORT="${FRONTEND_PORT:-15173}"
case "${1:-}" in --setup-only|'') ;; *) echo '用法：./start.sh [--setup-only]' >&2; exit 2 ;; esac
command -v node >/dev/null && command -v npm >/dev/null || { echo '请安装 Node.js 20+ 和 npm。' >&2; exit 1; }
node -e 'if (Number(process.versions.node.split(".")[0]) < 20) process.exit(1)' || { echo '需要 Node.js 20+。' >&2; exit 1; }
if [[ ! -x "$GILEAD_DELIVERY_ROOT/backend_v2/.venv/bin/python" ]]; then
  GILEAD_PYTHON_BIN="${PYTHON_BIN:-python3}"
  "$GILEAD_PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 11), "需要 Python 3.11+"'
  "$GILEAD_PYTHON_BIN" -m venv "$GILEAD_DELIVERY_ROOT/backend_v2/.venv"
fi
export PYTHONPATH="$GILEAD_DELIVERY_ROOT/backend_v2/src${PYTHONPATH:+:$PYTHONPATH}"
if ! "$GILEAD_DELIVERY_ROOT/backend_v2/.venv/bin/python" -c 'import fastapi, alembic, pymysql, openpyxl, pptx, reportlab, sqlglot' >/dev/null 2>&1; then
  "$GILEAD_DELIVERY_ROOT/backend_v2/.venv/bin/python" -m pip install -r "$GILEAD_DELIVERY_ROOT/backend_v2/requirements-runtime.lock" -e "$GILEAD_DELIVERY_ROOT/backend_v2"
fi
if [[ ! -x "$GILEAD_DELIVERY_ROOT/frontend/node_modules/.bin/vite" ]]; then
  (cd "$GILEAD_DELIVERY_ROOT/frontend" && npm ci --no-audit --no-fund)
fi
if [[ ! -f "$GILEAD_DELIVERY_ROOT/backend_v2/.env" ]]; then
  "$GILEAD_DELIVERY_ROOT/backend_v2/.venv/bin/python" "$GILEAD_DELIVERY_ROOT/deploy/setup_env.py"
fi
if [[ "${1:-}" == '--setup-only' ]]; then
  echo '依赖与私有配置已准备完成。'
  exit 0
fi
"$GILEAD_DELIVERY_ROOT/backend_v2/.venv/bin/python" - "$BACKEND_PORT" "$FRONTEND_PORT" <<'PY'
import socket, sys
for port in map(int, sys.argv[1:]):
    with socket.socket() as listener:
        try: listener.bind(('127.0.0.1', port))
        except OSError: raise SystemExit(f'端口 {port} 已被占用，请通过 BACKEND_PORT / FRONTEND_PORT 调整。')
PY
(cd "$GILEAD_DELIVERY_ROOT/backend_v2" && .venv/bin/python tools/manage_db.py upgrade)
backend_pid=''; frontend_pid=''
cleanup() {
  [[ -z "$backend_pid" ]] || kill "$backend_pid" 2>/dev/null || true
  [[ -z "$frontend_pid" ]] || kill "$frontend_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
(cd "$GILEAD_DELIVERY_ROOT/backend_v2" && exec .venv/bin/python -m uvicorn xiaoying_quick.app:app --host 127.0.0.1 --port "$BACKEND_PORT") &
backend_pid=$!
(cd "$GILEAD_DELIVERY_ROOT/frontend" && export VITE_DEV_API_TARGET="http://127.0.0.1:$BACKEND_PORT" && exec node_modules/.bin/vite --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort) &
frontend_pid=$!
"$GILEAD_DELIVERY_ROOT/backend_v2/.venv/bin/python" "$GILEAD_DELIVERY_ROOT/deploy/gilead_poc/wait_ready.py" "$BACKEND_PORT" "$FRONTEND_PORT"
printf '数据库问数与 XLSX 问数已启动：http://127.0.0.1:%s\n' "$FRONTEND_PORT"
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do sleep 1; done
exit 1
